"""Agent adapter ABC and unified ``query()`` frontend.

Each SDK adapter implements this interface. Consumer code (core.py)
instantiates the appropriate adapter via ``build_adapter()`` and calls
``run()`` (one-shot) or ``conversation()`` (multi-turn).

The module-level ``query()`` dispatches to the appropriate SDK adapter
based on model name — consumer code never imports from SDK packages.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager

from typing import Literal

from pydantic import BaseModel

from lup.trace import TraceLogger
from lup.types import LupDoneEvent, LupEvent, LupResponse, model_backend

type PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]


class BudgetExceededError(RuntimeError):
    """A conversation refused to start a turn: accumulated cost reached the budget.

    Raised between turns by adapters that enforce ``max_budget_usd``
    through their own usage accounting (the Codex runtime reports token
    counts, not cost). The turn that crossed the budget has already
    completed — this error stops the *next* one.
    """


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
    def conversation(self) -> AbstractAsyncContextManager[Conversation]:
        """Create a multi-turn conversation session.

        Implementations are ``@asynccontextmanager`` async generators
        yielding a ``Conversation`` that maintains state across turns.
        The SDK client/thread is created on entry and cleaned up on exit.
        """

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """One-shot convenience: open conversation, send one prompt, close."""
        async with self.conversation() as conv:
            return await conv.send(prompt, trace_logger=trace_logger, prefix=prefix)

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

    if backend != "anthropic":
        claude_only = {
            "max_turns": max_turns,
            "max_thinking_tokens": max_thinking_tokens,
            "tools": tools,
            "allowed_tools": allowed_tools,
            "permission_mode": permission_mode,
            "max_budget_usd": max_budget_usd,
        }
        requested = sorted(k for k, v in claude_only.items() if v is not None)
        if requested:
            raise ValueError(
                f"query() options {requested} are not supported on the "
                f"{backend} backend (model={effective_model!r}); use a "
                "Claude model or drop these options."
            )

    match backend:
        case "anthropic":
            from lup.adapters.claude_client import claude_query

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
