"""Git's lock protocol read off the filesystem rather than out of its words.

`File exists` is what git says both when a lock is stale and when the path it
names is a device node a sandbox put there, so every test here pins the mount
state — the only thing that separates the two — and none of them pins a
message git printed.

`/dev/null` is reached through a symlink because that is a device node any
user can point at; bind-mounting one, which is what the sandbox does, needs
privileges a test does not have and produces the same `stat`.
"""

import os
from pathlib import Path

import pytest

from lup.devtools.utils import config_lock_diagnosis
from lup.gitlocks import inspect_git_admin
from lup.harness.process import LaunchRequest, LocalProcessLauncher


def admin_dir(root: Path) -> Path:
    """A writable admin directory holding the config git writes through."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "config").write_text("[core]\n\trepositoryformatversion = 0\n")
    return root


def test_a_writable_admin_directory_reports_nothing(tmp_path: Path) -> None:
    state = inspect_git_admin(admin_dir(tmp_path / "admin"))

    assert not state.blocked
    assert state.diagnosis() == ""


def linked_worktree(tmp_path: Path) -> Path:
    """A second worktree of a real repository, sharing the one config it has.

    The lease the resolver hands each concern is exactly this: a checkout
    whose own ``.git`` is a file, whose config lives in the checkout that
    made it, and which therefore cannot be diagnosed by looking beside
    itself.
    """
    launcher = LocalProcessLauncher()
    work = tmp_path / "work"
    for arguments in (
        ["git", "init", "-b", "source", str(work)],
        ["git", "-C", str(work), "config", "user.email", "locks@example.test"],
        ["git", "-C", str(work), "config", "user.name", "Lock Test"],
        ["git", "-C", str(work), "commit", "--allow-empty", "-m", "base"],
        ["git", "-C", str(work), "worktree", "add", str(tmp_path / "leased")],
    ):
        status = launcher.launch(LaunchRequest(arguments=arguments, cwd=tmp_path))
        if status.code != 0:
            raise AssertionError(status.stderr)
    return tmp_path / "leased"


def test_a_real_repository_is_left_alone(tmp_path: Path) -> None:
    """The layout git actually creates, so the check cannot fire on a normal tree."""
    leased = linked_worktree(tmp_path)

    assert config_lock_diagnosis(tmp_path / "work") == ""
    assert config_lock_diagnosis(leased) == ""


def test_a_leased_worktree_is_diagnosed_by_the_config_it_shares(
    tmp_path: Path,
) -> None:
    """A lease has no config of its own, and the shadowed one is what stops it."""
    leased = linked_worktree(tmp_path)
    (tmp_path / "work" / ".git" / "config.lock").symlink_to(Path("/dev/null"))

    assert "blocked by the sandbox" in config_lock_diagnosis(leased)


def test_a_lease_is_diagnosed_by_its_own_admin_directory_too(tmp_path: Path) -> None:
    """`config.worktree` lands in the lease's own directory, not the shared one."""
    leased = linked_worktree(tmp_path)
    own = tmp_path / "work" / ".git" / "worktrees" / leased.name
    (own / "config.worktree").symlink_to(Path("/dev/null"))

    assert "`config.worktree` is a device node" in config_lock_diagnosis(leased)


def test_a_device_node_lock_names_the_sandbox(tmp_path: Path) -> None:
    root = admin_dir(tmp_path / "admin")
    (root / "config.lock").symlink_to(Path("/dev/null"))

    state = inspect_git_admin(root)
    diagnosis = state.diagnosis()

    assert state.device_locks == [root / "config.lock"]
    assert "blocked by the sandbox" in diagnosis
    assert "`config.lock` is a device node" in diagnosis
    assert "none to delete" in diagnosis
    assert "Rerun outside the sandbox" in diagnosis


def test_the_worktree_config_is_watched_alongside_the_lock(tmp_path: Path) -> None:
    """`config.worktree` is the second path a config write can be shadowed at."""
    root = admin_dir(tmp_path / "admin")
    (root / "config.worktree").symlink_to(Path("/dev/null"))

    assert inspect_git_admin(root).blocked


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root creates a file in a mode-555 directory, so the mode cannot "
    "stand in for the mount that would refuse it",
)
def test_an_admin_directory_that_refuses_the_lock_names_the_sandbox(
    tmp_path: Path,
) -> None:
    """What a read-only mount does to the lock protocol: creation is refused."""
    root = admin_dir(tmp_path / "admin")
    root.chmod(0o555)

    state = inspect_git_admin(root)
    diagnosis = state.diagnosis()
    root.chmod(0o755)

    assert state.unwritable_admin
    assert "refuses a new `config.lock`" in diagnosis
    assert "Rerun outside the sandbox" in diagnosis


@pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root writes a mode-444 file, so the mode cannot stand in for a mount",
)
def test_a_config_nobody_may_write_is_not_a_sandbox(tmp_path: Path) -> None:
    """Git renames over `config`; it never writes it, so its mode decides nothing.

    Reading the config's own bits called a plain `chmod 444` a confinement,
    which is the same wrong cause the `File exists` wording gives, arrived at
    from the other side.
    """
    root = admin_dir(tmp_path / "admin")
    (root / "config").chmod(0o444)

    assert not inspect_git_admin(root).blocked


def test_a_lock_name_the_confinement_shadows_is_the_callers_to_give(
    tmp_path: Path,
) -> None:
    """The watched names are git's, and a caller that knows others says so."""
    root = admin_dir(tmp_path / "admin")
    (root / "index.lock").symlink_to(Path("/dev/null"))

    assert not inspect_git_admin(root).blocked
    assert inspect_git_admin(root, ["index.lock"]).blocked
