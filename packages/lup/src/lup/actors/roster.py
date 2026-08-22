# lup: ignore[constant-declaration]
# The constant here names the roster's own file, which a spawning process and
# an outside door must spell alike to find each other's record at all — an
# identity of this format rather than a choice a caller can make.
"""Who a cohort holds, folded from a record rather than remembered in a dict.

A registry kept in memory answers only for the process that filled it. That is
the wrong shape for a population whose whole purpose is being reachable: the
door that wants to steer a spawn is often not the process that made it, and a
run resumed after a park has forgotten every address it ever minted. Both cases
read as "no such actor" from a store that was simply never rebuilt.

So the population is a stream of two facts — this actor started, this actor
stopped — and everything anyone asks about it is a fold. That costs one pass
over a small file and buys an answer that is the same from inside the spawning
process, from a console in another terminal, and from the same process an hour
after a restart.

Its own file rather than the consumer's journal, because the two are read on
completely different schedules. A resolver journal reaches tens of megabytes in
one run, and "which agents do you have?" is asked on every status line.

The fold keys by conversation and keeps the highest round seen, which is what
makes a second round an *advance* rather than a second member. Keyed by label,
one agent taken through two rounds appeared twice while its session store held
one — and the round-one ref left standing answered to none of the addresses
the cohort was by then printing.
"""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter, computed_field

from lup.actors.refs import ActorRef
from lup.channels.models import utc_now
from lup.channels.stream import Stream

ROSTER_FILE = "roster.jsonl"


class RosterRecord(BaseModel, frozen=True):
    """One thing that happened to a member, and what it makes of that member.

    The fold asks each record what the member becomes rather than testing
    which record it is holding. A reader that branched on the variant would
    be a filter going stale the moment a third kind of thing can happen to an
    agent — paused, adopted, handed over — and the fold is the one place that
    would silently keep working while ignoring it.
    """

    actor: ActorRef
    at: datetime

    def applied(self, standing: "SpawnedActor | None") -> "SpawnedActor | None":
        """The member as this record leaves it, or None where it says nothing."""
        raise NotImplementedError


class ActorSpawned(RosterRecord, frozen=True):
    """One agent started, and what it was asked for.

    The task is recorded here rather than left to the caller's memory because
    it is what an operator reads to decide which spawn they meant. An address
    alone distinguishes agents without describing any of them.
    """

    type: Literal["spawned"] = "spawned"
    task: str

    def applied(self, standing: "SpawnedActor | None") -> "SpawnedActor | None":
        """This agent, at the round this record starts it on.

        A replayed spawn for a round the member has already moved past says
        nothing about where it is now, so the standing entry survives it.
        """
        if standing is not None and self.actor.round < standing.actor.round:
            return standing
        return SpawnedActor(actor=self.actor, task=self.task, running=True)


class ActorFinished(RosterRecord, frozen=True):
    """One agent stopped, and what it left behind.

    Both outcomes ride one record because a reader wants them in one place:
    an empty ``error`` is the agent having concluded, and a non-empty one is
    the reason it did not. Split across two record types, every reader would
    have to merge them back to answer "how did that spawn end".
    """

    type: Literal["finished"] = "finished"
    summary: str = ""
    error: str = ""

    def applied(self, standing: "SpawnedActor | None") -> "SpawnedActor | None":
        """The member, stopped. A finish for nobody invents no member."""
        if standing is None:
            return None
        return standing.model_copy(
            update={"running": False, "summary": self.summary, "error": self.error}
        )


type RosterEntry = ActorSpawned | ActorFinished
"""What the population record carries. Nothing here is about a turn."""


ENTRY_ADAPTER: TypeAdapter[RosterEntry] = TypeAdapter(RosterEntry)


class SpawnedActor(BaseModel, frozen=True):
    """One agent the cohort holds: who it is, and what it is doing.

    It carries the ref rather than a copy of the parts, so what a reader is
    shown and what the send path recognizes cannot drift apart. The address
    is computed for exactly that reason and still serializes, because a tool
    result that named a member without giving a handle on it would leave an
    operator to reassemble one — which is where the spellings disagreed.
    """

    actor: ActorRef
    task: str
    running: bool
    summary: str = ""
    error: str = ""

    @computed_field
    @property
    def address(self) -> str:
        """The spelling that currently reaches this member."""
        return self.actor.label()

    @computed_field
    @property
    def kind(self) -> str:
        """What this agent was spawned as, so a label reads before it is used."""
        return self.actor.kind


class Roster:
    """Every agent one cohort has held, and whether each is still working."""

    def __init__(self, path: Path) -> None:
        self.stream: Stream[RosterEntry] = Stream(path, ENTRY_ADAPTER)

    def spawned(self, actor: ActorRef, task: str) -> None:
        """Record that this address is live, unless the record already says so.

        Idempotent per round, because two callers legitimately announce one
        start: work detached under an address announces it so the caller can
        steer it immediately, and the round that work then opens announces
        the same round again. Appending both would give that round two starts
        and leave a reader measuring how long it took with no way to say
        which of them it ran from.
        """
        if any(
            member.actor.conversation() == actor.conversation()
            and member.actor.round == actor.round
            and member.running
            for member in self.standing()
        ):
            return
        self.stream.append(ActorSpawned(actor=actor, task=task, at=utc_now()))

    def finished(self, actor: ActorRef, summary: str = "", error: str = "") -> None:
        """Record that this address has stopped, and how."""
        self.stream.append(
            ActorFinished(actor=actor, summary=summary, error=error, at=utc_now())
        )

    def standing(self) -> Iterator[SpawnedActor]:
        """Fold the record into one member per conversation, in first-seen order.

        A round advance updates the member in place rather than adding one,
        because a worker on its second round is the agent that took its first
        — the same conversation, one attempt further on. What a reader wants
        counted is agents, and what they want printed is the address that
        currently reaches each.
        """
        # A fold where a later record revises what an earlier one left: neither
        # a comprehension nor a generator expresses "replace what this key
        # already held". Each record says what it makes of the member, so
        # nothing here tests which record it is holding.
        held: dict[str, SpawnedActor] = {}  # lup: ignore[empty-collection]
        for entry in self.stream.read_all():
            conversation = entry.actor.conversation()
            found = held.get(conversation)  # lup: ignore[dict-get] presence
            applied = entry.applied(found)
            if applied is not None:
                held[conversation] = applied
        yield from held.values()

    def live(self) -> list[SpawnedActor]:
        """Every member, the ones still working first."""
        return sorted(self.standing(), key=lambda member: not member.running)

    def members(self) -> list[ActorRef]:
        """Every member as the ref that currently reaches it.

        Rebuilt from the record rather than from what this process spawned,
        which is what lets a door in another process address the same agents
        the cohort's own tools do.
        """
        return [member.actor for member in self.standing()]

    def reaching(self, address: str) -> ActorRef | None:
        """The member an operator's spelling of an address reaches, if any.

        Matched against what each member answers to rather than parsed out of
        the text, so a label this cohort printed is a label that works and a
        bare id reaches the same agent as the full one. Every consumer that
        instead took an address apart disagreed with whatever printed it, and
        a message sent to the spelling shown reached nobody.
        """
        if not address:
            return None
        return next(
            (member for member in self.members() if address in member.addresses()),
            None,
        )
