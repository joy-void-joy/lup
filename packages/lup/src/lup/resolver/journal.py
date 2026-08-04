"""One ordered record of everything every actor in a run did.

A run's actors each hold their own session, and until now nothing outside
those sessions could see what happened inside one. The journal is that
record: one append-only file per run, one writer, every entry naming the
actor it belongs to.

Ordering needs no coordination. A run holds its state lock for its entire
life, so there is exactly one writer and the sequence number is simply the
count of what came before.

The per-actor view and the merged view are the same sequence, filtered or
not. That is deliberate — a merged view assembled from separate per-actor
logs would have to invent an ordering between them, and knowing what
actually happened first is the one thing a reader wants from a merged view.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter

from lup.channels.models import utc_now
from lup.channels.stream import Stream
from lup.resolver.models import (
    FROZEN,
    ConcernProgress,
    MaterialQuestion,
    QuestionAnswer,
    ResolvePhase,
)
from lup.runtime.models import TurnEvent

JOURNAL_FILE = "journal.jsonl"

type ActorKind = Literal["worker", "reviewer", "merger", "planner", "run"]


class ActorRef(BaseModel):
    """Which actor an entry belongs to.

    A round is part of the identity because the same concern's worker is a
    different actor on round two: it holds a different session, and a reader
    tracing a decision needs to know which attempt they are looking at.
    """

    model_config = FROZEN

    kind: ActorKind
    id: str
    round: int = Field(default=1, ge=1)

    def label(self) -> str:
        return f"{self.kind}:{self.id}#{self.round}"


class PhaseChangedEvent(BaseModel):
    """The run moved to a new phase."""

    model_config = FROZEN

    type: Literal["phase_changed"] = "phase_changed"
    phase: ResolvePhase


class ConcernProgressedEvent(BaseModel):
    """One concern reached a new status."""

    model_config = FROZEN

    type: Literal["concern_progressed"] = "concern_progressed"
    progress: ConcernProgress


class QuestionAskedEvent(BaseModel):
    """An actor put a material question to the humans."""

    model_config = FROZEN

    type: Literal["question_asked"] = "question_asked"
    question: MaterialQuestion
    asked_by: str


class AnswerSettledEvent(BaseModel):
    """A question took its answer, from whichever door supplied it."""

    model_config = FROZEN

    type: Literal["answer_settled"] = "answer_settled"
    answer: QuestionAnswer
    door: str


class MessagePostedEvent(BaseModel):
    """A door volunteered something to an actor, or an actor replied.

    An intervention belongs in the record beside what it interrupted. A
    reader scrolling one actor's trace sees the moment someone redirected
    it, in order, against what it was doing — which is the difference
    between a trace and an audit filed somewhere else.
    """

    model_config = FROZEN

    type: Literal["message_posted"] = "message_posted"
    text: str
    door: str
    in_reply_to: str | None = None
    redirect: bool = False


class JoinCompletedEvent(BaseModel):
    """One parent was joined, and whether git had to be adjudicated for it."""

    model_config = FROZEN

    type: Literal["join_completed"] = "join_completed"
    parent: str
    commit: str
    conflicted: bool
    broke: list[str] = Field(default_factory=list)


class JoinAuditEvent(BaseModel):
    """The finished tree was re-checked against every parent that built it."""

    model_config = FROZEN

    type: Literal["join_audit"] = "join_audit"
    parents: list[str]
    outstanding: int
    commit: str


class RunFailedEvent(BaseModel):
    """The run reached a terminal failure."""

    model_config = FROZEN

    type: Literal["run_failed"] = "run_failed"
    reason: str


type RunEvent = (
    PhaseChangedEvent
    | ConcernProgressedEvent
    | QuestionAskedEvent
    | AnswerSettledEvent
    | MessagePostedEvent
    | JoinCompletedEvent
    | JoinAuditEvent
    | RunFailedEvent
)
"""What the run did, as opposed to what one actor's session did.

These share the sequence with turn events rather than living in a file of
their own, because the one thing a reader wants from a merged view is to
know what actually happened first — and an ordering invented between two
logs cannot answer that.
"""


class JournalEntry(BaseModel):
    """One event, stamped and attributed."""

    model_config = FROZEN

    seq: int
    at: datetime
    actor: ActorRef
    event: TurnEvent | RunEvent


ENTRY_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


class JournalTail(BaseModel):
    """What one follower read, and where it should resume."""

    model_config = FROZEN

    entries: list[JournalEntry]
    offset: int


class Journal:
    """The run's single ordered record, appended by one writer."""

    def __init__(self, root: Path) -> None:
        self.stream: Stream[JournalEntry] = Stream(root / JOURNAL_FILE, ENTRY_ADAPTER)
        self.next_seq = len(self.stream.read_all())
        self.run = ActorRef(kind="run", id=root.name)

    def append(self, actor: ActorRef, event: TurnEvent | RunEvent) -> JournalEntry:
        """Record one event.

        Appending reaches no await, so concurrent actors draining their own
        sessions into the same journal interleave between entries and never
        within one. That is what keeps the single-writer claim true once
        every actor holds a live session instead of taking turns.
        """
        entry = JournalEntry(seq=self.next_seq, at=utc_now(), actor=actor, event=event)
        self.stream.append(entry)
        self.next_seq += 1
        return entry

    def record(self, event: RunEvent) -> JournalEntry:
        """Record something the run did rather than something an actor did."""
        return self.append(self.run, event)

    def read(self, after_seq: int = -1) -> list[JournalEntry]:
        """Every entry after ``after_seq``, which is what an SSE resume wants.

        Reconnecting replays from ``seq + 1`` rather than from zero, so a
        page open all run does not re-render the whole run whenever its
        connection blinks.
        """
        return [entry for entry in self.stream.read_all() if entry.seq > after_seq]

    def tail(self, offset: int) -> JournalTail:
        """Whatever arrived after ``offset``, and where to resume.

        A follower reads by byte offset rather than by sequence number so
        that watching a run costs the size of what is new. Filtering by
        ``seq`` re-parses the whole file on every poll, which turns a long
        run into quadratic work exactly as it becomes interesting.
        """
        found = self.stream.read_from(offset)
        if not found:
            return JournalTail(entries=[], offset=offset)
        return JournalTail(
            entries=[pair.item for pair in found], offset=found[-1].commit_offset
        )

    def entry(self, seq: int) -> JournalEntry | None:
        """One entry whole, for a reader expanding a truncated block."""
        return next((item for item in self.stream.read_all() if item.seq == seq), None)

    def actors(self) -> list[ActorRef]:
        """Every actor that has produced an entry, in first-seen order."""
        return list(dict.fromkeys(entry.actor for entry in self.stream.read_all()))

    def for_actor(self, actor: ActorRef, after_seq: int = -1) -> list[JournalEntry]:
        """One actor's slice of the record, which is its whole trace."""
        return [entry for entry in self.read(after_seq) if entry.actor == actor]


async def record_turn(
    journal: Journal, actor: ActorRef, events: AsyncIterator[TurnEvent]
) -> None:
    """Drain one turn's durable events into the journal as they arrive.

    Taking the durable view rather than the live one keeps the journal a
    record of what happened rather than of what was being typed.
    """
    async for event in events:
        journal.append(actor, event)
