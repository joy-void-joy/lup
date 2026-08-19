# lup: ignore[constant-declaration]
# The constants here name the cohort's own on-disk layout, which a spawning
# process and an outside door must spell alike to meet at all — an identity
# of this format rather than a choice a caller can make.
"""A population of agents that stay in contact with the outside while they work.

One session per agent, held open across every turn it takes; mail that lands in
front of an agent's next tool call whether or not it thinks to look; and an
address for whoever spawned them, so the contact goes both ways. That is the
whole shape, and it is the same shape whether the agents were decided before
anything started or minted a moment ago.

Two ways to run one, because they are different work — and the difference is
what makes the rest of this reachable at all. A short check is *asked* and
awaited, and the answer is what the caller wanted. A long one is *started*, and
the caller keeps its turn. Only the second leaves anyone able to say anything:
a caller blocked inside a call is a caller that cannot make another, so a
population of awaited spawns has steering tools that can never fire.

What the cohort does not leave to its callers is the wiring. An agent is
addressable only if the inbox hook is in the options its session was opened
with, so a caller assembling that itself has a way to produce an agent nobody
can reach by forgetting one step. Callers pass a recipe and the cohort hands it
the hooks.

Nothing here knows what the agents are for. A resolver names one worker per
concern and derives every id from durable state; a research session mints ids
for spawns nobody declared. Both are this type, with an id supplied or not.

The root is used as given rather than nested under a directory of this layer's
choosing. Where a cohort's files sit beside a consumer's own — a resolver's run
directory holds both — the consumer is the one that knows whether they belong
together, and a layer that nested unconditionally would put the sessions
somewhere no resumed run would look for them.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, TypeAdapter

from lup.actors.mail import EVERYONE, ActorDelivery, ActorMail, new_message
from lup.actors.refs import ActorRef
from lup.actors.roster import ROSTER_FILE, Roster, SpawnedActor
from lup.actors.sessions import (
    RECORD_ADAPTER,
    ActorEvent,
    ActorInbox,
    ActorJournal,
    ActorRecord,
    ActorSession,
    create_inbox_hooks,
)
from lup.channels.models import Door, publish_atomic, utc_now
from lup.hooks import LupHooksConfig
from lup.journal import Journal, JournalRecord
from lup.runtime.factory import SessionFactory
from lup.runtime.models import TurnRequest, TurnResult

logger = logging.getLogger(__name__)

SESSION_DIR = "sessions"
JOURNAL_FILE = "journal.jsonl"
SPAWNER_KIND = "spawner"


type ActorRecipe = Callable[[ActorRef, LupHooksConfig], SessionFactory]
"""How one actor's session is configured, given the hooks that reach it.

The hooks are a parameter rather than something a recipe fetches, because
delivery depends on them being in the options the session opens with. A recipe
that must remember to go and get them is a recipe that can be written once
without them, producing an agent that looks spawned and answers to nothing.

The ref rides along because a recipe usually needs it: a worker's tools are
bound to the concern its id names, and its permissions to the lease that id
holds.
"""


class CohortEntry(JournalRecord[ActorRef], frozen=True):
    """One thing an actor did, or one thing said to it."""

    at: datetime
    event: ActorEvent


class CohortJournal(Journal[ActorRef, CohortEntry]):
    """The default record, for a cohort whose consumer keeps none of its own.

    Its own file rather than the spawning session's transcript, because the two
    answer different questions: a transcript is what that session did, and this
    is what was said to whom and whether it landed. A redirect that reached
    nobody is only visible here.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(root / JOURNAL_FILE, TypeAdapter(CohortEntry))

    def append(self, actor: ActorRef, event: ActorEvent) -> CohortEntry:
        """Record one event against the actor that produced it."""
        return self.write(
            lambda seq, _previous: CohortEntry(
                seq=seq, at=utc_now(), actor=actor, event=event
            )
        )


