"""Who a cohort holds, written as records and read back as a fold.

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

**The records are here and the fold is not.** What each record means to a
member is one question, and three processes ask it: this library, the hook a
runtime spawns at each prompt, and the compiled permission dispatcher. Only
this one can import pydantic, so the fold lives in
:mod:`lup.coordination.bare.store` where all three reach it, and what stays
here is the typed writer and the model a typed caller reads back. A record
added here is a case added there, once, rather than three times.
"""

import fcntl
import threading
from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter, computed_field

from lup.channels.models import utc_now
from lup.channels.stream import Stream
from lup.coordination.bare import store
from lup.coordination.refs import ActorRef
from lup.coordination.wake import WakePath, declared_wake


class RosterRecord(BaseModel, frozen=True):
    """One thing that happened to a member, written down as it happened."""

    actor: ActorRef
    at: datetime


class ActorSpawned(RosterRecord, frozen=True):
    """One agent started, and what it was asked for.

    The task is recorded here rather than left to the caller's memory because
    it is what an operator reads to decide which spawn they meant. An address
    alone distinguishes agents without describing any of them.
    """

    type: Literal["spawned"] = "spawned"
    task: str


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


def carried(spelled: str, fallback: Delivery) -> Delivery:
    """The delivery a folded row spells, or the fallback where it spells none.

    A spawned member's record carries no delivery at all — the spawner's hook
    is what reaches it, and that is the default this falls back to. A spelling
    no mode answers to falls back the same way rather than raising, because
    this is read on every listing and a store written by a newer library must
    not stop an older one reading who is here.
    """
    return next(
        (mode for mode in Delivery if mode.value == spelled),
        fallback,
    )


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

    wake: WakePath = WakePath()
    """What would make this peer look, where anything can.

    Self-reported, and on one runtime it can only be: the handle a
    Claude session's peers address it by appears in none of the
    variables that session is given, so nothing but the session itself
    can say it."""

    delivery: Delivery = Delivery.MAILBOX
    """How this peer is reached, defaulting to the mode that needs nothing.

    A member that declared no wake path still has a durable inbox, which is the
    conservative answer: mail waits rather than being dropped, and a sender is
    told what it will and will not do.
    """

    worktree: str = ""
    """Where this peer is working, absolute, empty where it is nowhere in particular.

    Carried because two questions need it and neither can derive it. A person
    reading a roster of sessions is choosing between checkouts as much as
    between names; and what a member may be attributed for changing is bounded
    by where it works, so a lease over a path is meaningless without knowing
    whose tree that path is in.
    """


class ActorDescribed(RosterRecord, frozen=True):
    """One member saying what it is doing now, which its task cannot keep up with.

    A task is what a member arrived for and it never changes. A description is
    what that member is doing, and on a roster that outlives one assignment
    those stop being the same fact: a session that joined this morning is on
    its third thing by noon, and a listing built from the task alone still
    shows the first. A person scanning a roster to decide who to ask is
    reading for the second, so the roster has to carry it.

    A record rather than a mutable field, because the roster is a fold and a
    field would be a second way to change a member — one that a reader in
    another process could not see arrive, and that a replay could not rebuild.
    """

    type: Literal["described"] = "described"
    description: str = ""


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


type RosterEntry = ActorSpawned | ActorJoined | ActorDescribed | ActorFinished
"""What the population record carries. Nothing here is about a turn.

Two ways in and one way out. A member is spawned by a process that owns its
lifetime, or joins as a peer that owns its own, and either leaves by the same
record — because how a member arrived is a fact about its arrival, and how it
went is the same question whichever way it came.

What happens in between is one record too. A member redescribing itself is not
arriving and not leaving, and the fold takes it beside the other three.
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

    heard: datetime | None = None
    """When the record last spoke of this member, or nothing where it never did.

    The newest record's own time, whichever kind it was — an arrival, a
    description, a finish. A reader deciding whether a silent member is still
    there starts from here and takes a later pulse where one was written; the
    record alone says when a member last *said* something, which is not the
    same question.
    """

    arrived: datetime | None = None
    """When this member's present standing began: its newest arrival's own time.

    Kept apart from ``heard`` because the two move differently — every record
    advances ``heard``, and only an arrival sets this — and a reader has a
    question only this answers: which departures happened while this member
    was here to have written to the departed.
    """

    worktree: str = ""
    """Where this member is working, absolute, empty where it is nowhere.

    A fact about the member rather than about its arrival, which is why it
    survives here: a listing built after the fact still says which checkout
    each session is in, and a lease over a path can say whose tree it is.
    """

    description: str = ""
    """What this member is doing now, empty until it has said.

    Beside the task rather than replacing it, because a reader wants both: the
    task is what this member is answerable for, and the description is where
    it has got to. Empty is honest for a member that has not spoken, and reads
    as such — the task is still there to fall back on.
    """

    liveness: str = ""
    """Who answers for this member still being there, empty where it answers itself.

    A spawned member leaves this empty and means something different by it than
    a peer that does: the spawning process is the answer, and it is the one
    writing these records. A peer with a named holder is one whose absence
    somebody else has undertaken to notice.
    """

    wake: WakePath = WakePath()
    """What would make this member look, where anything can.

    Beside the delivery mode rather than folded into it, because they
    answer different questions: delivery is how a message is carried and
    is always the file, while this is what nudges the member into
    reading it. A wake sits on top of the record and never replaces it,
    so an empty one costs a peer latency and never a message.
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


