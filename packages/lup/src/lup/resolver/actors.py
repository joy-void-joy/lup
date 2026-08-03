"""One durable session per actor, opened once and kept while the run moves.

Every resolver turn used to go through :func:`lup.runtime.query.query`, which
opens a session, takes one turn and closes it. Nine separate symptoms sat
downstream of that one fact: a park discarded the whole turn, a reviewer
re-read its concern cold each round, a merger never saw the parent it joined
last, and the same question was answered four times because each turn
re-derived it under an id no recorded answer matched.

An actor here is addressed rather than constructed per turn. It holds its
session across every turn it takes, drains what it does into the journal as
it happens, and is reattached after a park from its persisted identity. The
multi-turn shape is not new — :class:`lup.runtime.background.BackgroundAgent`
already holds one session open across many turns — the resolver simply
reached for the one-shot convenience instead.

``query()`` stays in the library. It is the legitimate one-shot convenience
and ``examples/one_shot.py`` uses it; what changed is that no resolver turn
calls it.
"""

import asyncio
import hashlib
import json
import logging
from contextlib import AsyncExitStack
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from lup.channels.models import publish_atomic
from lup.resolver.journal import ActorRef, Journal, record_turn
from lup.resolver.models import FROZEN
from lup.runtime.contracts import Interrupt, SessionFactory, Steer
from lup.runtime.models import (
    SessionHandle,
    SessionId,
    TurnInput,
    TurnRequest,
    TurnResult,
)

logger = logging.getLogger(__name__)

SESSION_DIR = "sessions"


class ActorSchemaChangedError(RuntimeError):
    """A resumed actor expects a different submission schema than it left with."""


class ActorRecord(BaseModel):
    """What one actor needs to be reattached after a park.

    The digest is recorded here rather than pushed into the runtime because
    only this side knows both halves of the comparison. A provider that
    restores a resumed thread's tools from its own metadata never says what
    it restored, so the answerable question is whether *we* expect the same
    schema now that we expected before the park.
    """

    model_config = FROZEN

    actor: ActorRef
    session: SessionId | None = None
    schema_digest: str | None = None


RECORD_ADAPTER: TypeAdapter[ActorRecord] = TypeAdapter(ActorRecord)


def schema_digest(output_type: type[BaseModel] | type[None] | None) -> str | None:
    """Digest the submission schema an actor's turns are bound to."""
    if output_type is None or not issubclass(output_type, BaseModel):
        return None
    schema = json.dumps(TypeAdapter(output_type).json_schema(), sort_keys=True)
    return hashlib.sha256(schema.encode("utf-8")).hexdigest()


