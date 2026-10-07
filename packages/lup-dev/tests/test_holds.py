"""Holds: waiting for the operator, and answering."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.policy.holds import HeldFile, HoldError, Holds, Response, answer, waiting

if TYPE_CHECKING:
    from conftest import FakeRuntime, Kit

FILES = [
    HeldFile(
        path=Path("src/new.py"),
        role="production",
        blob="abc",
        reasons=["new-file"],
        asks=["src/new.py is a new production file"],
    )
]


def holds(kit: Kit, worktree: Path) -> Holds:
    return Holds(layout=kit.layout.store(worktree))


def test_a_hold_waits_until_the_operator_answers(kit: Kit, tmp_path: Path) -> None:
    store = holds(kit, tmp_path)
    hold = store.create(tmp_path, "s1", FILES, "diff", kit.clock)

    def answer_later() -> None:
        store.answer(hold.key, Response(approved=False, comment="no"), kit.clock)

    kit.clock.on_sleep.append(answer_later)
    answered = store.wait(hold.key, kit.clock)
    assert answered is not None
    assert (answered.approved, answered.comment) == (False, "no")
    assert kit.clock.slept == 2


def test_a_hold_nobody_answers_gives_up_after_its_patience(
    kit: Kit, tmp_path: Path
) -> None:
    store = holds(kit, tmp_path)
    hold = store.create(tmp_path, "s1", FILES, "diff", kit.clock)
    assert store.wait(hold.key, kit.clock, patience=timedelta(seconds=10)) is None
    assert kit.clock.slept == 10


def test_nobody_answers_their_own_hold(
    kit: Kit, tmp_path: Path, runtimes: list[FakeRuntime]
) -> None:
    hold = holds(kit, tmp_path).create(tmp_path, "s1", FILES, "diff", kit.clock)
    runtimes[1].within = True
    with pytest.raises(HoldError, match="inside a second session"):
        answer(kit.layout, hold.key, Response(approved=True), list(runtimes), kit.clock)
    runtimes[1].within = False
    answered = answer(
        kit.layout,
        hold.key,
        Response(approved=True, comment="ok"),
        list(runtimes),
        kit.clock,
    )
    assert answered.answer is not None
    assert answered.answer.comment == "ok"


def test_a_hold_is_answered_once(kit: Kit, tmp_path: Path) -> None:
    hold = holds(kit, tmp_path).create(tmp_path, "s1", FILES, "diff", kit.clock)
    answer(kit.layout, hold.key, Response(approved=True), [], kit.clock)
    with pytest.raises(HoldError, match="already answered"):
        answer(kit.layout, hold.key, Response(approved=False), [], kit.clock)
    with pytest.raises(HoldError, match="no hold nope"):
        answer(kit.layout, "nope", Response(approved=False), [], kit.clock)


def test_waiting_holds_are_listed_across_worktrees(kit: Kit, tmp_path: Path) -> None:
    first = holds(kit, tmp_path / "a").create(
        tmp_path / "a", "s1", FILES, "diff", kit.clock
    )
    second = holds(kit, tmp_path / "b").create(
        tmp_path / "b", "s2", FILES, "diff", kit.clock
    )
    answer(kit.layout, first.key, Response(approved=True), [], kit.clock)
    assert [hold.key for hold in waiting(kit.layout)] == [second.key]


def test_a_late_answer_is_told_once(kit: Kit, tmp_path: Path) -> None:
    store = holds(kit, tmp_path)
    hold = store.create(tmp_path, "s1", FILES, "diff", kit.clock)
    store.mark(hold.key, abandoned=True)
    assert store.late() == []
    store.answer(hold.key, Response(approved=True), kit.clock)
    assert [each.key for each in store.late()] == [hold.key]
    store.mark(hold.key, delivered=True)
    assert store.late() == []
