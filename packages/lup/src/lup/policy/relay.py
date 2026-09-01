"""The durable record and single authority for every final ask.

One authority, three renderings. A detached session's question is answered
through this record directly; a supervised worker's reaches its supervisor
through the same record; an interactive session's is rendered by the
provider's native prompt acting as this relay's *renderer*, with the record
still holding the receipt. That the interactive case looks like a native
prompt is a rendering fact, not a second authority — which is what makes
"provider auto-mode cannot answer a Lup ask" enforceable rather than hopeful.

The receipts are asymmetric, and the asymmetry is a measured provider fact
rather than a design choice: a native prompt reports an approval by executing
the call, and reports a rejection by nothing at all. So approval is *observed*
from the execution of the exact call and rejection is *inferred* from its
absence, and the record says which it was. Anything that reads a rejection as
if it were reported would be reading something no provider sends.

Two invariants hold everywhere:

- **The requester never answers its own question.** Eligibility comes from
  authenticated session relationships recorded here, never from whether an
  answering command happens to be visible in somebody's tool list — which
  would make the reviewer whoever the agent could reach.
- **An approval is single-use and binds to a fingerprint.** A payload that
  changed after somebody answered is a fresh question, not a stale approval
  quietly reused.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lup.policy.kernel.semantics import ReviewPurpose, ReviewerRequirement
from lup.policy.operations import Operation

type QuestionState = Literal[
    "pending",
    "approved",
    "rejected",
    "expired",
    "cancelled",
    "preparing",
    "dispatched",
    "completed",
    "failed",
    "in_doubt",
]
"""Where one question stands, including the state nobody wants to be in.

``in_doubt`` is the honest name for a dispatch whose completion evidence never
arrived — a crash between sending an operation and recording its outcome. It
is not retried, because a retry is a second external effect and this
coordinator promises at-most-once dispatch rather than exactly-once effect.
A typed broker may reconcile one where the remote system offers an idempotency
key or an authoritative status query; nothing else may guess.
"""

type ReceiptKind = Literal["observed", "inferred", "recorded"]
"""How an answer reached this record, which decides how much it can be trusted.

