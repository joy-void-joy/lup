"""Behavior tests for the worktree lease expressed as mounts.

The two that carry the module are the ones about siblings: that they are
mounted at all, and that they are mounted read-only. Omitting them looks like
the tighter choice and is the one that lets `git gc` delete their
administrative state.
"""

from pathlib import Path

import pytest

from lup.execution.shell import git
from lup.sandbox.rail import (
    Lease,
    lease_for,
    repository_layout,
    same_path,
    sibling_worktrees,
)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A repository with two linked worktrees, since that is the whole subject."""
    root = tmp_path / "main"
    root.mkdir()
    git("-C", str(root), "init", "-q", "-b", "main")
    git("-C", str(root), "config", "user.email", "test@example.invalid")
    git("-C", str(root), "config", "user.name", "Test")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    git("-C", str(root), "add", "-A")
    git("-C", str(root), "commit", "-qm", "first")
    git("-C", str(root), "worktree", "add", "-q", str(tmp_path / "mine"), "-b", "mine")
    git(
        "-C", str(root), "worktree", "add", "-q", str(tmp_path / "other"), "-b", "other"
    )
    return tmp_path


@pytest.fixture
def bare_repository(tmp_path: Path) -> Path:
    """A bare repository with its worktrees beside it, not under a checkout.

    The layout this rail actually runs in, and the one that puts the shared
    directory in `git worktree list`: a bare repository is reported as the
    main worktree, so it comes back from `sibling_worktrees` as well as from
    `repository_layout`. A normal checkout never produces that, which is why
    the collision it causes needs its own fixture to reach.
    """
    source = tmp_path / "source"
    source.mkdir()
    git("-C", str(source), "init", "-q", "-b", "main")
    git("-C", str(source), "config", "user.email", "test@example.invalid")
    git("-C", str(source), "config", "user.name", "Test")
    (source / "README.md").write_text("readme\n", encoding="utf-8")
    git("-C", str(source), "add", "-A")
    git("-C", str(source), "commit", "-qm", "first")
    bare = tmp_path / "repo.git"
    git("clone", "-q", "--bare", str(source), str(bare))
    git("-C", str(bare), "worktree", "add", "-q", str(tmp_path / "mine"), "-b", "mine")
    return tmp_path


def test_no_path_is_leased_writable_and_read_only_at_once(
    bare_repository: Path,
) -> None:
    """One path, one mode: two mounts at one target have no tie-break to trust.

    The shared directory arrives twice here -- once as the directory this
    lease deliberately makes writable, once as its own sibling, because a
    bare repository is the main worktree git reports. Both spellings said
    read-only until the shared directory became writable, so the collision
    was invisible rather than absent, and it resolves toward writable.
    """
    layout = repository_layout(bare_repository / "mine")
    leased = lease_for(bare_repository / "mine")

    # The collision this pins is only real while git reports it, so the
    # premise is asserted rather than assumed: without this line the test
    # would keep passing against a git that stopped listing the bare main
    # worktree, having quietly stopped exercising anything.
    assert layout.common in sibling_worktrees(bare_repository / "mine")
    assert not set(leased.writable) & set(leased.read_only)
    assert layout.common in leased.writable
    assert layout.common not in leased.read_only


def test_a_lease_makes_its_own_worktree_writable(repository: Path) -> None:
    leased = lease_for(repository / "mine")
    assert repository / "mine" in leased.writable


def test_a_lease_mounts_siblings_read_only_rather_than_leaving_them_out(
    repository: Path,
) -> None:
    """Omitting them is the trap: `git gc` prunes worktrees whose directory is gone.

    A worker that could not see its siblings would find every one of their
    directories absent and delete their administrative state from the shared
    repository as ordinary housekeeping, with no error anywhere. So they are
    present, and unwritable.
    """
    leased = lease_for(repository / "mine")
    assert repository / "other" in leased.read_only
    assert repository / "other" not in leased.writable


def test_a_lease_does_not_mount_the_worktree_it_is_for_as_a_sibling(
    repository: Path,
) -> None:
    leased = lease_for(repository / "mine")
    assert repository / "mine" not in leased.read_only


def test_the_shared_directory_is_writable_with_only_worktrees_held_back(
    repository: Path,
) -> None:
    """`config` has to be writable to cut a worktree; `worktrees/` must not be.

    Three nested modes rather than two: the shared directory writable,
    `worktrees/` read-only inside it, and this worktree's own entry writable
    again within that. Which is what keeps every sibling's entry present and
    unwritable while this worktree's own entry stays writable.
    """
    layout = repository_layout(repository / "mine")
    leased = lease_for(repository / "mine")
    assert layout.common in leased.writable
    assert layout.common not in leased.read_only
    assert layout.common / "worktrees" in leased.read_only
    assert layout.common / "worktrees" / "other" not in leased.writable
    assert layout.private in leased.writable


def test_a_commit_survives_everything_the_lease_leaves_unwritable(
    repository: Path,
) -> None:
    """The claim above, run rather than asserted about a list of names.

    A lease that names the paths a commit needs can always miss one, and
    `logs` is the one it missed: a ref update appends to
    `logs/refs/heads/<branch>` wherever that file already exists, git fails
    the whole update when it cannot, and a contained session could not commit
    at all -- with the reflog this module's docstring rests its case on never
    written either. Comparing names could not catch that, because the name
    nobody thought of is the one missing from both sides.

    Withholding write permission from exactly what the lease calls read-only
    is the cheapest faithful model of the mount table, and it is the only
    shape of test that could have caught a path nobody thought to name.
    """
    worktree = repository / "mine"
    leased = lease_for(worktree)
    layout = repository_layout(worktree)

    def read_only_here(found: Path) -> bool:
        """Whether the deepest mount covering this path is a read-only one.

        The lease nests, so "is this under something writable" answers the
        wrong question: everything in the shared directory is under a
        writable mount, and `worktrees/` is read-only inside it regardless.
        A mount engine settles that by applying parents first and letting the
        deepest entry win, so this has to as well -- a flat test withholds
        nothing here and passes without exercising anything.
        """
        covering = [
            (root, writable)
            for roots, writable in ((leased.writable, True), (leased.read_only, False))
            for root in roots
            if root == found or root in found.parents
        ]
        deepest = max(covering, key=lambda pair: len(pair[0].parts), default=None)
        return deepest is not None and not deepest[1]

    # Every file too, not only the directories holding them. A directory with
    # its write bit off still lets an existing file inside it be rewritten,
    # which a read-only mount does not -- and modelling only the directories
    # is what let a first version of this test pass against the very bug it
    # was written for.
    withheld = [
        found
        for found in [layout.common, *layout.common.rglob("*")]
        if read_only_here(found)
    ]
    # The sibling's administrative entry is the one this has to cover, and
    # naming it here is what stops the set quietly emptying again.
    assert layout.common / "worktrees" / "other" in withheld
    assert layout.private not in withheld
    restored = {entry: entry.stat().st_mode for entry in withheld}
    try:
        for entry in withheld:
            entry.chmod(restored[entry] & ~0o222)
        (worktree / "second.txt").write_text("second\n", encoding="utf-8")
        git("-C", str(worktree), "add", "-A")
        git("-C", str(worktree), "commit", "-qm", "second")
    finally:
        for entry, mode in restored.items():
            entry.chmod(mode)
    assert git.out("-C", str(worktree), "log", "-1", "--format=%s").strip() == "second"


def test_a_plain_checkout_leases_its_own_git_directory(tmp_path: Path) -> None:
    """A repository with no linked worktrees is degenerate here, not broken."""
    git("-C", str(tmp_path), "init", "-q", "-b", "main")
    layout = repository_layout(tmp_path)
    assert not layout.linked()
    assert layout.common in lease_for(tmp_path).writable


def test_paths_are_mounted_at_the_names_the_host_calls_them(
    repository: Path,
) -> None:
    """Forced, not chosen: a linked worktree's `.git` holds an absolute pointer."""
    mapped = same_path([repository / "mine"])
    assert mapped == {repository / "mine": (repository / "mine").as_posix()}


