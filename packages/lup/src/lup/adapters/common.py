# claude: ignore
"""Agent adapter ABC and unified ``query()`` frontend.

Each SDK adapter implements this interface. Consumer code (core.py)
instantiates the appropriate adapter via ``build_adapter()`` and calls
``run()`` (one-shot) or ``conversation()`` (multi-turn).

The module-level ``query()`` dispatches to the appropriate SDK adapter
based on model name — consumer code never imports from SDK packages.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from typing import Literal

from pydantic import BaseModel

from lup.trace import TraceLogger
from lup.types import LupContentBlock, LupResponse, model_backend

type PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------


class LupEvent:
    """Base class for normalized streaming events."""

    pass


class LupTextEvent(LupEvent):
    """Streamed text delta."""

    def __init__(self, text: str) -> None:
        self.text = text


class LupToolUseEvent(LupEvent):
    """Streamed tool invocation start."""

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


class LupToolResultEvent(LupEvent):
    """Streamed tool result."""

    def __init__(self, tool_use_id: str, content: str) -> None:
        self.tool_use_id = tool_use_id
        self.content = content


class LupThinkingEvent(LupEvent):
    """Streamed thinking content."""

    def __init__(self, thinking: str) -> None:
        self.thinking = thinking


class LupDoneEvent(LupEvent):
    """Stream complete."""

    def __init__(self, blocks: list[LupContentBlock] | None = None) -> None:
        self.blocks = blocks or []


# ---------------------------------------------------------------------------
# Conversation (multi-turn session)
# ---------------------------------------------------------------------------


class Conversation(ABC):
    """Multi-turn conversation session.

    Wraps a persistent SDK client or thread. ``send()`` sends a message
    and collects the full response. ``interrupt()`` signals the backend
    to stop the current response (Ctrl-C support).
    """

    @abstractmethod
    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse: ...

    async def interrupt(self) -> None:
        """Signal the backend to stop the current response. No-op by default."""
        pass


# ---------------------------------------------------------------------------
# Adapter ABC
# ---------------------------------------------------------------------------


class AgentAdapter(ABC):
    """Run prompts against an SDK backend.

    The single abstract method is ``conversation()``, which yields a
    multi-turn ``Conversation``. ``run()`` is a convenience that opens
    a conversation, sends one prompt, and closes it.
    """

    @abstractmethod
    @asynccontextmanager
    async def conversation(self) -> AsyncGenerator[Conversation, None]:
        """Create a multi-turn conversation session.

        Yields a ``Conversation`` that maintains state across turns.
        The SDK client/thread is created on entry and cleaned up on exit.
        """
        yield  # type: ignore[misc]

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """One-shot convenience: open conversation, send one prompt, close."""
        async with self.conversation() as conv:
            return await conv.send(
                prompt, trace_logger=trace_logger, prefix=prefix
            )

    async def resume(self, session_id: str, prompt: str) -> LupResponse:
        """Resume a previous session by ID. Not all adapters support this."""
        raise NotImplementedError(f"{type(self).__name__} does not support resume")

    async def fork(self, session_id: str, prompt: str) -> LupResponse:
        """Fork a previous session and run on the fork."""
        raise NotImplementedError(f"{type(self).__name__} does not support fork")

    async def run_streamed(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Run with streaming events. Default falls back to non-streaming."""
        response = await self.run(prompt, trace_logger=trace_logger, prefix=prefix)
        yield LupDoneEvent(blocks=response.blocks)


# ---------------------------------------------------------------------------
# Unified query() — dispatches to the right adapter by model name
# ---------------------------------------------------------------------------


async def query(
    prompt: str,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    output_type: type[BaseModel] | None = None,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    max_budget_usd: float | None = None,
) -> LupResponse:
    """One-shot query that routes to the right SDK adapter by model name.

    For Claude models (``claude-*``, ``haiku``, ``sonnet``, ``opus``),
    uses the Claude Agent SDK. For Codex/GPT models, uses the Codex SDK.
    For everything else, uses the OpenAI-compatible adapter via Codex.

    Returns a ``LupResponse`` — use ``.text`` for text or
    ``.output(MyModel)`` for structured output.
    """
    effective_model = model or "claude-sonnet-4-6"
    backend = model_backend(effective_model)

    output_schema = output_type.model_json_schema() if output_type else None

    match backend:
        case "anthropic":
            return await claude_query(
                prompt,
                model=effective_model,
                system_prompt=system_prompt,
                output_schema=output_schema,
                trace_logger=trace_logger,
                prefix=prefix,
                max_turns=max_turns,
                max_thinking_tokens=max_thinking_tokens,
                tools=tools,
                allowed_tools=allowed_tools,
                permission_mode=permission_mode,
                max_budget_usd=max_budget_usd,
            )
        case "openai":
            from lup.adapters.codex import CodexAdapter

            codex_adapter: AgentAdapter = CodexAdapter(
                model=effective_model,
                system_prompt=system_prompt or "",
                output_schema=output_schema,
                mcp_tools=False,
            )
            return await codex_adapter.run(
                prompt, trace_logger=trace_logger, prefix=prefix
            )
        case _:
            from lup.adapters.openai_compat import OpenAICompatibleAdapter

            compat_adapter: AgentAdapter = OpenAICompatibleAdapter(
                model=effective_model,
                system_prompt=system_prompt or "",
                output_schema=output_schema,
                mcp_tools=False,
            )
            return await compat_adapter.run(
                prompt, trace_logger=trace_logger, prefix=prefix
            )


async def claude_query(
    prompt: str,
    *,
    model: str = "claude-sonnet-4-6",
    system_prompt: str | None = None,
    output_schema: dict[str, object] | None = None,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
    max_turns: int | None = None,
    max_thinking_tokens: int | None = None,
    tools: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    permission_mode: PermissionMode | None = None,
    max_budget_usd: float | None = None,
) -> LupResponse:
    """One-shot query via the Claude Agent SDK, returning LupResponse."""
    from lup.adapters.claude_client import query as claude_sdk_query

    collector = await claude_sdk_query(
        prompt,
        model=model,
        system_prompt=system_prompt,
        prefix=prefix,
        trace_logger=trace_logger,
        max_turns=max_turns,
        max_thinking_tokens=max_thinking_tokens,
        tools=tools,
        allowed_tools=allowed_tools,
        permission_mode=permission_mode,
        max_budget_usd=max_budget_usd,
        output_format=(
            {"type": "json_schema", "schema": output_schema}
            if output_schema
            else None
        ),
    )

    from lup.adapters.claude import claude_block_to_lup

    from lup.types import (
        LupAssistantMessage,
        LupResultMessage,
    )

    blocks = [claude_block_to_lup(b) for b in collector.blocks]
    tool_results = [claude_block_to_lup(b) for b in collector.tool_results]

    response = LupResponse(blocks=blocks, tool_results=tool_results)
    for msg in collector.messages:
        from claude_agent_sdk.types import AssistantMessage

        if isinstance(msg, AssistantMessage):
            lup_blocks = [claude_block_to_lup(b) for b in msg.content]
            response.messages.append(LupAssistantMessage(content=lup_blocks))

    if collector.result is not None:
        response.result = LupResultMessage(
            structured_output=collector.result.structured_output,
            is_error=collector.result.is_error,
            result=collector.result.result,
            duration_ms=collector.result.duration_ms,
            total_cost_usd=collector.result.total_cost_usd,
            usage=collector.result.usage,
        )

    return response