``recorded`` is somebody answering through the relay: the strongest, because
the answer and the question met in one place. ``observed`` is an approval read
from the execution of the exact call under a native prompt. ``inferred`` is a
rejection read from that execution not happening, which is the only signal a
native prompt gives for "no" — and saying so is what keeps a silence from
being written down as a decision somebody made.
"""


class Principal(BaseModel, frozen=True):
    """One authenticated party in a session relationship.

    ``human`` is the fact that decides whether a human-only question can end
    here. It is authenticated by the launcher rather than claimed by the
    party, because a principal that could assert its own humanity is a
    supervisor chain with an exit at every link.
    """

    id: str
    kind: Literal["human", "agent"] = "agent"
    supervisor: str = ""

    def human(self) -> bool:
        return self.kind == "human"


class SupervisorChain(BaseModel, frozen=True):
    """Who may answer for whom, resolved from authenticated relationships.

    A missing supervisor, a cycle, or a principal declared as its own
    supervisor all resolve the same way: the question climbs to the human.
    Failing upward rather than closed, because the alternative is a question
    that reaches nobody in a session where somebody is right there — and
    failing *upward* rather than sideways, because the human is the one
    principal whose authority is not derived from another.
    """

    principals: list[Principal] = []

    def find(self, principal: str) -> Principal | None:
        return next((entry for entry in self.principals if entry.id == principal), None)

    def above(self, requester: str) -> list[Principal]:
        """Every principal above one requester, nearest first.

        A cycle stops the walk rather than hanging it: the visited set is what
        makes a self-supervising principal resolve to "nobody above me here",
        which the humans below then answer for.
        """
        seen = {requester}
        # lup: ignore[empty-collection] — a walk whose continuation
        # depends on what it has already visited, which is what stops a
        # cycle rather than hanging on one; no comprehension carries it
        chain: list[Principal] = []
        current = self.find(requester)
        while current is not None and current.supervisor:
            if current.supervisor in seen:
                break
            seen.add(current.supervisor)
            above = self.find(current.supervisor)
            if above is None:
                break
            chain.append(above)
            current = above
        return chain

    def eligible(self, requester: str, requirement: ReviewerRequirement) -> list[str]:
        """Who may answer one question, which never includes the requester.

        A human-only question skips agent supervisors entirely rather than
        letting them decline it, because a chain that can pass a question
        along can also pass it to somebody who answers it.
        """
        above = self.above(requester)
        if requirement == "human_only":
            return [entry.id for entry in above if entry.human()]
        return [entry.id for entry in above]


class Answer(BaseModel, frozen=True):
    """One decision about one question, and who made it.

    ``note`` is how yes-plus-instructions and no-plus-instructions travel
    without a second message. It reaches the agent with the resumption or the
    refusal, which is the moment it is worth reading.
    """

    approved: bool
    principal: str
    receipt: ReceiptKind = "recorded"
    unresolved_chain: bool = False
    """Whether no authenticated chain stood behind this answerer's eligibility.

    Recorded on the answer rather than inferred later, because the question it
    settles is about the moment of answering: an approval given while nothing
    could resolve who was entitled to give it is a weaker receipt than one
    given against a chain, and an audit that could not tell them apart would
    report both as approved.
    """
    note: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PersistentQuestion(BaseModel, frozen=True):
    """One parked ask, durable, with everything needed to resume it exactly.

    The operation is carried whole rather than summarized, because the
    requesting agent must not be the thing that reconstructs it: an agent
    asked to reissue an approved call is an agent that can reissue a
    different one.
    """

    id: str
    operation: Operation
    fingerprint: str
    reason: str
    rule: str = ""
    purpose: ReviewPurpose | None = None
    requirement: ReviewerRequirement = "human_only"
    eligible: list[str] = []
    chain_resolved: bool = True
    """Whether ``eligible`` was resolved from an authenticated chain here.

    False where the boundary that parked this question could not resolve one —
    the compiled dispatcher is hermetic and reaches a verdict without the
    session's principals. It is not the same as resolving to nobody, and
    collapsing the two made every question the live path parked unanswerable.

    What it relaxes is the narrowing and never the invariant: the requester
    still cannot answer, and the answer records that no chain stood behind the
    eligibility, so an audit shows an approval given without one.
    """
    escalation: str = ""
    checkpoint_failure: str = ""
    state: QuestionState = "pending"
    answer: Answer | None = None
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires: datetime | None = None
    completed: datetime | None = None
    outcome: str = ""

    def answerable_by(self, principal: str) -> bool:
        """Whether this principal may answer, which the requester never may.

        Every half is checked here rather than at each caller, because a
        caller that remembered only the eligibility list is a caller that lets
        a requester answer itself by appearing in its own chain.

        An unresolved chain narrows nothing and excludes nobody but the
        requester. That is the honest reading: eligibility unknown here is a
        gap in what this boundary could compute, not a finding that nobody
        qualifies — and read as the second it made the durable queue
        unanswerable on the path that produces most of it.
        """
        if self.state != "pending" or principal == self.operation.requester:
            return False
        return not self.chain_resolved or principal in self.eligible

    def stale(self, now: datetime | None = None) -> bool:
        """Whether this question has passed its expiry without being answered."""
        if self.expires is None or self.state != "pending":
            return False
        return (now or datetime.now(UTC)) >= self.expires

    def summary(self) -> str:
        """One line for a queue, which says what is being asked and by whom."""
        return (
            f"{self.id}  {self.state:<10} {self.requirement:<18}"
            f" {self.operation.summary()}  — {self.reason}"
        )


class QuestionRelay:
    """The durable store every final ask is written to before anybody sees it.

    Append-only on disk, because the failure this has to survive is a crash
    between recording a question and answering it — and a store that rewrites
    a file in place has a window where the question is neither the old one nor
    the new one. Reading folds the log forward, so the last record for an id
    is its state and every earlier record is still there to be read.
    """

    path: Path

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, question: PersistentQuestion) -> PersistentQuestion:
        """Append one question's current state, and return it unchanged."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(question.model_dump_json() + "\n")
        return question

    def questions(self) -> list[PersistentQuestion]:
        """Every question, folded forward to its latest recorded state.

        A line that will not parse is skipped rather than fatal: a torn write
        at the end of the log is the expected shape of a crash, and refusing
        to read the whole queue over it would lose every question before it.
        """
        if not self.path.exists():
            return []
        folded: dict[str, PersistentQuestion] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = PersistentQuestion.model_validate(json.loads(line))
            except ValueError:
                continue
            folded[entry.id] = entry
        return list(folded.values())

    def find(self, question: str) -> PersistentQuestion | None:
        return next((entry for entry in self.questions() if entry.id == question), None)

    def pending(self, principal: str = "") -> list[PersistentQuestion]:
        """Questions still waiting, optionally narrowed to one reviewer's own.

        Narrowed by *eligibility* rather than by ownership: a supervisor
        seeing a question it may not answer is a supervisor about to try.
        """
        waiting = [
            entry
            for entry in self.questions()
            if entry.state == "pending" and not entry.stale()
        ]
        if not principal:
            return waiting
        return [entry for entry in waiting if entry.answerable_by(principal)]

    def answer(
        self,
        question: str,
        principal: str,
        approved: bool,
        note: str = "",
        receipt: ReceiptKind = "recorded",
    ) -> PersistentQuestion:
        """Record one decision, refusing every answer that is not this one's.

        Four refusals, and each is a way an approval could otherwise be reused
        or forged: a question that does not exist, one already answered, one
        whose expiry passed, and one this principal may not answer — which
        includes the requester, always.
        """
        entry = self.find(question)
        if entry is None:
            raise ValueError(f"no question {question!r} is recorded")
        if entry.state != "pending":
            raise ValueError(
                f"question {question!r} is {entry.state} and cannot be answered again"
            )
        if entry.stale():
            return self.record(entry.model_copy(update={"state": "expired"}))
        if not entry.answerable_by(principal):
            raise ValueError(
                f"{principal!r} may not answer {question!r}"
                f" — eligible: {', '.join(entry.eligible) or 'nobody'}"
            )
        return self.record(
            entry.model_copy(
                update={
                    "state": "approved" if approved else "rejected",
                    "answer": Answer(
                        approved=approved,
                        principal=principal,
                        note=note,
                        receipt=receipt,
                        unresolved_chain=not entry.chain_resolved,
                    ),
                }
            )
        )

    def cancel(self, question: str, reason: str = "") -> PersistentQuestion:
        """Withdraw a question nobody needs answered any more."""
        entry = self.find(question)
        if entry is None:
            raise ValueError(f"no question {question!r} is recorded")
        return self.record(
            entry.model_copy(update={"state": "cancelled", "outcome": reason})
        )

    def advance(
        self, question: str, state: QuestionState, outcome: str = ""
    ) -> PersistentQuestion:
        """Move one question along its lifecycle after it was answered.

        The dispatch states live here rather than beside the executor because
        the record is what makes at-most-once dispatch checkable: a
        coordinator that crashed after sending finds ``dispatched`` written
        down, and a coordinator that finds it does not send again.
        """
        entry = self.find(question)
        if entry is None:
            raise ValueError(f"no question {question!r} is recorded")
        completed = (
            datetime.now(UTC)
            if state in ("completed", "failed", "in_doubt")
            else entry.completed
        )
        return self.record(
            entry.model_copy(
                update={"state": state, "outcome": outcome, "completed": completed}
            )
        )

    def dispatchable(self, question: str) -> PersistentQuestion:
        """The approved question this operation may act on, or a refusal saying why.

        The single-use check is here rather than at the executor because every
        route to the executor passes through this: a check at the caller is a
        check each caller can forget, and the one that forgets it is the one
        that dispatches an approval twice.
        """
        entry = self.find(question)
        if entry is None:
            raise ValueError(f"no question {question!r} is recorded")
        if entry.state != "approved":
            raise ValueError(
                f"question {question!r} is {entry.state}, so nothing may be dispatched"
            )
        return entry
