"""Holds: waiting for the operator, and answering."""

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from lup_dev.policy.holds import (
    Answer,
    HeldFile,
    Hold,
    HoldError,
    Holds,
    Response,
    answer,
    answer_unheard,
    said_answering,
    waiting,
)
from lup_dev.policy.store import Held, WorktreeState
from lup_dev.policy.verdicts import Verdict, VerdictLog
from lup_dev.stored import write_model

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


def test_a_hold_is_waited_on_while_its_call_holds_its_lock(
    kit: Kit, tmp_path: Path
) -> None:
    """The lock is the OS's, freed where the call's process ends, so a hold whose
    call is gone is told from one a call waits on, by any thread or process."""
    store = holds(kit, tmp_path)
    hold = held(kit, tmp_path)
    assert not store.waited_on(hold.key)
    with store.waiting(hold.key):
        assert store.waited_on(hold.key)
    assert not store.waited_on(hold.key)


def test_a_wait_whose_call_was_interrupted_gives_up_at_once(
    kit: Kit, tmp_path: Path
) -> None:
    store = holds(kit, tmp_path)
    hold = held(kit, tmp_path)
    ended: list[bool] = []

    def interrupted() -> bool:
        return bool(ended)

    kit.clock.on_sleep.append(lambda: ended.append(True))
    assert store.wait(hold.key, kit.clock, ended=interrupted) is None
    assert kit.clock.slept == 2
    # An answer given as the call was interrupted is the session's next call's.
    store.answer(hold.key, Response(approved=True), kit.clock)
    assert store.wait(hold.key, kit.clock, ended=interrupted) is None


def test_a_hold_nobody_answers_gives_up_after_its_patience(
    kit: Kit, tmp_path: Path
) -> None:
    store = holds(kit, tmp_path).model_copy(update={"patience": timedelta(seconds=10)})
    hold = held(kit, tmp_path)
    assert store.wait(hold.key, kit.clock) is None
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


def test_a_hold_settled_with_no_call_waiting_is_told_once_its_answered(
    kit: Kit, tmp_path: Path
) -> None:
    store = holds(kit, tmp_path)
    hold = held(kit, tmp_path)
    store.answer(hold.key, Response(approved=True), kit.clock)
    assert store.late() == []
    store.mark(hold.key, orphaned=True)
    [late] = store.late()
    assert (late.key, late.waited()) == (hold.key, False)


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


def test_a_key_two_stores_keep_is_answered_in_the_worktree_named_and_refused_unnamed(
    kit: Kit, tmp_path: Path
) -> None:
    first = held(kit, tmp_path / "a")
    second = holds(kit, tmp_path / "b").put(
        first.model_copy(update={"worktree": tmp_path / "b"})
    )
    with pytest.raises(HoldError, match="more than one worktree's store"):
        answer(kit.layout, first.key, Response(approved=True), [], kit.clock)
    answered = answer(
        kit.layout,
        second.key,
        Response(approved=False),
        [],
        kit.clock,
        worktree=tmp_path / "b",
    )
    assert answered.worktree == tmp_path / "b"
    assert holds(kit, tmp_path / "a").get(first.key) == first
    assert [hold.worktree for hold in waiting(kit.layout)] == [tmp_path / "a"]


def noted(kit: Kit, worktree: Path) -> Hold:
    """Keep a hold of `worktree`'s, noted as a checkpoint notes it, its call gone."""
    hold = held(kit, worktree)
    kept = Held(hold=hold.key, path=FILES[0].path, blob=FILES[0].blob)
    write_model(holds(kit, worktree).layout.state, WorktreeState(holding=[kept]))
    return hold


GONE = (
    "lup's host service went away while your call waited for the operator's answer "
    "to the change to"
)


def test_an_answer_no_call_hears_says_what_a_checkpoint_will_do_of_it(
    kit: Kit, tmp_path: Path
) -> None:
    key = noted(kit, tmp_path).key
    fine = Response(approved=True, comment="fine")
    approved = answer(kit.layout, key, fine, [], kit.clock, telling=True)
    assert approved.told
    assert said_answering(kit.layout, approved) == (
        f"{GONE} {tmp_path}/src/new.py, which they have since approved: fine. The next "
        "checkpoint in its worktree keeps it, and you hear more only where the file "
        "has changed since and it isn't in place."
    )
    no = Answer(approved=False, time=kit.clock.now())
    declined = approved.model_copy(update={"answer": no})
    assert said_answering(kit.layout, declined) == (
        f"{GONE} {tmp_path}/src/new.py, which they have since declined. The next "
        "checkpoint in its worktree puts it back, or it never lands, and saves your "
        "version."
    )


def test_an_answer_to_a_hold_nothing_notes_says_it_changes_nothing(
    kit: Kit, tmp_path: Path
) -> None:
    """A write outside the worktree, or a hold whose process ended before noting it: no checkpoint settles it."""
    key = held(kit, tmp_path).key
    yes = Response(approved=True)
    hold = answer(kit.layout, key, yes, [], kit.clock, telling=True)
    assert said_answering(kit.layout, hold).endswith(
        "lup lost its hold as it went away, so their answer changes nothing: a change "
        "still there is asked again at a checkpoint, and one that never landed is "
        "yours to make again if it's still wanted."
    )


def test_an_answer_a_call_waits_to_hear_isnt_for_the_inbox_to_tell(
    kit: Kit, tmp_path: Path
) -> None:
    key = noted(kit, tmp_path).key
    yes = Response(approved=True)
    with holds(kit, tmp_path).waiting(key):
        hold = answer(kit.layout, key, yes, [], kit.clock, telling=True)
    assert not hold.told


def test_a_moves_answer_isnt_for_the_inbox_to_tell(kit: Kit, repo: Path) -> None:
    key = held(kit, repo, commit="c0ffee").key
    yes = Response(approved=True)
    assert not answer(kit.layout, key, yes, [], kit.clock, telling=True).told


def test_an_answer_nothing_told_is_said_once_its_call_is_gone(
    kit: Kit, tmp_path: Path
) -> None:
    key = noted(kit, tmp_path).key
    yes = Response(approved=True)
    assert answer_unheard(kit.layout, tmp_path, key) is None
    with holds(kit, tmp_path).waiting(key):
        answer(kit.layout, key, yes, [], kit.clock, telling=True)
        assert answer_unheard(kit.layout, tmp_path, key) is None
    said = answer_unheard(kit.layout, tmp_path, key)
    assert said is not None
    assert said.startswith(
        f"{GONE} {tmp_path}/src/new.py, which they have since approved."
    )
    assert answer_unheard(kit.layout, tmp_path, key) is None


def test_an_answer_settled_since_isnt_said(kit: Kit, tmp_path: Path) -> None:
    key = noted(kit, tmp_path).key
    store = holds(kit, tmp_path)
    with store.waiting(key):
        answer(kit.layout, key, Response(approved=True), [], kit.clock, telling=True)
    write_model(store.layout.state, WorktreeState())
    assert answer_unheard(kit.layout, tmp_path, key) is None
