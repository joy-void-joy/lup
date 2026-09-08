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

import fcntl
import threading
from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter, computed_field

from lup.coordination.refs import ActorRef
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


class Delivery(StrEnum):
    """How a message reaches one member, which differs by what that member is.

    A property of the member rather than of the message: what carries a line to
    a peer is decided by what that peer is and who is holding it, and a sender
    that had to choose would be choosing on facts it does not have.
    """

    INBOX = "inbox"
    """Injected in front of the member's next tool call by its own hook.

    What a spawned agent gets, and the only mode that needs nothing running
    beside it: the hook fires because the member takes a turn, so a busy member
    cannot fail to receive and an idle one receives the moment it moves.
    """

    MAILBOX = "mailbox"
    """Left in the file for the member to read when it next looks.

    The mode with no wake at all, and the honest answer for a peer nothing can
    reach: a headless session between invocations, a member on a machine this
    one does not share. The file is the durable record either way — every other
    mode is a wake *on top of* this one, not an alternative to it.
    """


class ActorJoined(RosterRecord, frozen=True):
    """One peer that joined a cohort nobody spawned it into.

    The record a spawn cannot stand in for. A spawned member is live because
    the process that made it says so and finished because that process said
    that too; a peer that walked in has no such process, so what would
    otherwise be inferred has to be carried: who vouches for it still being
    there, and what reaches it.

    That is the whole difference between a cohort and a roster. A cohort is
    what one process started, and its membership is a fact that process owns; a
    roster is who is present, which nobody owns and everybody appends to.
    """

    type: Literal["joined"] = "joined"
    task: str = ""
    """What the peer says it is doing, in its own words. Empty is honest."""

    liveness: str = ""
    """Who answers for this peer still being there, by address.

    Empty means the peer answers for itself — it wrote this record and will
    write the one that ends it. A named holder is a peer that cannot: a
    launcher that minted the identity, or a watcher that will mark it gone when
    it stops answering. Somebody has to be able to say a member left, and for a
    session nobody spawned that is not automatic.
    """

    delivery: Delivery = Delivery.MAILBOX
    """How this peer is reached, defaulting to the mode that needs nothing.

    A member that declared no wake path still has a durable inbox, which is the
    conservative answer: mail waits rather than being dropped, and a sender is
    told what it will and will not do.
    """

    def applied(self, standing: "SpawnedActor | None") -> "SpawnedActor | None":
        """This peer, present. A rejoin under a round already held says nothing."""
        if standing is not None and self.actor.round < standing.actor.round:
            return standing
        return SpawnedActor(
            actor=self.actor,
            task=self.task,
            running=True,
            liveness=self.liveness,
            delivery=self.delivery,
        )


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


type RosterEntry = ActorSpawned | ActorJoined | ActorFinished
"""What the population record carries. Nothing here is about a turn.

Two ways in and one way out. A member is spawned by a process that owns its
lifetime, or joins as a peer that owns its own, and either leaves by the same
record — because how a member arrived is a fact about its arrival, and how it
went is the same question whichever way it came.
"""


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

    liveness: str = ""
    """Who answers for this member still being there, empty where it answers itself.

    A spawned member leaves this empty and means something different by it than
    a peer that does: the spawning process is the answer, and it is the one
    writing these records. A peer with a named holder is one whose absence
    somebody else has undertaken to notice.
    """

    delivery: Delivery = Delivery.INBOX
    """How a message reaches this member.

    The spawned default, because a spawned member is opened with the hook that
    makes it true — mail lands in front of its next tool call whether or not it
    thinks to look. A peer says what it can actually do instead.
    """

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
        self.lock_path = path.with_suffix(".lock")
        self.lock = threading.Lock()

    def announce(self, actor: ActorRef, arrival: RosterEntry) -> None:
        """Append one arrival, unless the record already has this member present.

        Idempotent per round, because two callers legitimately announce one
        arrival. For a spawn they are the process that detached the work and
        the round that work then opened; for a peer they are one session
        rejoining after a restart, which is the same member arriving again
        rather than a second one. Appending both would give that round two
        starts, and offer an operator two addresses reaching one session.

        Under a lock, because those callers are in *different processes*.
        Folding the record and then appending to it is a read-modify-write, so
        unguarded both see no standing entry and both append: the idempotence
        would hold in every case except the one it was written for. The thread
        lock sits outside the file lock because ``flock`` is granted per open
        file description rather than per thread, so two threads in one process
        would each hold it and interleave inside the region.
        """
        with self.lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    if any(
                        member.actor.conversation() == actor.conversation()
                        and member.actor.round == actor.round
                        and member.running
                        for member in self.standing()
                    ):
                        return
                    self.stream.append(arrival)
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def spawned(self, actor: ActorRef, task: str) -> None:
        """Record that a member this process started is live."""
        self.announce(actor, ActorSpawned(actor=actor, task=task, at=utc_now()))

    def joined(
        self,
        actor: ActorRef,
        task: str = "",
        liveness: str = "",
        delivery: Delivery = Delivery.MAILBOX,
    ) -> None:
        """Record that a peer nobody spawned is present, and how to reach it."""
        self.announce(
            actor,
            ActorJoined(
                actor=actor,
                task=task,
                liveness=liveness,
                delivery=delivery,
                at=utc_now(),
            ),
        )

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
            found = held.get(conversation)
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
