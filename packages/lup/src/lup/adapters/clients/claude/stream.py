"""The Claude engine's live event stream.

The Claude SDK feeds messages as the turn unfolds, so this engine
implements the :class:`~lup.adapters.clients.Stream.Stream` verb itself
rather than taking the replay gap-filler.
"""

from collections.abc import AsyncGenerator

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.adapters.clients.claude.collector import ClaudeResponseCollector
from lup.adapters.clients.claude.messages import (
    claude_block_to_lup,
    claude_message_to_lup,
)
from lup.adapters.clients.Stream import Stream
from lup.telemetry.display import print_message
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupContentBlock,
    LupDoneEvent,
    LupEvent,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
)


class ClaudeLiveStream(Stream):
    """Streams events live from the Claude SDK.

    Drains through
    :class:`~lup.adapters.clients.claude.collector.ClaudeResponseCollector`
    — the same walk the session path uses — mapping each SDK block to its
    live event as it arrives. The collector raises after yielding an
    error result, so the terminal ``LupDoneEvent`` still reaches the
    consumer first.
    """

    def __init__(self, options: claude.ClaudeAgentOptions) -> None:
        self.options = options

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        collected: list[LupContentBlock] = []
        async with claude.ClaudeSDKClient(options=self.options) as client:
            await client.query(prompt)
            collector = ClaudeResponseCollector(
                client, trace_logger=trace_logger, prefix=prefix
            )
            async for message in collector.drain():
                lup_msg = claude_message_to_lup(message)
                if lup_msg is not None and trace_logger:
                    print_message(lup_msg, prefix=prefix, trace=trace_logger)

                match message:
                    case claude_types.AssistantMessage():
                        for block in message.content:
                            collected.append(claude_block_to_lup(block))
                            match block:
                                case claude.ThinkingBlock():
                                    if block.thinking:
                                        yield LupThinkingEvent(thinking=block.thinking)
                                case claude.TextBlock():
                                    yield LupTextEvent(text=block.text)
                                case claude.ToolUseBlock():
                                    yield LupToolUseEvent(id=block.id, name=block.name)
                    case claude_types.UserMessage():
                        if isinstance(message.content, list):
                            for block in message.content:
                                if isinstance(block, claude.ToolResultBlock):
                                    yield LupToolResultEvent(
                                        tool_use_id=block.tool_use_id,
                                        content=str(block.content),
                                    )
                    case claude_types.ResultMessage():
                        yield LupDoneEvent(blocks=collected)