class ActorSession:
    """One actor's conversation, held open across every turn it takes."""

    def __init__(
        self,
        actor: ActorRef,
        factory: SessionFactory,
        journal: Journal,
        record: ActorRecord | None = None,
    ) -> None:
        self.actor = actor
        self.factory = factory
        self.journal = journal
        self.record = record or ActorRecord(actor=actor)
        self.stack = AsyncExitStack()
        self.handle: SessionHandle | None = None
        self.interrupt: Interrupt | None = None
        self.steering: Steer | None = None
        self.pending: list[str] = []  # lup: ignore[empty-collection] — delivery queue

    async def opened(self) -> SessionHandle:
        """Open this actor's session once, resuming where one was persisted."""
        if self.handle is None:
            self.handle = await self.stack.enter_async_context(
                self.factory.open(resume=self.record.session)
            )
        return self.handle

    async def turn[T: BaseModel | None](self, request: TurnRequest[T]) -> TurnResult[T]:
        """Take one turn on this actor's session, recording it as it happens.

        The events are drained concurrently with awaiting the result rather
        than afterwards. An adapter fills its queue from its own task and the
        queue is unbounded, so a reader cannot deadlock a turn — and a
        watcher that only saw a turn once it finished would be a log rather
        than a trace.
        """
        self.check_schema(request)
        handle = await self.opened()
        started = await handle.session.start(self.with_pending(request))
        self.interrupt = started.interrupt
        self.steering = started.steer
        drain = (
            asyncio.create_task(
                record_turn(self.journal, self.actor, started.events.events())
            )
            if started.events is not None
            else None
        )
        try:
            result = await started.turn.result()
        finally:
            self.interrupt = None
            self.steering = None
            if drain is not None:
                # The adapter closes its queue in a `finally`, so the drain
                # terminates on the failure path too and awaiting it here
                # cannot outlive the turn that fed it.
                await drain
        self.record = self.record.model_copy(
            update={"session": result.identifiers.session}
        )
        return result

    def with_pending[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnRequest[T]:
        """Put whatever was volunteered between turns at the head of this one.

        Ahead of the prompt rather than after it, because a message that
        retargets an actor has to be read before the instruction it revises.
        """
        if not self.pending:
            return request
        delivered = "\n\n".join([*self.pending, request.input.text])
        self.pending.clear()
        return request.model_copy(
            update={"input": request.input.model_copy(update={"text": delivered})}
        )

    def check_schema[T: BaseModel | None](self, request: TurnRequest[T]) -> None:
        """Refuse a resumed actor whose submission schema no longer matches."""
        digest = schema_digest(request.output_type)
        if self.record.schema_digest is None:
            self.record = self.record.model_copy(update={"schema_digest": digest})
            return
        if digest != self.record.schema_digest:
            raise ActorSchemaChangedError(
                f"{self.actor.label()} resumed expecting a different submission "
                "schema than the one it was bound to"
            )

    async def steer(self, text: str) -> bool:
        """Volunteer something to an actor that should keep going.

        Best-effort by contract: it hands the message to the running turn and
        the runtime delivers it at the next opportunity. Deliberately not
        emulated with an interrupt — spending one to deliver a message ends a
        turn that had no reason to end, and reads as a different act in the
        trace. Between turns there is nothing to append to, so the message
        waits and arrives at the head of the next one.
        """
        if self.steering is None:
            self.pending.append(text)
            return True
        await self.steering.steer(TurnInput(text=text))
        return True

    async def redirect(self, text: str) -> bool:
        """Stop what this actor is doing and put it on something else.

        Interrupt-then-new-turn, which is uniform on every runtime. This is
        the verb for retargeting rather than for informing: it gives an
        observable boundary, and every resolver turn ends in a typed
        submission, so steering a decision into a turn that has already
        formed its report is racy exactly when the input was meant to change
        the outcome.
        """
        self.pending.append(text)
        if self.interrupt is None:
            return False
        await self.interrupt.interrupt()
        return True

    async def close(self) -> None:
        await self.stack.aclose()
        self.handle = None


class ActorSessions:
    """Every actor's session for one run, and their persisted identities.

    Sessions are addressed by actor rather than created per turn, so asking
    for the same actor twice continues one conversation. Closing is the run's
    job and happens once, at the end of the run or at a park.
    """

    def __init__(self, root: Path, journal: Journal) -> None:
        self.root = root / SESSION_DIR
        self.journal = journal
        self.sessions: dict[str, ActorSession] = {}

    def key(self, actor: ActorRef) -> str:
        """Which conversation this actor belongs to.

        Deliberately not the round. A worker on round two is the agent that
        wrote round one's code and was told what was wrong with it, and a
        reviewer that re-read its concern cold each round is one of the
        symptoms this exists to remove. The round attributes what happened
        in the journal; it does not fork the conversation.
        """
        return f"{actor.kind}-{actor.id}"

    def path(self, actor: ActorRef) -> Path:
        return self.root / f"{self.key(actor)}.json"

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

    def session(self, actor: ActorRef, factory: SessionFactory) -> ActorSession:
        """This actor's session, resumed from its record the first time."""
        held = self.sessions.get(self.key(actor))  # lup: ignore[dict-get] — presence
        if held is not None:
            held.actor = actor
            return held
        opened = ActorSession(actor, factory, self.journal, self.persisted(actor))
        self.sessions[self.key(actor)] = opened
        return opened

    def save(self, actor: ActorRef) -> None:
        """Persist one actor's identity so a resumed run reattaches to it."""
        held = self.sessions.get(self.key(actor))  # lup: ignore[dict-get] — presence
        if held is not None:
            publish_atomic(self.path(actor), held.record)

    async def close(self) -> None:
        """Close every open session, persisting what each one needs to return."""
        for held in list(self.sessions.values()):
            self.save(held.actor)
            await held.close()
        self.sessions.clear()
