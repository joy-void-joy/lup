"""How much of the machine one gate takes when others are on it.

The failure this is written against is invisible from inside any one run:
every session's gate reports its own timings honestly, and every one of them
is several times what the same suite costs alone. Nobody sees the contention,
so everybody concludes the gate is slow. `dev test` opens the same suites at
the same width, so it answers to the same pool.
"""

from contextlib import ExitStack
from pathlib import Path
from typing import NoReturn

import pytest
import typer

import lup.devtools.dev.check as check
from lup.devtools.dev.admission import (
    MINIMUM_WORKERS,
    SLOT_DIRECTORY,
    SLOTS,
    admitted,
    held_beside,
    slot_paths,
)
from lup.harness.notice import Notice


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


def test_a_share_is_announced_as_it_is_taken_and_kept_in_the_record(
    tmp_path: Path,
) -> None:
    """A streaming caller hears what the gate reads back, not a second story."""
    heard: list[Notice] = []
    with admitted(tmp_path, 16):
        with admitted(tmp_path, 16, announce=heard.append) as second:
            assert second.said == heard
            assert [
                notice.text.startswith("gate admission: 8 ") for notice in heard
            ] == [True]


def test_a_streaming_caller_hears_the_wait_as_it_begins(tmp_path: Path) -> None:
    """A run queued without a word reads as hung, and is killed as hung.

    The holder gives its slot up only once the waiter has announced its wait,
    so the waiter getting in at all — rather than running anyway when its
    patience ends — is what shows the notice arrived while it was queued.
    """
    heard: list[Notice] = []
    with ExitStack() as holder:
        holder.enter_context(admitted(tmp_path, 16, slots=1))

        def announce(notice: Notice) -> None:
            heard.append(notice)
            holder.close()

        with admitted(
            tmp_path, 16, slots=1, patience=30.0, announce=announce
        ) as queued:
            assert queued.workers == 16
            assert queued.said == heard

    assert ["waiting" in notice.text for notice in heard] == [True]


class Probe(check.TestRoot):
    """A suite that runs nothing, and notes its width and the slots held around it."""

    clone: Path
    handed: list[int] = []
    held: list[int] = []

    def run(
        self,
        paths: list[str],
        workers: int,
        excluded_roots: list[str],
        foreground: bool = False,
    ) -> None:
        del paths, excluded_roots, foreground
        self.handed.append(workers)
        self.held.append(held_beside(slot_paths(self.clone, SLOTS), self.directory))


def suite_in(clone: Path, monkeypatch: pytest.MonkeyPatch) -> Probe:
    """A probe suite in a clone of its own, which `dev test` takes slots in."""
    (clone / ".git").mkdir(parents=True)
    monkeypatch.setattr(check, "project_root", lambda: clone)
    return Probe(name="pytest", directory=clone, clone=clone)


def test_dev_test_holds_a_slot_while_its_suites_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's own suite under another name, so the gate's pool counts it.

    Unadmitted, every agent iterating on a change opened a suite of sixteen
    beside whichever gate held a slot, and the division the gate made was
    undone by runs it could not see.
    """
    suite = suite_in(tmp_path, monkeypatch)

    check.run_selected([suite], [], [], workers=16)

    assert suite.held == [1]
    assert suite.handed == [16]
    assert held_beside(slot_paths(tmp_path, SLOTS), tmp_path) == 0


def test_dev_test_takes_its_share_beside_a_running_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = suite_in(tmp_path, monkeypatch)

    with admitted(tmp_path, 16):
        check.run_selected([suite], [], [], workers=16)

    assert suite.handed == [8]
    assert "gate admission: 8 workers per suite" in capsys.readouterr().out


def test_a_path_under_no_suite_is_refused_before_a_slot_is_asked_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo is answered at once, not after a wait behind four other runs."""
    suite = suite_in(tmp_path / "clone", monkeypatch)

    def refuse(*_: object, **__: object) -> NoReturn:
        raise AssertionError("a slot was asked for before the selection was read")

    monkeypatch.setattr(check, "admitted", refuse)

    with pytest.raises(typer.BadParameter):
        check.run_selected([suite], [str(tmp_path / "elsewhere")], [], workers=16)