def test_a_declared_human_owned_path_becomes_unwritable(repository: Path) -> None:
    """Taken from the declaration that already exists rather than listed again."""
    (repository / "mine" / "README.md").write_text("x", encoding="utf-8")
    leased = lease_for(repository / "mine", human_owned=[Path("README.md")])
    assert repository / "mine" / "README.md" in leased.read_only


def test_a_human_owned_path_that_is_not_there_is_not_mounted(
    repository: Path,
) -> None:
    """A bind mount of a missing source is how `bwrap` and docker both hard-fail."""
    leased = lease_for(repository / "mine", human_owned=[Path("ABSENT.md")])
    assert repository / "mine" / "ABSENT.md" not in leased.read_only


def test_siblings_are_asked_of_git_rather_than_scanned(repository: Path) -> None:
    """Where sibling checkouts live is the repository's arrangement, not a layout."""
    (repository / "unrelated").mkdir()
    found = sibling_worktrees(repository / "mine")
    assert repository / "other" in found
    assert repository / "unrelated" not in found


def test_a_lease_reports_whether_it_covers_a_path(repository: Path) -> None:
    leased = lease_for(repository / "mine")
    assert leased.covers(repository / "mine" / "src" / "x.py")
    assert not leased.covers(Path("/etc/passwd"))


def test_an_empty_lease_covers_nothing() -> None:
    assert not Lease().covers(Path("/anywhere"))
