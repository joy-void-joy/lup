"""A turn starts the first time anything asks, and answers every view from one reading.

Driven over the real composed session, so the one-active-turn rule and the
binding-before-acceptance order are the engine's own rather than a double's:
the adapter half is a starter feeding a queue, which is what both providers'
adapters are.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from pydantic import BaseModel

from lup.sessions.capabilities import (
    EventStream,
    Interrupt,
    SessionEngine,
    SessionWrapper,
    Steer,
    TurnToolBinder,
)
from lup.sessions.composition import AcceptedTurn, CompletedTurn, ComposedSession
from lup.sessions.errors import (
    DeltaStreamingDisabled,
    ProviderTurnError,
    TurnFailure,
)
from lup.sessions.events import (
    BlockCompletedEvent,
    BlockDeltaEvent,
    LiveTurnEvent,
    MessageCompletedEvent,
    SessionId,
    TurnCompletedEvent,
    TurnEvent,
    TurnId,
    TurnIdentifiers,
    TurnInput,
    TurnMessage,
    TurnRequest,
    TurnStartedEvent,
    TurnTextBlock,
    TurnToolBinding,
)
from lup.sessions.layers import CleanupWrapper, SessionLayers
from lup.sessions.middleware import (
    CorrectionConfig,
    DecoratingSession,
    SerializedSession,
    SwitchingEventStream,
    TimeoutConfig,
)
from lup.sessions.turns import LazyTurn


IDENTIFIERS = TurnIdentifiers(session=SessionId(value="s"), turn=TurnId(value="t"))
TEXT = TurnTextBlock(text="the answer")


def said(delta: str = "") -> list[LiveTurnEvent]:
    """One turn's whole event sequence: a delta, a block, its message, the end."""
    return [
        TurnStartedEvent(identifiers=IDENTIFIERS),
        BlockDeltaEvent(identifiers=IDENTIFIERS, delta=delta or "the ans"),
        BlockCompletedEvent(identifiers=IDENTIFIERS, block=TEXT),
        MessageCompletedEvent(
            identifiers=IDENTIFIERS,
            message=TurnMessage(role="assistant", blocks=[TEXT]),
        ),
        TurnCompletedEvent(identifiers=IDENTIFIERS),
    ]


class QueuedStream(EventStream):
    """What both adapters hand back: one queue, read with or without deltas."""

    def __init__(self, queue: asyncio.Queue[LiveTurnEvent | None]) -> None:
        self.queue = queue
        self.reads = 0

    async def read(self) -> AsyncIterator[LiveTurnEvent]:
        self.reads += 1
        while (event := await self.queue.get()) is not None:
            yield event

    async def durable(self) -> AsyncIterator[TurnEvent]:
        async for event in self.read():
            if (kept := event.durable) is not None:
                yield kept

    def events(self) -> AsyncIterator[TurnEvent]:
        return self.durable()

    def live(self) -> AsyncIterator[LiveTurnEvent]:
        return self.read()


class Unbound(TurnToolBinder):
    """No submission tool to install: these turns ask for no typed output."""

    async def bind[T: BaseModel](self, binding: TurnToolBinding[T] | None) -> None:
        return None


class Stopped(Interrupt):
    """An interrupt that ends the turn it belongs to, as a provider's does."""

    def __init__(self, provider: "Provider") -> None:
        self.provider = provider

    async def interrupt(self) -> None:
        self.provider.interrupted += 1
        self.provider.release.set()


class Steered(Steer):
    def __init__(self, provider: "Provider") -> None:
        self.provider = provider

    async def steer(self, input: TurnInput) -> None:
        self.provider.steered.append(input.text)


class Provider:
    """A scripted adapter: each start feeds a queue and completes on release."""

    def __init__(
        self,
        events: list[LiveTurnEvent] | None = None,
        *,
        fails: bool = False,
        steers: bool = False,
        waits: bool = False,
    ) -> None:
        self.script = said() if events is None else events
        self.fails = fails
        self.steers = steers
        self.release = asyncio.Event()
        if not waits:
            self.release.set()
        self.started: list[str] = []
        self.streams: list[QueuedStream] = []
        self.interrupted = 0
        self.steered: list[str] = []

    async def start(self, text: str) -> AcceptedTurn:
        self.started.append(text)
        queue: asyncio.Queue[LiveTurnEvent | None] = asyncio.Queue()
        stream = QueuedStream(queue)
        self.streams.append(stream)

        async def complete() -> CompletedTurn:
            await self.release.wait()
            for event in self.script:
                queue.put_nowait(event)
            queue.put_nowait(None)
            if self.fails:
                raise ProviderTurnError(TurnFailure(message="the provider failed"))
            return CompletedTurn(blocks=[TEXT], identifiers=IDENTIFIERS)

        return AcceptedTurn(
            identifiers=IDENTIFIERS,
            complete=complete,
            events=stream,
            interrupt=Stopped(self),
            steer=Steered(self) if self.steers else None,
        )

    def engine(self) -> ComposedSession:
        return ComposedSession(self.start, Unbound())


