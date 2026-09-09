# tests claim: a node's standing is a view over what points at it, so a claim
# cannot keep a label its support stopped giving it; one log holds unrelated
# types without relating them; and provenance is stamped, never asserted.
"""The mechanism, over types declared here the way a project declares its own.

Every type below is a fixture rather than a library export, which is the whole
point being tested: `lup.ledger` names no node type, so a suite that used one
of its own would be testing something the library does not ship.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import Field, ValidationError

from lup.coordination.refs import ActorRef
from lup.ledger.journal import LedgerRefusal, LedgerStore
from lup.ledger.models import LedgerEdge, LedgerNode, Standing


class Task(LedgerNode, frozen=True):
    """Work somebody has to do."""

    kind: Literal["fixture:task"] = "fixture:task"
    holder: str = ""

    def standing(self, incoming: list[LedgerEdge]) -> Standing:
        blocking = [edge for edge in incoming if edge.kind == "fixture:blocks"]
        if blocking:
            return Standing(label="blocked", reason=f"{len(blocking)} first")
        return Standing(label="held" if self.holder else "unheld")


class Claim(LedgerNode, frozen=True):
    """A settled result, which may stop being settled."""

    kind: Literal["fixture:claim"] = "fixture:claim"
    grade: Literal["measured", "argued", "conjecture"]

    def standing(self, incoming: list[LedgerEdge]) -> Standing:
        if any(edge.kind == "fixture:supersedes" for edge in incoming):
            return Standing(label="superseded", reason="a correction replaced it")
        if any(edge.kind == "fixture:verifies" for edge in incoming):
            return Standing(label="verified", reason=self.grade)
        return Standing(label="unverified", reason=self.grade)


class Handoff(LedgerNode, frozen=True):
    """A body of work transferred, which must say what is still open."""

    kind: Literal["fixture:handoff"] = "fixture:handoff"
    open_questions: list[str] = Field(min_length=1)


class Blocks(LedgerEdge, frozen=True):
    kind: Literal["fixture:blocks"] = "fixture:blocks"


class Supersedes(LedgerEdge, frozen=True):
    kind: Literal["fixture:supersedes"] = "fixture:supersedes"


class Verifies(LedgerEdge, frozen=True):
    kind: Literal["fixture:verifies"] = "fixture:verifies"

    def refusal(self, source: LedgerNode, target: LedgerNode) -> str:
        del source
        if target.author == self.author:
            return "a verification of your own work is not one"
        return ""


NODE_CLASSES: list[type[LedgerNode]] = [Task, Claim, Handoff]


def opened(root: Path, who: str = "alpha") -> LedgerStore:
    """One session's handle on the repository's log."""
    return LedgerStore(root, ActorRef(kind="session", id=who))


def test_a_type_reads_back_as_itself_and_others_are_not_in_the_answer(
    tmp_path: Path,
) -> None:
    """The typed read is a filter, not a cast: nothing comes back that is not one."""
    store = opened(tmp_path)
    store.record(Task, "wire the skill", holder="alpha")
    store.record(Claim, "the bound is 2.5x", grade="argued")

    tasks = store.read(Task)
    claims = store.read(Claim)
    assert [task.holder for task in tasks] == ["alpha"]
    assert [claim.grade for claim in claims] == ["argued"]
    # Each read sees only its own type, over one log holding both.
    assert len(store.lines()) == 2


def test_unrelated_types_share_a_log_without_sharing_a_shape(tmp_path: Path) -> None:
    """One store, four field sets, and no union anywhere a caller can see."""
    store = opened(tmp_path)
    store.record(Task, "re-audit", holder="alpha")
    store.record(Claim, "2.5x", grade="measured")
    store.record(Handoff, "over to you", open_questions=["does it hold?"])

    assert {node.kind for node in store.all_nodes(NODE_CLASSES)} == {
        "fixture:task",
        "fixture:claim",
        "fixture:handoff",
    }
    # The fields are genuinely disjoint: each type answers only for its own.
    assert store.read(Handoff)[0].open_questions == ["does it hold?"]
    assert not hasattr(store.read(Task)[0], "grade")


def test_standing_is_a_view_and_may_regress(tmp_path: Path) -> None:
    """The invariant the whole design exists for: a claim cannot outrun support.

    Nothing stores a status, so nothing has to be revisited when the support
    for one goes away. The label changes because the question is asked again.
    """
    alpha = opened(tmp_path, "alpha")
    beta = opened(tmp_path, "beta")
    claim = alpha.record(Claim, "the bound is 2.5x", grade="argued")
    assert alpha.standing(claim).label == "unverified"

    checker = beta.record(Task, "check it", holder="beta")
    beta.relate(Verifies, checker, claim)
    assert alpha.standing(claim).label == "verified"

    correction = beta.record(Claim, "3.1x", grade="measured")
    beta.relate(Supersedes, correction, claim)
    assert alpha.standing(claim).label == "superseded"


def test_a_type_that_declares_no_standing_takes_the_base_answer(
    tmp_path: Path,
) -> None:
    """A kind with no epistemics is one class and no overrides."""
    store = opened(tmp_path)
    handoff = store.record(Handoff, "over to you", open_questions=["does it hold?"])
    assert store.standing(handoff) == Standing(label="recorded")


def test_what_used_to_need_a_gate_is_now_a_field(tmp_path: Path) -> None:
    """A requirement the type can state refuses at construction, not at a gate."""
    store = opened(tmp_path)
    with pytest.raises(ValidationError):
        store.record(Handoff, "over to you", open_questions=[])
    # And nothing was written, so a refused record leaves no trace.
    assert store.lines() == []


def test_an_edge_may_refuse_the_author_of_what_it_points_at(tmp_path: Path) -> None:
    """The one rule this library keeps about who may say what.

    On the edge rather than the node because only an edge sees both ends, and
    it is a property of the relation: a verification somebody gives their own
    work is not one, whatever a project's epistemics are.
    """
    alpha = opened(tmp_path, "alpha")
    beta = opened(tmp_path, "beta")
    claim = alpha.record(Claim, "the bound is 2.5x", grade="argued")
    checker = alpha.record(Task, "check it", holder="alpha")

    with pytest.raises(LedgerRefusal, match="your own work"):
        alpha.relate(Verifies, checker, claim)
    # Somebody else may, which is what makes the edge worth drawing.
    assert beta.relate(Verifies, checker, claim).target == claim.id


def test_an_edge_crosses_types_because_an_id_is_an_id(tmp_path: Path) -> None:
    """One DAG is for exactly this: a relation between unrelated types."""
    alpha = opened(tmp_path, "alpha")
    beta = opened(tmp_path, "beta")
    task = alpha.record(Task, "re-audit", holder="alpha")
    claim = beta.record(Claim, "2.5x", grade="argued")
    # Drawn by alpha, since beta wrote the claim and may not verify it.
    alpha.relate(Verifies, task, claim)

    assert [edge.source for edge in alpha.into(claim.id)] == [task.id]
    assert [edge.target for edge in alpha.out_of(task.id)] == [claim.id]


def test_provenance_is_stamped_rather_than_asserted(tmp_path: Path) -> None:
    """A writer cannot spell who wrote something, so cannot get it wrong."""
    store = opened(tmp_path, "alpha")
    task = store.record(Task, "re-audit", holder="beta")
    assert task.author == ActorRef(kind="session", id="alpha")
    # The holder is a field the writer chose; the author is not.
    assert task.holder == "beta"


def test_a_node_of_an_undeclared_type_still_reads(tmp_path: Path) -> None:
    """One log outlives any one build, so a reader will meet types it lacks.

    It comes back as the base saying its kind, because the alternatives are
    both worse: refusing makes declining one module unread the whole store,
    and skipping loses a node with nothing said while its edges dangle.
    """
    store = opened(tmp_path)
    claim = store.record(Claim, "the bound is 2.5x", grade="argued")

    without = store.all_nodes([Task])
    assert [node.kind for node in without] == ["fixture:claim"]
    assert type(without[0]) is LedgerNode
    assert store.standing(without[0]) == Standing(label="recorded")
    assert store.resolve(claim.id, [Task]) is not None


def test_two_sessions_append_to_one_log_without_a_lock(tmp_path: Path) -> None:
    """There is no seam between copies, because there is one copy."""
    alpha = opened(tmp_path, "alpha")
    beta = opened(tmp_path, "beta")
    alpha.record(Task, "alpha's", holder="alpha")
    beta.record(Task, "beta's", holder="beta")
    assert {task.holder for task in alpha.read(Task)} == {"alpha", "beta"}
    assert {task.holder for task in beta.read(Task)} == {"alpha", "beta"}


def test_bytes_a_node_attaches_are_named_by_what_they_are(tmp_path: Path) -> None:
    """Content addressing, so nothing arriving later changes what a node meant."""
    store = opened(tmp_path)
    node = store.record(Claim, "2.5x", grade="measured", attachments=[b"the proof"])
    (digest,) = node.attachments
    assert store.blobs.read(digest) == b"the proof"
    # The same bytes attached twice are one blob.
    again = store.record(
        Claim, "2.5x again", grade="measured", attachments=[b"the proof"]
    )
    assert again.attachments == [digest]


def test_a_malformed_line_does_not_poison_a_live_log(tmp_path: Path) -> None:
    """One bad record must not stop a reader of a log somebody is appending to."""
    store = opened(tmp_path)
    store.record(Task, "before", holder="alpha")
    with store.path.open("a", encoding="utf-8") as log:
        log.write("{not json at all\n")
    store.record(Task, "after", holder="alpha")
    assert [task.title for task in store.read(Task)] == ["before", "after"]


def test_the_recorded_time_is_the_caller_s_when_they_supply_one(
    tmp_path: Path,
) -> None:
    """A record replayed from elsewhere keeps when it happened."""
    store = opened(tmp_path)
    when = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
    assert store.record(Task, "replayed", at=when).at == when