def folded_member(member: store.Member) -> SpawnedActor:
    """One row of the shared fold, as a typed caller reads it.

    Total rather than validating: every field is coerced to something the model
    accepts, because this is the read path a listing, a hook and a console all
    go through, and a record written by a newer library must leave an older one
    still able to say who is here. What a malformed field costs is that field.
    """
    wake = member["wake"]
    return SpawnedActor(
        actor=ActorRef(kind=member["kind"], id=member["id"], round=member["round"]),
        task=member["task"],
        running=member["running"],
        summary=member["summary"],
        error=member["error"],
        heard=store.spoken_at(member["heard"]),
        arrived=store.spoken_at(member["arrived"]),
        worktree=member["worktree"],
        description=member["description"],
        liveness=member["liveness"],
        wake=declared_wake(
            store.text(wake.get("runtime")),
            store.text(wake.get("handle")),
            store.text(wake.get("session")),
        ),
        delivery=carried(member["delivery"], Delivery.INBOX),
    )


class Roster:
    """Every agent one cohort has held, and whether each is still working."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream: Stream[RosterEntry] = Stream(path, ENTRY_ADAPTER)
        self.lock_path = path.with_suffix(".lock")
        self.lock = threading.Lock()

    def present(self, actor: ActorRef) -> bool:
        """Whether this exact round is already standing as a working member.

        The idempotence test, named rather than inlined, because it is asked
        twice: once outside the lock to keep the common arrival cheap, and once
        inside it to make the answer binding.
        """
        conversation = actor.conversation()
        return any(
            member.actor.conversation() == conversation
            and member.actor.round == actor.round
            and member.running
            for member in self.standing()
        )

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

        Read once before taking anything, because the standing case is now the
        common one: every process opening a view onto a cohort announces the
        member that is always present, and a lock taken to discover that it is
        already there would put an exclusive file lock on the constructor of
        the reading half. A false negative here costs the lock the guard was
        already written for; a false positive cannot happen, because nothing
        removes an arrival.
        """
        if self.present(actor):
            return
        with self.lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    if self.present(actor):
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
        worktree: str = "",
        wake: WakePath = WakePath(),
    ) -> None:
        """Record that a peer nobody spawned is present, and how to reach it."""
        self.announce(
            actor,
            ActorJoined(
                actor=actor,
                task=task,
                liveness=liveness,
                delivery=delivery,
                worktree=worktree,
                wake=wake,
                at=utc_now(),
            ),
        )

    def describes(self, actor: ActorRef, description: str) -> None:
        """Record what this member is doing now.

        Appended rather than announced, because this is not an arrival and the
        idempotence guard would refuse the second one — a member that describes
        itself twice is a member that moved on, which is the whole use.
        """
        self.stream.append(
            ActorDescribed(actor=actor, description=description, at=utc_now())
        )

    def finished(self, actor: ActorRef, summary: str = "", error: str = "") -> None:
        """Record that this address has stopped, and how."""
        self.stream.append(
            ActorFinished(actor=actor, summary=summary, error=error, at=utc_now())
        )

    def standing(self) -> Iterator[SpawnedActor]:
        """The shared fold of this record, one member per conversation.

        A round advance updates the member in place rather than adding one,
        because a worker on its second round is the agent that took its first
        — the same conversation, one attempt further on. What a reader wants
        counted is agents, and what they want printed is the address that
        currently reaches each.
        """
        for member in store.members(self.path).values():
            yield folded_member(member)

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