def asked(
    engine: SessionEngine, prompt: str = "go", *, deltas: bool = True
) -> LazyTurn[None]:
    return LazyTurn(
        engine, TurnRequest[None](input=TurnInput(text=prompt)), deltas=deltas
    )


async def test_asking_starts_nothing_until_something_asks() -> None:
    provider = Provider()
    turn = asked(provider.engine())
    await asyncio.sleep(0)

    assert provider.started == []

    result = await turn.result()

    assert provider.started == ["go"]
    assert result.blocks == [TEXT]


async def test_awaiting_again_returns_the_same_result_and_starts_once() -> None:
    provider = Provider()
    turn = asked(provider.engine())

    first = await turn.result()
    second = await turn.result()

    assert first is second
    assert provider.started == ["go"]


async def test_iteration_yields_completed_blocks_only() -> None:
    provider = Provider()
    turn = asked(provider.engine())

    blocks = [block async for block in turn.blocks()]

    assert blocks == [TEXT]


async def test_awaiting_after_iterating_returns_the_same_result() -> None:
    provider = Provider()
    turn = asked(provider.engine())

    blocks = [block async for block in turn.blocks()]
    result = await turn.result()

    assert blocks == result.blocks
    assert provider.started == ["go"]


async def test_concurrent_askers_start_the_turn_once() -> None:
    provider = Provider()
    turn = asked(provider.engine())

    async def iterate() -> list[TurnTextBlock | object]:
        return [block async for block in turn.blocks()]

    results = await asyncio.gather(turn.result(), iterate(), turn.result())

    assert provider.started == ["go"]
    assert results[0] is results[2]


async def test_every_view_reads_the_whole_turn_from_one_reading() -> None:
    provider = Provider()
    turn = asked(provider.engine())
    await turn.result()

    durable = [event async for event in turn.events()]
    live = [event async for event in turn.live()]
    again = [event async for event in turn.events()]

    assert [event.type for event in durable] == [
        "turn_started",
        "block_completed",
        "message_completed",
        "turn_completed",
    ]
    assert [event.type for event in live] == [event.type for event in said()]
    assert again == durable
    assert [stream.reads for stream in provider.streams] == [1]


async def test_a_session_without_deltas_refuses_the_live_view_at_once() -> None:
    provider = Provider()
    turn = asked(provider.engine(), deltas=False)

    with pytest.raises(DeltaStreamingDisabled):
        turn.live()

    assert provider.started == []
    assert [event.type async for event in turn.events()] == [
        "turn_started",
        "block_completed",
        "message_completed",
        "turn_completed",
    ]


async def test_a_failed_turn_ends_every_view_with_its_failure() -> None:
    provider = Provider(fails=True)
    turn = asked(provider.engine())

    seen: list[TurnTextBlock | object] = []
    with pytest.raises(ProviderTurnError, match="the provider failed"):
        async for block in turn.blocks():
            seen.append(block)

    assert seen == [TEXT]
    with pytest.raises(ProviderTurnError, match="the provider failed"):
        await turn.result()


async def test_interrupting_starts_stops_and_frees_the_session() -> None:
    provider = Provider(waits=True)
    engine = provider.engine()
    turn = asked(engine, "long job")

    await turn.interrupt()

    assert provider.started == ["long job"]
    assert provider.interrupted == 1
    assert engine.active is False
    follow_up = await asked(engine, "next").result()
    assert follow_up.blocks == [TEXT]


async def test_a_turn_nobody_awaits_still_hands_its_session_back() -> None:
    provider = Provider()
    engine = provider.engine()
    watched = asked(engine, "watched only")

    assert [block async for block in watched.blocks()] == [TEXT]
    await asyncio.sleep(0)

    assert (await asked(engine, "after").result()).blocks == [TEXT]