def submitted_summary(output: BaseModel | None) -> str:
    """What a finished agent found, read off the result it has already given.

    A summary that costs another model call is one nobody takes on a path that
    has already produced its answer, so this reads a ``summary`` field where
    the submission carries one and reports nothing where it does not. A caller
    whose result names it differently passes its own.
    """
    if output is None:
        return ""
    found = output.model_dump().get("summary")  # lup: ignore[dict-get] optional field
    return found if isinstance(found, str) else ""


class ActorCohort:
    """Every agent one session holds, and how to reach any of them.

    Held by the process that runs the work, because that is where the sessions
    live. Everything an outside door needs — who exists, what each was asked,
    what is queued for whom — is on disk under the cohort's root, so steering
    from another process is the same operation as steering from this one.
    """

    def __init__(
        self,
        root: Path,
        journal: ActorJournal | None = None,
        mail: ActorMail | None = None,
        run_id: str | None = None,
        spawner: ActorRef | None = None,
    ) -> None:
        self.root = root
        self.run_id = run_id or root.name
        self.journal = journal or CohortJournal(self.root)
        # Taken rather than always built, because a consumer that already has
        # one must not end up with two. A question mailbox holds mail of its
        # own over the same directory, and a cohort that opened a second
        # stream beside it would give the two halves of one conversation
        # different files to disagree in.
        self.mail = mail or ActorMail(self.root)
        self.roster = Roster(self.root / ROSTER_FILE)
        self.spawner = spawner or ActorRef(kind=SPAWNER_KIND, id=self.run_id)
        # Keyed by conversation rather than by label, because a round is an
        # attempt and not a new agent: a worker's second round is the session
        # that took its first, and keying by the label held two of them.
        self.sessions: dict[str, ActorSession] = {}
        self.inboxes: dict[str, ActorInbox] = {}
        self.running: dict[str, asyncio.Task[None]] = {}

    def actor(self, kind: str, id: str | None = None, round: int = 1) -> ActorRef:
        """An address in this cohort, derived from what a caller has or minted.

        A caller with durable state to name an agent by passes it, and the
        address is then stable across a restart — which is what lets a resumed
        run reattach to the conversation it left rather than open a fresh one.
        A caller with nothing to derive from omits it and gets a mint.

        That is the only difference between the two cases, and it is why they
        are one method: everything downstream — the held session, the mail, the
        record — is identical either way.
        """
        return ActorRef(kind=kind, id=id or uuid4().hex[:8], round=round)

    def path(self, actor: ActorRef) -> Path:
        return self.root / SESSION_DIR / f"{actor.conversation()}.json"

    def inbox(self, actor: ActorRef) -> ActorInbox:
        """This conversation's mail, kept current with the round it is on.

        One object per conversation rather than one per caller, because the
        hook that interrupts a live turn and the collection that heads the next
        one are two views of one stream. Handing each its own left them with
        two positions over it, and a message could sit behind both.
        """
        held = self.inboxes.get(actor.conversation())  # lup: ignore[dict-get] presence
        if held is None:
            held = ActorInbox(self.mail, self.journal, actor)
            self.inboxes[actor.conversation()] = held
        held.actor = actor
        return held

    def persisted(self, actor: ActorRef) -> ActorRecord | None:
        """The identity this actor left behind, if it has run before."""
        path = self.path(actor)
        if not path.exists():
            return None
        try:
            return RECORD_ADAPTER.validate_json(path.read_text("utf-8"))
        except ValueError:
            logger.exception("Discarding unreadable actor record at %s", path)
            return None

    def session(self, actor: ActorRef, recipe: ActorRecipe) -> ActorSession:
        """This actor's session, resumed from its record the first time.

        The recipe is handed this actor's inbox hooks, so what it opens is
        reachable mid-turn without the caller having arranged anything.
        """
        held = self.sessions.get(actor.conversation())  # lup: ignore[dict-get] presence
        if held is not None:
            held.actor = actor
            return held
        inbox = self.inbox(actor)
        opened = ActorSession(
            actor,
            recipe(actor, create_inbox_hooks(inbox)),
            self.journal,
            self.persisted(actor),
            inbox,
        )
        self.sessions[actor.conversation()] = opened
        return opened

    def spawn(self, actor: ActorRef, task: str) -> None:
        """Record that this address is live, before anything is said to it."""
        self.roster.spawned(actor, task)

    async def finish(self, actor: ActorRef, summary: str = "", error: str = "") -> None:
        """Record that this agent's work concluded, and let go of its session.

        Closing here rather than leaving it to the caller, because finishing is
        exactly the moment the session stops being worth holding — and the
        record is saved first, so an agent asked for again reattaches to the
        conversation instead of starting a fresh one.
        """
        self.roster.finished(actor, summary=summary, error=error)
        await self.retire(actor)

    async def retire(self, actor: ActorRef) -> None:
        """Save and close one actor's session without saying its work ended."""
        held = self.sessions.pop(actor.conversation(), None)
        if held is None:
            return
        self.save(actor, held)
        self.inbox(actor).record_outstanding()
        await held.close()

    def save(self, actor: ActorRef, held: ActorSession | None = None) -> None:
        """Persist one actor's identity so a resumed run reattaches to it."""
        found = held or self.sessions.get(  # lup: ignore[dict-get] presence
            actor.conversation()
        )
        if found is not None:
            publish_atomic(self.path(actor), found.record)

    def live(self) -> list[SpawnedActor]:
        """Every agent this cohort holds, the ones still working first."""
        return self.roster.live()

    def members(self) -> list[ActorRef]:
        """Every agent as the ref that currently reaches it."""
        return self.roster.members()

    def reaching(self, address: str) -> ActorRef | None:
        """The agent an operator's spelling of an address reaches, if any.

        Folded from the record rather than from what this process spawned, so
        a console in another terminal resolves the same address the cohort's
        own tools do — and so a run resumed after a park can still be steered.

        A broadcast token resolves to nobody on purpose: it is not one agent,
        and a door that answered it with the first member would deliver to one
        recipient what was meant for all of them.
        """
        if address in self.spawner.addresses():
            return self.spawner
        return self.roster.reaching(address)

    def say(
        self,
        actor: ActorRef,
        text: str,
        redirect: bool = False,
        door: Door = Door.AGENT,
        in_reply_to: str = "",
    ) -> None:
        """Put something in front of one agent's next tool call.

        A redirect refuses that call and hands back the text as its reason, so
        the agent cannot take another step down what it was doing without
        reading why it was stopped. An ordinary message rides alongside and it
        keeps going.
        """
        self.post(
            actor.label(), text, redirect=redirect, door=door, in_reply_to=in_reply_to
        )

    def say_all(
        self, text: str, redirect: bool = False, door: Door = Door.AGENT
    ) -> None:
        """Say the same thing to every agent, including ones not yet spawned.

        One record addressed to everyone rather than one per member. A member
        spawned after this still receives it, because its cursor starts behind
        the record and the record still names it — which a fan-out over the
        roster cannot do, since it can only name who existed when it ran.
        """
        self.post(EVERYONE, text, redirect=redirect, door=door)

    def tell_spawner(
        self, text: str, door: Door = Door.AGENT, in_reply_to: str = ""
    ) -> None:
        """Say something to whoever spawned this cohort.

        The spawner is an ordinary address with an inbox and no session, which
        is what makes contact symmetric: an agent volunteering something uses
        the same mechanism that steers it, and what it says lands somewhere a
        person can read rather than nowhere.
        """
        self.say(self.spawner, text, door=door, in_reply_to=in_reply_to)

    def post(
        self,
        to_actor: str,
        text: str,
        redirect: bool = False,
        door: Door = Door.AGENT,
        in_reply_to: str = "",
    ) -> None:
        """Write one message to whatever address a caller already holds.

        The one place a message is built, so a door with a raw address string
        and a caller with a ref reach the stream the same way.
        """
        self.mail.send(
            new_message(
                run_id=self.run_id,
                to_actor=to_actor,
                text=text,
                door=door,
                in_reply_to=in_reply_to,
                redirect=redirect,
            )
        )

    def heard(self) -> ActorDelivery:
        """What agents have told the spawner, consuming none of it."""
        return self.mail.waiting(self.spawner)

    def hear(self) -> ActorDelivery:
        """Take what agents have told the spawner, for a door displaying it."""
        delivery = self.heard()
        self.mail.delivered(self.spawner, delivery.through)
        return delivery

    def outstanding(self, actor: ActorRef) -> int:
        """How much this agent has been sent and not yet been handed.

        What makes "sent" answerable. The mail accepting a message is not the
        same as anyone reading it, and a sender told only the first has no way
        to find out about the second.
        """
        return len(self.mail.waiting(actor).messages)

    async def ask[T: BaseModel | None](
        self,
        actor: ActorRef,
        request: TurnRequest[T],
        recipe: ActorRecipe,
        task: str = "",
    ) -> TurnResult[T]:
        """Run one agent to an answer, recording what it was asked and gave.

        The caller waits, so this is for work whose result is what the caller
        wanted. It is still addressable while it runs — by a door in another
        process, or by a sibling — because the mail is on disk and the hook is
        in the session either way. What it is not is steerable by *this*
        caller, who is inside the call.
        """
        self.spawn(actor, task or request.input.text)
        try:
            result = await self.session(actor, recipe).turn(request)
        except Exception as error:
            await self.finish(actor, error=str(error))
            raise
        await self.finish(actor, summary=submitted_summary(result.output))
        return result

    def start[T: BaseModel | None](
        self,
        actor: ActorRef,
        request: TurnRequest[T],
        recipe: ActorRecipe,
        task: str = "",
        then: Callable[[TurnResult[T]], Awaitable[None]] | None = None,
    ) -> ActorRef:
        """Set one agent working and keep the caller's turn.

        This is what makes a cohort worth having. The caller returns
        immediately, so it can spawn more, answer a question, or say something
        to what it just started — none of which is reachable from inside an
        awaited call.

        The failure is recorded against the agent rather than swallowed: the
        roster carries it, the log carries the traceback, and the task keeps
        the exception for whoever gathers it.
        """
        self.spawn(actor, task or request.input.text)

        async def work() -> None:
            try:
                result = await self.session(actor, recipe).turn(request)
            except Exception as error:
                logger.exception("%s failed", actor.label())
                await self.finish(actor, error=str(error))
                raise
            await self.finish(actor, summary=submitted_summary(result.output))
            if then is not None:
                await then(result)

        self.running[actor.conversation()] = asyncio.create_task(work())
        return actor

    async def wait_all(self) -> None:
        """Wait for everything started, whatever each of them does.

        Failures are gathered rather than raised, because one agent going down
        must not cost the others their results — and every one of them has
        already been recorded against its own address.
        """
        await asyncio.gather(*self.running.values(), return_exceptions=True)
        self.running.clear()

    async def wait_any(self) -> None:
        """Wait until one started agent finishes, leaving the rest working."""
        if not self.running:
            return
        await asyncio.wait(self.running.values(), return_when=asyncio.FIRST_COMPLETED)
        for conversation in [
            conversation for conversation, task in self.running.items() if task.done()
        ]:
            del self.running[conversation]

    async def close(self) -> None:
        """Stop whatever is still running, recording what none of it read.

        A sender is told a message was sent on the strength of the mailbox
        accepting it, which is not the same as anyone reading it. What is still
        queued as the sessions close is therefore recorded against the agent it
        was for — outstanding across a park, and never read at all on a run
        that ended.
        """
        for task in self.running.values():
            task.cancel()
        await asyncio.gather(*self.running.values(), return_exceptions=True)
        self.running.clear()
        for held in list(self.sessions.values()):
            await self.retire(held.actor)
