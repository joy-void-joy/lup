"""The stream gap-filler: run the whole turn, then replay its blocks."""

from collections.abc import AsyncGenerator

from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.clients.streams.Stream import Stream
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupDoneEvent,
    LupEvent,
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
    """A ``Stream`` wrapping a ``Sessions``: whole turn first, events after.

    One turn in a fresh session, then every response block replayed as
    its event with the terminal ``LupDoneEvent`` last. Preserves the
    block→event mapping every consumer expects, for engines whose SDK
    reports a turn only once it is complete.
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
