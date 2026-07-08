"""Engine components composed into the one concrete ``Client``.

There are no per-engine ``Client`` subclasses. An engine contributes the
small verbs it natively has — always its
:class:`~lup.adapters.clients.Sessions.Sessions`, plus a
:class:`~lup.adapters.clients.Stream.Stream` when its SDK feeds events
live — and construction composes them here. Gaps fill generically:
``query`` runs one turn in a fresh session, and a missing live stream
becomes :class:`ReplayStream`. Extending an engine is contributing a new
component that implements a verb, never subclassing the client.
"""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager

from lup.adapters.clients.Client import Client, Session
from lup.adapters.clients.Sessions import Sessions
from lup.adapters.clients.Stream import Stream
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupDoneEvent,
    LupEvent,
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


class ReplayStream(Stream):
    """The stream gap-filler: run the whole turn, then replay its blocks.

    Wraps an engine's :class:`Sessions` — one turn in a fresh session,
    then every response block replayed as its event with the terminal
    ``LupDoneEvent`` last. Preserves the block→event mapping every
    consumer expects, for engines whose SDK reports a turn only once it
    is complete.
    """

    def __init__(self, sessions: Sessions) -> None:
        self.sessions = sessions

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        async with self.sessions.open() as session:
            response = await session.send(
                prompt, trace_logger=trace_logger, prefix=prefix
            )
        for block in response.blocks:
            match block:
                case LupThinkingBlock():
                    yield LupThinkingEvent(thinking=block.thinking)
                case LupTextBlock():
                    yield LupTextEvent(text=block.text)
                case LupToolUseBlock():
                    yield LupToolUseEvent(id=block.id, name=block.name)
                case LupToolResultBlock():
                    yield LupToolResultEvent(
                        tool_use_id=block.tool_use_id,
                        content=str(block.content),
                    )
        yield LupDoneEvent(blocks=response.blocks)


class ComposedClient(Client):
    """The one concrete ``Client``: an engine's components behind the seam.

    Args:
        sessions: The engine's session opener — the component every
            engine contributes.
        streams: The engine's live event stream, when its SDK has one;
            left ``None``, the slot is filled with :class:`ReplayStream`
            over the same sessions.
    """

    def __init__(self, sessions: Sessions, *, streams: Stream | None = None) -> None:
        self.sessions = sessions
        self.streams = streams if streams is not None else ReplayStream(sessions)

    def session(
        self, *, resume: str | None = None
    ) -> AbstractAsyncContextManager[Session]:
        return self.sessions.open(resume=resume)

    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        async with self.sessions.open() as session:
            return await session.send(prompt, trace_logger=trace_logger, prefix=prefix)

    def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        return self.streams.run(prompt, trace_logger=trace_logger, prefix=prefix)
