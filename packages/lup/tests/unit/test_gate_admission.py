"""How much of the machine one gate takes when others are on it.

The failure this is written against is invisible from inside any one run:
every session's gate reports its own timings honestly, and every one of them
is several times what the same suite costs alone. Nobody sees the contention,
so everybody concludes the gate is slow.
"""

from pathlib import Path

from lup.devtools.dev.admission import (
    MINIMUM_WORKERS,
    SLOT_DIRECTORY,
    admitted,
    slot_paths,
)


def test_a_run_with_the_machine_to_itself_keeps_every_worker(tmp_path: Path) -> None:
    """Division is what several runs cost each other, not a standing tax."""
    with admitted(tmp_path, 16) as alone:
        assert alone.workers == 16
        assert not alone.said


def test_a_second_run_halves_what_each_of_them_opens(tmp_path: Path) -> None:
    """Two gates at full width are twice the machine, which is why they crawl.

    Divided, the two together carry about what one carries alone — and both
    still run, which is the whole reason this is a pool and not a lock: the
    gates that legitimately overlap are checking different worktrees.
    """
    with admitted(tmp_path, 16) as first:
        with admitted(tmp_path, 16) as second:
            assert first.workers == 16
            assert second.workers == 8
            assert second.said


def test_a_fourth_run_takes_a_quarter_rather_than_waiting(tmp_path: Path) -> None:
    """Four is what the resolver runs at once, so four is admitted without a queue."""
    with admitted(tmp_path, 16), admitted(tmp_path, 16), admitted(tmp_path, 16):
        with admitted(tmp_path, 16) as fourth:
            assert fourth.workers == 4


def test_the_share_never_narrows_past_running_serially(tmp_path: Path) -> None:
    """Below two workers a suite spells serial, which is slower than contending.

    A machine with few enough cores to reach the floor is one where dividing
    has nothing left to give, and running slightly wide there is the better
    error.
    """
    with admitted(tmp_path, 4), admitted(tmp_path, 4), admitted(tmp_path, 4):
        with admitted(tmp_path, 4) as fourth:
            assert fourth.workers == MINIMUM_WORKERS


def test_a_run_that_waited_out_its_patience_goes_ahead_at_full_width(
    tmp_path: Path,
) -> None:
    """Coordination that fails must not be a gate that fails.

    The case is a slot whose holder died in a way the lock outlived. What it
    costs is the contention this exists to avoid, which is where every session
    was before — and the run says so rather than being quietly narrow.
    """
    with admitted(tmp_path, 16, slots=1):
        with admitted(tmp_path, 16, slots=1, patience=0.0) as pressed:
            assert pressed.workers == 16
            assert any("ran anyway" in said.text for said in pressed.said)


def test_the_slots_belong_to_the_clone_rather_than_to_one_worktree(
    tmp_path: Path,
) -> None:
    """Every worktree of one clone contends for one machine, so they share one pool.

    Kept under the shared git directory for that reason: a pool beneath a
    worktree would be a pool per branch, and branches are exactly what the
    contending sessions differ in.
    """
    (tmp_path / ".git").mkdir()

    [first, *_] = slot_paths(tmp_path, 2)

    assert first.parent.name == SLOT_DIRECTORY
    assert first.parent.parent == tmp_path / ".git"