async def test_steering_reaches_the_engine_that_steers() -> None:
    provider = Provider(steers=True, waits=True)
    turn = asked(provider.engine())

    await turn.steer("also do z")
    provider.release.set()
    await turn.result()

    assert provider.steered == ["also do z"]


async def test_steering_an_engine_that_cannot_is_an_invariant_failure() -> None:
    provider = Provider()
    turn = asked(provider.engine())

    with pytest.raises(RuntimeError, match="no steering"):
        await turn.steer("anything")


def test_layers_over_others_keep_what_they_set_and_add_their_wrappers() -> None:
    first = CleanupWrapper(lambda: None)
    second = CleanupWrapper(lambda: None)
    beneath = SessionLayers(
        timeout=TimeoutConfig(seconds=5), serialized=True, wrappers=[first]
    )
    over = SessionLayers(correction=CorrectionConfig(cycles=2), wrappers=[second])

    laid = over.over(beneath)

    assert laid.timeout == TimeoutConfig(seconds=5)
    assert laid.correction == CorrectionConfig(cycles=2)
    assert laid.serialized is True
    assert laid.wrappers == [first, second]


class Recording(SessionWrapper):
    """Record when this wrapper's session opens and closes, by name."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self.log = log

    def around(
        self,
        opened: AbstractAsyncContextManager[SessionEngine],
        resume: SessionId | None,
    ) -> AbstractAsyncContextManager[SessionEngine]:
        return self.recorded(opened)

    @asynccontextmanager
    async def recorded(
        self, opened: AbstractAsyncContextManager[SessionEngine]
    ) -> AsyncGenerator[SessionEngine]:
        self.log.append(f"open {self.name}")
        async with opened as engine:
            yield engine
        self.log.append(f"close {self.name}")


@asynccontextmanager
async def native(
    engine: SessionEngine, log: list[str]
) -> AsyncGenerator[SessionEngine]:
    log.append("open provider")
    yield engine
    log.append("close provider")


async def test_wrappers_go_around_the_turn_layers_the_first_innermost() -> None:
    log: list[str] = []
    provider = Provider()
    layers = SessionLayers(
        correction=CorrectionConfig(cycles=1),
        wrappers=[Recording("inner", log), Recording("outer", log)],
    )

    async with layers.around(native(provider.engine(), log), None) as engine:
        assert isinstance(engine, DecoratingSession)
        await asked(engine).result()

    assert log == [
        "open outer",
        "open inner",
        "open provider",
        "close provider",
        "close inner",
        "close outer",
    ]


async def test_no_turn_layer_leaves_the_engine_bare_and_serialized_queues() -> None:
    provider = Provider()

    async with SessionLayers().around(native(provider.engine(), []), None) as bare:
        assert isinstance(bare, ComposedSession)
    async with SessionLayers(serialized=True).around(
        native(provider.engine(), []), None
    ) as queued:
        assert isinstance(queued, SerializedSession)


async def test_a_cleanup_runs_when_the_session_closes_on_failure() -> None:
    cleaned: list[str] = []
    provider = Provider()
    layers = SessionLayers(wrappers=[CleanupWrapper(lambda: cleaned.append("done"))])

    with pytest.raises(RuntimeError, match="the caller failed"):
        async with layers.around(native(provider.engine(), []), None):
            raise RuntimeError("the caller failed")

    assert cleaned == ["done"]


class Refusing(EventStream):
    """A stream built without partial streaming, as a Claude session can be."""

    def __init__(self, inner: QueuedStream) -> None:
        self.inner = inner

    def events(self) -> AsyncIterator[TurnEvent]:
        return self.inner.events()

    def live(self) -> AsyncIterator[LiveTurnEvent]:
        raise DeltaStreamingDisabled("built without partials")


async def test_a_refused_live_view_leaves_the_resilient_stream_whole() -> None:
    queue: asyncio.Queue[LiveTurnEvent | None] = asyncio.Queue()
    for event in said():
        queue.put_nowait(event)
    queue.put_nowait(None)
    switching = SwitchingEventStream(Refusing(QueuedStream(queue)))
    switching.close()

    with pytest.raises(DeltaStreamingDisabled):
        [event async for event in switching.live()]

    assert [event.type async for event in switching.events()] == [
        "turn_started",
        "block_completed",
        "message_completed",
        "turn_completed",
    ]
