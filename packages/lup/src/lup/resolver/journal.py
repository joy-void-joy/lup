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
from lup.resolver.models import FROZEN
from lup.runtime.models import TurnEvent

JOURNAL_FILE = "journal.jsonl"

type ActorKind = Literal["worker", "reviewer", "merger", "planner"]


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


class JournalEntry(BaseModel):
    """One event, stamped and attributed."""

    model_config = FROZEN

    seq: int
    at: datetime
    actor: ActorRef
    event: TurnEvent


ENTRY_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


class Journal:
    """The run's single ordered record, appended by one writer."""

    def __init__(self, root: Path) -> None:
        self.stream: Stream[JournalEntry] = Stream(root / JOURNAL_FILE, ENTRY_ADAPTER)
        self.next_seq = len(self.stream.read_all())

    def append(self, actor: ActorRef, event: TurnEvent) -> JournalEntry:
        entry = JournalEntry(seq=self.next_seq, at=utc_now(), actor=actor, event=event)
        self.stream.append(entry)
        self.next_seq += 1
        return entry

    def read(self, after_seq: int = -1) -> list[JournalEntry]:
        """Every entry after ``after_seq``, which is what an SSE resume wants.

        Reconnecting replays from ``seq + 1`` rather than from zero, so a
        page open all run does not re-render the whole run whenever its
        connection blinks.
        """
        return [entry for entry in self.stream.read_all() if entry.seq > after_seq]

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
