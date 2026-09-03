"""What a capture covers, what it does not, and what undo may do about it.

The claim a relaxed lattice rests on is that a mistake can be put back, so
what is pinned here is mostly the ways that claim can be false: a partial
capture, a footprint nothing could enumerate, a path something else changed
afterwards, and a lease held across a question.
"""

from pathlib import Path

import pytest

from lup.policy.checkpoints import (
    PathState,
    RecoveryCoordinator,
    WorktreeLease,
    capture_required,
)
from lup.policy.operations import MutationFootprint


def tree(root: Path) -> Path:
    """One worktree with a file, a script, and a link into it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "kept.txt").write_text("kept\n", encoding="utf-8")
    script = root / "run.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    (root / "link").symlink_to("kept.txt")
    return root


def test_an_exact_footprint_captures_exactly_what_it_names(tmp_path: Path) -> None:
    """The ordinary case, and the reason the wider capture is not the default.

    Holding every precious root in front of `rm build/out` would write the
    whole checkout before a deletion that names one file.
    """
    root = tree(tmp_path / "repo")
    footprint = MutationFootprint(deletions=[root / "kept.txt"])

    assert capture_required(footprint) == "targeted"
    captured = RecoveryCoordinator(tmp_path / "store").capture(
        "op-1", footprint, precious=[root]
    )

    assert captured.complete
    assert [state.path.name for state in captured.pre_state] == ["kept.txt"]


def test_opacity_widens_the_capture_rather_than_refusing_the_operation(
    tmp_path: Path,
) -> None:
    """An unresolved variable is not a policy decision.

    The operation is legible and its blast radius is not, so every precious
    writable root is held and it proceeds. The wider capture is what the
    opacity costs.
    """
    root = tree(tmp_path / "repo")
    footprint = MutationFootprint(
        deletions=[root / "kept.txt"],
        exact=False,
        opacity="the target is a variable this call did not bind",
    )

    assert capture_required(footprint) == "boundary_wide"
    captured = RecoveryCoordinator(tmp_path / "store").capture(
        "op-1", footprint, precious=[root, root / "run.sh"]
    )

    assert captured.complete
    assert {state.path.name for state in captured.pre_state} == {"repo", "run.sh"}


def test_an_operation_that_can_change_nothing_needs_no_capture(
    tmp_path: Path,
) -> None:
    """ "Nothing to capture" and "the capture failed" are different answers.

    Only the second is worth telling somebody about, and reporting a read as a
    failed capture would put a notice on every command in the session.
    """
    captured = RecoveryCoordinator(tmp_path / "store").capture(
        "op-1", MutationFootprint(), precious=[]
    )

    assert captured.evidence() == "absent"
    assert not captured.restorable()


def test_a_capture_that_fell_short_says_so_rather_than_reading_as_protection(
    tmp_path: Path,
) -> None:
    """A partial capture is not a small one.

    Its gap is exactly where nobody looked, so an operation authorized on it
    has been authorized on nothing — and the settlement row that reads this
    keeps its question and says the protection was attempted.
    """
    root = tree(tmp_path / "repo")
    footprint = MutationFootprint(deletions=[root / "kept.txt"])
    incomplete = (
        RecoveryCoordinator(tmp_path / "store")
        .capture("op-1", footprint, precious=[root])
        .model_copy(update={"complete": False, "failure": "the store was unwritable"})
    )

    assert incomplete.evidence() == "failed"
    assert not incomplete.restorable()


def test_absence_is_a_state_a_capture_records(tmp_path: Path) -> None:
    """An undo of a creation has to know the file was not there.

    Unable to tell that from "this was not captured", it either leaves the
    creation in place or deletes a file it never held.
    """
    root = tree(tmp_path / "repo")
    footprint = MutationFootprint(creations=[root / "new.txt"])

    captured = RecoveryCoordinator(tmp_path / "store").capture(
        "op-1", footprint, precious=[root]
    )

    assert captured.complete
    assert captured.pre_state[0].present is False


def test_a_restore_that_drops_the_executable_bit_has_not_restored_the_file(
    tmp_path: Path,
) -> None:
    """Which reads as a successful recovery until something tries to run it."""
    root = tree(tmp_path / "repo")
    state = PathState.read(root / "run.sh")

    (root / "run.sh").chmod(0o644)

    assert state.mode == 0o755
    assert not PathState.read(root / "run.sh").matches(state)


def test_a_symlink_is_captured_as_the_link_it_is(tmp_path: Path) -> None:
    """Restoring the target's content over a link replaces a pointer with a copy.

    A different tree that passes a content comparison, which is the failure
    shape a digest alone cannot see.
    """
    root = tree(tmp_path / "repo")

    state = PathState.read(root / "link")

    assert state.symlink_target == "kept.txt"
    assert state.digest == ""


def test_a_conflict_free_undo_and_a_diverged_one_are_told_apart(
    tmp_path: Path,
) -> None:
    """Post-state is what makes the distinction possible at all.

    Compared against pre-state alone, every successful operation looks like a
    conflict — so every undo would ask and none of them would mean it.
    """
    root = tree(tmp_path / "repo")
    coordinator = RecoveryCoordinator(tmp_path / "store")
    captured = coordinator.capture(
        "op-1", MutationFootprint(overwrites=[root / "kept.txt"]), precious=[root]
    )
    (root / "kept.txt").write_text("changed by the operation\n", encoding="utf-8")
    settled = coordinator.settle(captured)

    assert settled.conflicts() == []

    (root / "kept.txt").write_text("changed by somebody else\n", encoding="utf-8")

    assert settled.conflicts() == [root / "kept.txt"]


def test_one_worktree_serializes_and_siblings_do_not(tmp_path: Path) -> None:
    """A capture of one tree says nothing about another.

    One lock across both would serialize work that never interacts, which is
    the cost of a lease drawn wider than the thing it protects.
    """
    first = tree(tmp_path / "one")
    second = tree(tmp_path / "two")

    held = WorktreeLease(first, "session-a")
    assert held.acquire()

    assert not WorktreeLease(first, "session-b").acquire()
    assert WorktreeLease(second, "session-b").acquire()

    held.release()
    assert WorktreeLease(first, "session-b").acquire()


def test_a_lease_names_its_holder_so_a_stale_one_is_recognizable(
    tmp_path: Path,
) -> None:
    """The holder crashing and the holder working look identical otherwise.

    Breaking a lease is then a deliberate act with a reason rather than a
    timeout nobody sees fire.
    """
    root = tree(tmp_path / "repo")
    lease = WorktreeLease(root, "session-a")
    lease.acquire()

    assert lease.held().startswith("session-a:")


def test_a_lease_taken_as_a_context_refuses_rather_than_silently_sharing(
    tmp_path: Path,
) -> None:
    """Two captures interleaving is the one thing the lease exists to prevent."""
    root = tree(tmp_path / "repo")
    WorktreeLease(root, "session-a").acquire()

    with pytest.raises(RuntimeError, match="lease"):
        with WorktreeLease(root, "session-b"):
            pass
