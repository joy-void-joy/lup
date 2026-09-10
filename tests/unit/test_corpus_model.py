"""Standing that reaches through premises, questions, slugs, and what moved.

Written against the second half of syra's invariant — one landing invalidated
ten keystone claims at once — which the one-hop reading could not reproduce,
and against the direction files whose `watch` lists nothing ever read.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from lup.channels.models import utc_now
from lup.coordination.identity import mint_member_id
from lup.coordination.refs import ActorRef
from lup.coordination.repository import RepositoryPeers
from lup.coordination.handoffs import hand_off
from lup.coordination.tasks import Task
from lup_template.corpus import (
    Answers,
    Artifact,
    Claim,
    Correction,
    Question,
    Refutes,
    RestsOn,
    Supersedes,
    Supports,
    Validation,
)
from lup.ledger.journal import LedgerRefusal, LedgerStore
from lup.ledger.models import LedgerNode

CLASSES: list[type[LedgerNode]] = [Claim, Question, Correction, Artifact, Task]


def opened(root: Path, who: str = "alice") -> LedgerStore:
    return LedgerStore(root, ActorRef(kind="session", id=who))


def supported(store: LedgerStore, title: str) -> Claim:
    """A claim with one piece of live evidence behind it."""
    claim = store.record(Claim, title)
    artifact = store.record(
        Artifact,
        f"{title}.log",
        attachments=[b"ok"],
        validation=Validation(schema_id="t", subject_digest="d").model_dump(),
    )
    store.relate(Supports, artifact, claim)
    return claim


def test_a_refuted_premise_takes_down_everything_resting_on_it_transitively(
    tmp_path: Path,
) -> None:
    """The ten-keystone case: A rests on B rests on C; refute C and A falls,
    with the reason naming the chain — and nobody amended A or B.
    """
    store = opened(tmp_path)
    c = supported(store, "c")
    b = supported(store, "b")
    a = supported(store, "a")
    store.relate(RestsOn, b, c)
    store.relate(RestsOn, a, b)

    assert store.standing(a, CLASSES).label == "supported"

    counter = store.record(
        Artifact,
        "counter.log",
        attachments=[b"no"],
        validation=Validation(schema_id="t", subject_digest="x").model_dump(),
    )
    store.relate(Refutes, counter, c)

    reading = store.standing(a, CLASSES)
    assert reading.label == "premise regressed" and not reading.sound
    assert b.id in reading.reason and "premise regressed" in reading.reason
    assert store.standing(c, CLASSES).label == "contradicted"


def test_a_premise_cycle_is_reported_rather_than_followed(tmp_path: Path) -> None:
    store = opened(tmp_path)
    a = supported(store, "a")
    b = supported(store, "b")
    store.relate(RestsOn, a, b)
    store.relate(RestsOn, b, a)

    reading = store.standing(a, CLASSES)

    assert reading.label == "premise regressed" and "cyclic" in reading.reason


def test_a_claim_cannot_rest_on_itself(tmp_path: Path) -> None:
    store = opened(tmp_path)
    a = store.record(Claim, "a")

    with pytest.raises(LedgerRefusal, match="itself"):
        store.relate(RestsOn, a, a)


def test_a_question_is_answered_only_while_its_answer_stands(tmp_path: Path) -> None:
    """Answered is read from the claim, so a question goes back to open when
    the claim answering it loses its footing — without anybody amending it.
    """
    store = opened(tmp_path)
    question = store.record(Question, "how deep do quotes nest?", priority=2)
    assert store.standing(question, CLASSES).label == "open"

    answer = supported(store, "two")
    store.relate(Answers, answer, question)
    assert store.standing(question, CLASSES).label == "answered"

    correction = store.record(Correction, "three", wrong="two")
    store.relate(Supersedes, correction, answer, changes=["the figure"])
    reading = store.standing(question, CLASSES)
    assert reading.label == "open" and "none standing" in reading.reason

    store.amend(question.model_copy(update={"closed": "asked the wrong thing"}))
    [closed] = store.read(Question)
    assert store.standing(closed, CLASSES).label == "closed"
    assert closed.finished() and closed.priority == 2


def test_a_slug_resolves_like_an_id_and_is_taken_once(tmp_path: Path) -> None:
    store = opened(tmp_path)
    claim = store.record(Claim, "the ceiling", slug="renewal-prefix-ceiling")

    assert store.resolve("renewal-prefix-ceiling", CLASSES) == claim
    with pytest.raises(LedgerRefusal, match="already names"):
        store.record(Claim, "another", slug="renewal-prefix-ceiling")

    store.amend(claim.model_copy(update={"text": "2"}))
    assert store.resolve("renewal-prefix-ceiling", CLASSES) is not None
    other = store.record(Claim, "other")
    with pytest.raises(LedgerRefusal, match="already names"):
        store.amend(other.model_copy(update={"slug": "renewal-prefix-ceiling"}))


def test_moved_since_reads_the_log_and_not_a_stored_standing(tmp_path: Path) -> None:
    store = opened(tmp_path)
    before = utc_now()
    a = store.record(Claim, "a", at=before - timedelta(minutes=2))
    b = store.record(Claim, "b", at=before - timedelta(minutes=1))
    c = store.record(Claim, "c", at=before + timedelta(seconds=1))
    store.relate(RestsOn, c, a, at=before + timedelta(seconds=2))

    assert store.moved_since(before) == [c.id, a.id]
    assert store.moved_since(before, [b.id, a.id]) == [a.id]


def test_a_handoff_watch_list_is_recorded_and_the_task_carries_priority(
    tmp_path: Path,
) -> None:
    peers = RepositoryPeers(tmp_path)
    member = mint_member_id()
    peers.join(member, tmp_path / "tree", cli_name="sender")
    store = LedgerStore(tmp_path, ActorRef(kind="session", id=member))
    premise = store.record(Claim, "the ceiling", slug="ceiling")
    task = store.record(Task, "finish it", priority=3)

    result = hand_off(
        peers,
        store,
        "the work",
        open_questions=["whether it holds"],
        tasks=[task.id],
        watch=["ceiling"],
    )

    assert result.handoff.watch == ["ceiling"]
    assert store.read(Task)[0].priority == 3
    assert store.moved_since(result.handoff.at, [premise.id]) == []
