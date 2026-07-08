"""The Claude engine's run path: ``create_claude``, sessions, and the client.

Construction refuses through the shared consume-tracking seam
(:mod:`lup.adapters.clients.refusal`) over the translation in
:mod:`lup.adapters.clients.claude.options`; the run path drains every
turn through the collector in
:mod:`lup.adapters.clients.claude.collector`.
"""

import copy
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.adapters.clients.claude.collector import (
    ClaudeResponseCollector,
    ClaudeUsageNormalizer,
)
from lup.adapters.clients.claude.messages import (
    claude_block_to_lup,
    claude_message_to_lup,
)
from lup.adapters.clients.claude.options import build_claude_options
from lup.adapters.clients.Client import Client, Session
from lup.adapters.clients.fallbacks import query_via_session
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.clients.usage import extract_token_usage
from lup.adapters.options import LupAgentOptions
from lup.telemetry.display import print_message
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupContentBlock,
    LupDoneEvent,
    LupEvent,
    LupResponse,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
)


def create_claude(options: LupAgentOptions) -> Client:
    """Build a Claude Agent SDK client from neutral options.

    Consumes the in-process mechanism payloads (hooks, tool servers,
    native subagent definitions) and ignores the subprocess ones (served
    tool groups, writable roots). The one intent knob the SDK has no lever
    for is ``turn_timeout_seconds`` — the SDK exposes no client-side
    per-turn wall-clock cap (checked against claude-agent-sdk's
    ``ClaudeAgentOptions``: ``max_turns`` and ``max_budget_usd`` exist,
    nothing bounds a single turn's duration), so it is left unread and
    refused.
    """
    return ClaudeClient(refuse_unconsumed("claude", options, build_claude_options))


class ClaudeSession(Session):
    """Multi-turn conversation via the Claude Agent SDK.

    ``id`` carries the SDK session id: seeded when the session was opened
    with ``resume=``, refreshed from each turn's result otherwise.
    """

    def __init__(
        self,
        client: claude.ClaudeSDKClient,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
        resumed: str | None = None,
    ) -> None:
        self.client = client
        self.usage_normalizer = usage_normalizer
        self.id = resumed

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        await self.client.query(prompt)
        collector = ClaudeResponseCollector(
            self.client,
            usage_normalizer=self.usage_normalizer,
            trace_logger=trace_logger,
            prefix=prefix,
        )
        response = await collector.collect()
        self.id = response.session_id or self.id
        return response

    async def interrupt(self) -> None:
        await self.client.interrupt()


class ClaudeClient(Client):
    """Run prompts via the Claude Agent SDK.

    Args:
        options: Native SDK options built by
            :func:`~lup.adapters.clients.claude.options.build_claude_options`.
        usage_normalizer: Transforms the raw SDK usage payload into a
            ``Usage`` (or subclass, for vendor-specific fields).
    """

    def __init__(
        self,
        options: claude.ClaudeAgentOptions,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
    ) -> None:
        self.options = options
        self.usage_normalizer = usage_normalizer

    @asynccontextmanager
    async def session(
        self, *, resume: str | None = None
    ) -> AsyncGenerator[Session, None]:
        options = self.options
        if resume:
            options = copy.copy(self.options)
            options.resume = resume
        async with claude.ClaudeSDKClient(options=options) as client:
            yield ClaudeSession(
                client, usage_normalizer=self.usage_normalizer, resumed=resume
            )

    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        return await query_via_session(
            self, prompt, trace_logger=trace_logger, prefix=prefix
        )

    async def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Stream events live from the Claude SDK.

        Drains through :class:`~lup.adapters.clients.claude.collector.ClaudeResponseCollector`
        — the same walk the one-shot/session path uses — mapping each SDK
        block to its live event as it arrives. The collector raises after
        yielding an error result, so the terminal ``LupDoneEvent`` still
        reaches the consumer first.
        """
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
