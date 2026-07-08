"""The composed client's generic gap-filling over a sessions component.

``ComposedClient`` is the one concrete ``Client``: engines contribute a
sessions component (and optionally a live stream), and the gaps fill
generically. These tests pin the replay path — an engine without a live
stream must still yield blocks as events in order with the done event
last — since every post-hoc engine (codex, openai-compat) rides it.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from lup.adapters.clients.Client import Session
from lup.adapters.clients.composed import ComposedClient, ReplayStream
from lup.adapters.clients.Sessions import Sessions
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupDoneEvent,
    LupResponse,
    LupTextBlock,
    LupTextEvent,
    LupThinkingBlock,
    LupThinkingEvent,
    LupToolResultBlock,
    LupToolResultEvent,
    LupToolUseBlock,
    LupToolUseEvent,
)


class CannedSession(Session):
    """One scripted response per send."""

    def __init__(self, response: LupResponse) -> None:
        self.response = response

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        _ = (prompt, trace_logger, prefix)
        return self.response

    async def interrupt(self) -> None:
        raise NotImplementedError("CannedSession has no interrupt")


class CannedSessions(Sessions):
    """A sessions component yielding canned sessions."""

    def __init__(self, response: LupResponse) -> None:
        self.response = response

    @asynccontextmanager
    async def open(self, *, resume: str | None = None) -> AsyncGenerator[Session, None]:
        _ = resume
        yield CannedSession(self.response)


CANNED = LupResponse(
    blocks=[
        LupThinkingBlock(thinking="hmm"),
        LupTextBlock(text="hello"),
        LupToolUseBlock(id="t1", name="command_execution", input={}),
        LupToolResultBlock(tool_use_id="t1", content="out"),
    ]
)


async def test_stream_gap_replays_blocks_in_order() -> None:
    """A composition without a live stream replays blocks as events."""
    client = ComposedClient(CannedSessions(CANNED))
    assert isinstance(client.streams, ReplayStream)

    events = [event async for event in client.stream("go")]

    assert [type(event) for event in events] == [
        LupThinkingEvent,
        LupTextEvent,
        LupToolUseEvent,
        LupToolResultEvent,
        LupDoneEvent,
    ]
    done = events[-1]
    assert isinstance(done, LupDoneEvent)
    assert done.blocks == CANNED.blocks


async def test_query_gap_runs_one_turn_in_a_fresh_session() -> None:
    """The one-shot fills from the sessions component."""
    client = ComposedClient(CannedSessions(CANNED))

    response = await client.query("go")

    assert response is CANNED
