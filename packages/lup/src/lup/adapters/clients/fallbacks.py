"""Shared method bodies for engines missing a native one-shot or live stream.

An engine without a self-contained one-shot implements ``Client.query``
as a one-line call to :func:`query_via_session`; an engine without a
live event stream implements ``Client.stream`` as a one-line call to
:func:`replay_stream`, which runs the turn to completion and replays its
blocks. Both are explicit choices written in the engine's own module —
the :class:`~lup.adapters.clients.Client.Client` ABC itself carries no
concrete defaults.
"""

from collections.abc import AsyncGenerator

from lup.adapters.clients.Client import Client
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


async def query_via_session(
    client: Client,
    prompt: str,
    *,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
) -> LupResponse:
    """Open a session, send one prompt, close — the self-contained one-shot.

    The shared ``Client.query`` body for engines whose one-shot is just a
    single-turn session.
    """
    async with client.session() as session:
        return await session.send(prompt, trace_logger=trace_logger, prefix=prefix)


async def replay_stream(
    client: Client,
    prompt: str,
    *,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
) -> AsyncGenerator[LupEvent, None]:
    """Run the turn to completion, then replay its blocks as events.

    The shared ``Client.stream`` body for engines without a live event
    stream. Preserves the block→event mapping every consumer expects.
    """
    response = await client.query(prompt, trace_logger=trace_logger, prefix=prefix)
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
