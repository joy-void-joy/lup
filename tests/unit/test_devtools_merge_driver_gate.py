"""Behavior tests for the one config write left in making a worktree.

Git resolves a merge driver's name from config alone, so no repository can
ship the `lup-ownership` declaration `.gitattributes` carries and every clone
registers it once. That registration is the only reason `dev worktree create`
touches the shared config at all — and a clone that has already made it never
writes there again.

Which is what the refusal in front of it has to know. Asked unconditionally,
it denied a worktree over a write nobody was going to make, wherever the
shared config was held read-only; asked about the outstanding registration,
it stays out of the way of a registered clone and still meets an unregistered
one up front rather than as `File exists` halfway through.
"""

from pathlib import Path

import pytest
import sh
import typer

from lup.devtools.dev import worktree
from lup.devtools.harness.launch import relocation_hint
from tests.unit.repos import commit_file, initialized_repo


@pytest.fixture
def own_config_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read the fixture's config and no reader's own.

    Registration is a per-clone fact, and whether one is outstanding is the
    subject here. A machine whose owner registered the driver globally would
    answer for every fixture at once, and the unregistered case would never
    be reachable on it.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout with one commit, standing where the command would run."""
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    monkeypatch.chdir(work)
    return work


@pytest.fixture
def tree_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The sibling directory worktrees are created in, as `create` resolves it."""
    tree = tmp_path / "tree"
    tree.mkdir()
    monkeypatch.setattr(worktree, "get_tree_dir", lambda: tree)
    return tree


def confine(repo: Path) -> None:
    """Hold `config.lock` the way a sandbox does, without taking a mount.

    A device node where git expects a regular file of its own is what the
    boundary leaves, and it refuses the exclusive create every config write
    begins with — so a run meeting it cannot write config and can do
    everything else.
    """
    (repo / ".git" / "config.lock").symlink_to(Path("/dev/null"))


def register(repo: Path) -> None:
    """Register the driver as a clone's first setup does, on the host."""
    sh.Command("git")(
        "-C", str(repo), "config", "merge.lup-ownership.driver", "true", _tty_out=False
    )
    sh.Command("git")(
        "-C", str(repo), "config", "merge.lup-ownership.name", "keep", _tty_out=False
    )


def test_a_registered_clone_is_not_stopped_by_a_config_it_cannot_write(
    repo: Path, own_config_only: None
) -> None:
    """The refusal that used to fire regardless, over a write already made."""
    register(repo)
    confine(repo)

    worktree.refuse_a_blocked_registration()


def test_an_unregistered_clone_still_meets_the_diagnosis_up_front(
    repo: Path, own_config_only: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case the refusal exists for, said before anything is created."""
    confine(repo)

    with pytest.raises(typer.Exit) as raised:
        worktree.refuse_a_blocked_registration()

    assert raised.value.exit_code == 1
    assert "blocked by the sandbox" in capsys.readouterr().err


def test_an_unregistered_clone_that_can_write_is_let_through(
    repo: Path, own_config_only: None
) -> None:
    """Nothing is refused where the write it guards would simply happen."""
    worktree.refuse_a_blocked_registration()


def test_a_worktree_is_still_made_where_only_the_config_is_held(
    repo: Path, tree_dir: Path, own_config_only: None
) -> None:
    """The whole point, end to end: creation needs no config write of its own.

    The base record lands in the shared `lup/` directory and the guards land
    in the hooks directory, neither of which is `config` — so a clone that
    already resolves the driver cuts a worktree with the config held.
    """
    register(repo)
    confine(repo)

    worktree.create(
        "topic",
        no_sync=True,
        no_copy_data=True,
        base_branch=None,
        launcher=relocation_hint,
    )

    assert (tree_dir / "topic").is_dir()


def test_a_worktree_is_still_removed_where_only_the_config_is_held(
    repo: Path, tree_dir: Path, own_config_only: None
) -> None:
    """Removal writes no config at all, so a held one is nothing to it.

    The entry it rewrites lives under the shared directory's `worktrees/`,
    which `config` is beside rather than part of. Refused on the config lock,
    a removal that would have worked was reported as a sandbox to escape.
    """
    register(repo)
    sh.Command("git")(
        "-C", str(repo), "worktree", "add", str(tree_dir / "topic"), _tty_out=False
    )
    confine(repo)

    worktree.remove("topic", force=False)

    assert not (tree_dir / "topic").exists()
