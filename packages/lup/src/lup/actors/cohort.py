# lup: ignore[constant-declaration]
# The constants here name the cohort's own on-disk layout, which a spawning
# process and an outside door must spell alike to meet at all — an identity
# of this format rather than a choice a caller can make.
"""A session's spawned agents: minted on demand, reachable while they work.

:class:`~lup.actors.sessions.ActorSessions` holds actors a run already knows
the names of — one worker per concern, decided before anything starts. This
is the other case: a session that spawns agents as it goes, whose addresses
did not exist a moment ago and whose count nobody declared.

What that case needs beyond a session store is small and entirely mechanical
— mint an address, remember what the spawn was asked for, say whether it is
still working, and recognize an operator's spelling of an address well enough
to put a message in front of the right one. Written per consumer it is four
subtly different implementations of "which agent did you mean".

Two ways to start one, because they are different work. A short check is
asked and awaited, and the answer is what the caller wanted. A long one is
*started*, and the caller keeps its turn — which is the only arrangement
under which the caller can say anything to it at all, since a caller blocked
inside a call is a caller that cannot make another.

The mail is a file under the cohort's root rather than memory, so a door
outside the spawning process reaches the same actor its own tools do.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter

from lup.actors.mail import ActorMail, new_message
from lup.actors.mailbox import AnswerDoor
from lup.actors.refs import ActorRef
from lup.actors.sessions import ActorEvent, ActorSessions, create_inbox_hooks
from lup.channels.models import utc_now
from lup.hooks import LupHooksConfig
from lup.journal import Journal, JournalRecord

logger = logging.getLogger(__name__)

COHORT_DIR = "actors"
JOURNAL_FILE = "journal.jsonl"


class CohortEntry(JournalRecord[ActorRef], frozen=True):
    """One thing a spawned actor did, or one thing said to it."""

    at: datetime
    event: ActorEvent


ENTRY_ADAPTER: TypeAdapter[CohortEntry] = TypeAdapter(CohortEntry)


class CohortJournal(Journal[ActorRef, CohortEntry]):
    """The ordered record of every actor one cohort holds.

    Its own file rather than the spawning session's transcript, because the
    two answer different questions: a transcript is what that session did,
    and this is what was said to whom and whether it landed. A redirect that
    reached nobody is only visible here.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(root / JOURNAL_FILE, ENTRY_ADAPTER)

    def append(self, actor: ActorRef, event: ActorEvent) -> CohortEntry:
        """Record one event against the actor that produced it."""
        return self.write(
            lambda seq, _previous: CohortEntry(
                seq=seq, at=utc_now(), actor=actor, event=event
            )
        )


class SpawnedActor(BaseModel):
    """What one spawned agent is, to whoever asks after it."""

    address: str
    kind: str
    task: str
    running: bool
    summary: str = ""
    error: str = ""


class ActorCohort:
    """Every agent one session has spawned, and how to reach any of them.

    Held by the process that spawns, because that is where the work runs.
    The mail underneath is a file, so an actor stays addressable from
    outside that process even though the task awaiting it is not.
    """

    def __init__(self, root: Path, run_id: str | None = None) -> None:
        self.root = root / COHORT_DIR
        self.run_id = run_id or root.name
        self.journal = CohortJournal(self.root)
        self.mail = ActorMail(self.root)
        self.sessions = ActorSessions(self.root, self.journal, self.mail)
        self.actors: dict[str, ActorRef] = {}
        self.spawned: dict[str, SpawnedActor] = {}
        self.running: dict[str, asyncio.Task[None]] = {}

    def address(self, kind: str) -> ActorRef:
        """A fresh address for one spawn, unique within this cohort.

        The kind is what the agent was spawned as, so an operator reading a
        label knows what they are talking to before they say anything to it.
        """
        return ActorRef(kind=kind, id=uuid4().hex[:8])

    def inbox_hooks(self, actor: ActorRef) -> LupHooksConfig:
        """The mid-turn delivery hook for one spawned actor's session.

        Taken before the session is built, because the hook has to be in the
        options the factory opens with — and taken from the cohort's own
        store, so the inbox delivering mid-turn is the one the next turn
        resumes from.
        """
        return create_inbox_hooks(self.sessions.inbox(actor))

    def record(self, actor: ActorRef, task: str) -> None:
        """Note that this address is live, before anything is said to it."""
        self.actors[actor.label()] = actor
        self.spawned[actor.label()] = SpawnedActor(
            address=actor.label(), kind=actor.kind, task=task, running=True
        )

    def finish(self, actor: ActorRef, summary: str = "", error: str = "") -> None:
        """Note that this address has stopped, and what it left behind."""
        held = self.spawned.get(actor.label())  # lup: ignore[dict-get] presence
        if held is None:
            return
        self.spawned[actor.label()] = held.model_copy(
            update={"running": False, "summary": summary, "error": error}
        )

    def live(self) -> list[SpawnedActor]:
        """Every spawn this cohort made, the ones still working first."""
        return sorted(self.spawned.values(), key=lambda spawn: not spawn.running)

    def reaching(self, address: str) -> ActorRef | None:
        """The actor an operator's spelling of an address reaches, if any.

        Matched against what each live actor answers to rather than parsed
        out of the text, so a label this cohort printed is a label that
        works — and a bare id reaches the same agent as the full one. Every
        consumer that instead took the address apart disagreed with the
        printer about what an address was, and a message sent to the
        spelling shown reached nobody.
        """
        if not address:
            return None
        return next(
            (actor for actor in self.actors.values() if address in actor.addresses()),
            None,
        )

    def say(self, actor: ActorRef, text: str, redirect: bool = False) -> None:
        """Put something in front of one actor's next tool call.

        A redirect refuses that call and hands back the text as its reason,
        so the actor cannot take another step down what it was doing without
        reading why it was stopped. An ordinary message rides alongside and
        it keeps going.
        """
        self.mail.send(
            new_message(
                run_id=self.run_id,
                to_actor=actor.label(),
                text=text,
                door=AnswerDoor.AGENT,
                redirect=redirect,
            )
        )

    def outstanding(self, actor: ActorRef) -> int:
        """How much this actor has been sent and not yet been handed.

        What makes "sent" answerable. The mail accepting a message is not the
        same as anyone reading it, and a sender told only the first has no
        way to find out about the second.
        """
        return len(self.mail.waiting(actor).messages)

    async def close(self) -> None:
        """Stop whatever is still running, recording what none of it read."""
        for task in list(self.running.values()):
            task.cancel()
        await self.sessions.close()
