"""Holds: waiting for the operator, and answering."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.policy.holds import (
    HeldFile,
    Hold,
    HoldError,
    Holds,
    Response,
    answer,
    waiting,
)
from lup_dev.policy.verdicts import Verdict, VerdictLog

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


def held(
    kit: Kit,
    worktree: Path,
    session: str = "s1",
    *,
    commit: str | None = None,
    verdicts: list[Verdict] | None = None,
) -> Hold:
    store = holds(kit, worktree)
    return store.put(
        Hold(
            key=store.unused(),
            worktree=worktree,
            session=session,
            created=kit.clock.now(),
            files=FILES,
            diff="diff",
            commit=commit,
            verdicts=verdicts or [],
        )
    )


def test_a_hold_waits_until_the_operator_answers(kit: Kit, tmp_path: Path) -> None:
    store = holds(kit, tmp_path)
    hold = held(kit, tmp_path)

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
    hold = held(kit, tmp_path)
    assert store.wait(hold.key, kit.clock, patience=timedelta(seconds=10)) is None
    assert kit.clock.slept == 10


def test_nobody_answers_their_own_hold(
    kit: Kit, tmp_path: Path, runtimes: list[FakeRuntime]
) -> None:
    hold = held(kit, tmp_path)
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
    hold = held(kit, tmp_path)
    answer(kit.layout, hold.key, Response(approved=True), [], kit.clock)
    with pytest.raises(HoldError, match="already answered"):
        answer(kit.layout, hold.key, Response(approved=False), [], kit.clock)
    with pytest.raises(HoldError, match="no hold nope"):
        answer(kit.layout, "nope", Response(approved=False), [], kit.clock)


def test_waiting_holds_are_listed_across_worktrees(kit: Kit, tmp_path: Path) -> None:
    first = held(kit, tmp_path / "a")
    second = held(kit, tmp_path / "b", "s2")
    answer(kit.layout, first.key, Response(approved=True), [], kit.clock)
    assert [hold.key for hold in waiting(kit.layout)] == [second.key]


def test_a_late_answer_is_told_once(kit: Kit, tmp_path: Path) -> None:
    store = holds(kit, tmp_path)
    hold = held(kit, tmp_path)
    store.mark(hold.key, abandoned=True)
    assert store.late() == []
    store.answer(hold.key, Response(approved=True), kit.clock)
    assert [each.key for each in store.late()] == [hold.key]
    store.mark(hold.key, delivered=True)
    assert store.late() == []


def test_a_moves_hold_is_told_once_its_answered(kit: Kit, tmp_path: Path) -> None:
    store = holds(kit, tmp_path)
    hold = held(kit, tmp_path, commit="abc")
    assert not hold.waited()
    assert store.late() == []
    store.answer(hold.key, Response(approved=False), kit.clock)
    assert [each.key for each in store.late()] == [hold.key]


def test_answering_a_hold_nobody_waits_on_logs_the_answer(kit: Kit, repo: Path) -> None:
    verdict = Verdict.model_validate(
        {
            "key": "k:src/new.py",
            "time": kit.clock.now(),
            "session": None,
            "runtime": "asking",
            "tool": "move",
            "worktree": repo,
            "path": "src/new.py",
            "role": "production",
            "outcome": "hold",
            "reasons": ["new-file"],
        }
    )
    hold = held(kit, repo, commit="abc", verdicts=[verdict])
    answer(kit.layout, hold.key, Response(approved=True), [], kit.clock)
    [logged] = VerdictLog(path=kit.layout.verdicts(repo / ".git")).read()
    assert (logged.key, logged.answer) == ("k:src/new.py", "approved")
