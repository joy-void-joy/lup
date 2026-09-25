"""A turn that starts the first time anything asks, as every provider's turn runs.

Asking a session for a turn builds one of these and starts nothing. The first
await, iteration, event view, interrupt or steer starts it — once, however
many ask at once — which is what keeps a typed turn's submission tool bound
before the provider accepts the prompt: binding is the start's first step.

A provider's public turn class is composed over one, and adds only what that
provider supports. This is the engine they share, so it carries every verb
either needs and the provider class decides which of them a caller sees.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

from pydantic import BaseModel

from lup.sessions.capabilities import EventStream, SessionEngine
from lup.sessions.errors import DeltaStreamingDisabled
from lup.sessions.events import (
    AnyTurnBlock,
    LiveTurnEvent,
    StartedTurn,
    TurnEvent,
    TurnInput,
    TurnRequest,
    TurnResult,
)
from lup.sessions.middleware import read_outcome

logger = logging.getLogger(__name__)


def turn_input(prompt: str | TurnInput) -> TurnInput:
    """A prompt as the portable input it is sent as."""
    # Narrowed on `str` rather than on `TurnInput`: the foreign alternative is
    # the one that cannot answer for itself.
    match prompt:
        case str():
            return TurnInput(text=prompt)
        case _:
            return prompt


class TurnFeed:
    """One turn's events, read once from its engine and replayed to each reader.

    A provider's stream can be consumed once, and a turn has more than one
    reader worth having: the caller iterating its blocks, a journal draining
    its events, a display following its deltas. Each reader here starts from
    the turn's first event, whenever it arrives, so a view asked for after the
    turn finished still says everything that happened.

    Reading starts with the turn rather than with the first reader, because the
    provider fills its stream either way and a turn nobody watched until it
    ended is still one somebody may ask about.
    """

    def __init__(self, stream: EventStream, deltas: bool) -> None:
        self.stream = stream
        self.deltas = deltas
        self.seen: list[LiveTurnEvent] = []
        self.readers: list[asyncio.Queue[LiveTurnEvent | None]] = []
        self.finished = False
        self.pump = asyncio.create_task(self.drain())

    async def drain(self) -> None:
        """Read the engine's stream once, handing each event to every reader."""
        try:
            view = self.stream.live() if self.deltas else self.stream.events()
            async for event in view:
                self.seen.append(event)
                for reader in self.readers:
                    reader.put_nowait(event)
        except Exception:
            # The turn's result carries whatever ended it; a reader is told
            # that by awaiting it, so this stream only has to stop.
            logger.debug("turn event stream ended early", exc_info=True)
        finally:
            self.finished = True
            for reader in self.readers:
                reader.put_nowait(None)

    async def replay(self) -> AsyncIterator[LiveTurnEvent]:
        """Every event of the turn, from its first, then each as it arrives."""
        reader: asyncio.Queue[LiveTurnEvent | None] = asyncio.Queue()
        for event in self.seen:
            reader.put_nowait(event)
        if self.finished:
            reader.put_nowait(None)
        else:
            self.readers.append(reader)
        try:
            while (event := await reader.get()) is not None:
                yield event
        finally:
            if reader in self.readers:
                self.readers.remove(reader)


class LazyTurn[T: BaseModel | None]:
    """One turn on a session engine, started the first time anything asks.

    Its result is settled on a task of its own from the moment it starts, so a
    turn advances whether or not anyone awaits it and hands its session back
    when it ends — a turn that was only interrupted, or only watched, does not
    hold the session against the next one. Awaiting it is waiting for that
    task, which a caller's cancellation still reaches.
    """

    def __init__(
        self, engine: SessionEngine, request: TurnRequest[T], *, deltas: bool
    ) -> None:
        self.engine = engine
        self.request = request
        self.deltas = deltas
        self.starting: asyncio.Task[StartedTurn[T]] | None = None
        self.feed: TurnFeed | None = None
        self.settling: asyncio.Task[TurnResult[T]] | None = None

    async def started(self) -> StartedTurn[T]:
        """The accepted turn, starting it if nothing has yet."""
        if self.starting is None:
            self.starting = asyncio.ensure_future(self.begin())
        return await self.starting

    async def begin(self) -> StartedTurn[T]:
        started = await self.engine.start(self.request)
        self.feed = TurnFeed(started.events, self.deltas)
        self.settling = asyncio.ensure_future(started.turn.result())
        self.settling.add_done_callback(read_outcome)
        return started

    async def settled(self) -> asyncio.Task[TurnResult[T]]:
        """The task settling this turn's result, once the turn has started."""
        await self.started()
        if self.settling is None:
            raise RuntimeError("a started turn has no result being settled")
        return self.settling

    async def result(self) -> TurnResult[T]:
        """This turn's result, the same one however many times it is asked."""
        return await (await self.settled())

    async def watched(self) -> AsyncIterator[LiveTurnEvent]:
        """Every event of this turn, then its failure if it failed."""
        await self.started()
        if self.feed is None:
            raise RuntimeError("a started turn has no events being read")
        async for event in self.feed.replay():
            yield event
        await self.result()

    async def durable(self) -> AsyncIterator[TurnEvent]:
        async for event in self.watched():
            if (kept := event.durable) is not None:
                yield kept

    def events(self) -> AsyncIterator[TurnEvent]:
        """Every durable event of this turn, from its first."""
        return self.durable()

    def live(self) -> AsyncIterator[LiveTurnEvent]:
        """Every event of this turn with the deltas between them.

        Refused at once on a session built without partial streaming, because
        a live view that simply never yielded a delta would read as a quiet
        turn rather than as a session that was never going to show one.
        """
        if not self.deltas:
            raise DeltaStreamingDisabled(
                "this session was built without partial message streaming"
            )
        return self.watched()

    async def blocks(self) -> AsyncIterator[AnyTurnBlock]:
        """The turn's completed blocks, in the order they finished."""
        async for event in self.durable():
            if (block := event.completed_block) is not None:
                yield block

    async def interrupt(self) -> None:
        """Stop this turn, returning once it has settled.

        Waiting for the settle is what makes the session free again when this
        returns, so the next turn asked of it can start. Its outcome is not
        raised here: an interrupted turn's result is its own, and awaiting the
        turn is where it is read.
        """
        started = await self.started()
        await started.interrupt.interrupt()
        await asyncio.wait([await self.settled()])

    async def steer(self, prompt: str | TurnInput) -> None:
        """Add input to this turn while it runs, without starting another."""
        started = await self.started()
        if started.steer is None:
            raise RuntimeError("this provider's engine supplied no steering")
        await started.steer.steer(turn_input(prompt))
