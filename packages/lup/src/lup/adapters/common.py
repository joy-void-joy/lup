"""Agent adapter ABC and unified ``query()`` frontend.

Each SDK adapter implements this interface. Consumer code (core.py)
instantiates the appropriate adapter via ``build_adapter()`` and calls
``run()`` (one-shot) or ``conversation()`` (multi-turn).

The module-level ``query()`` dispatches to the appropriate SDK adapter
based on model name — consumer code never imports from SDK packages.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Mapping
from contextlib import AbstractAsyncContextManager

from typing import Literal

from pydantic import BaseModel

from lup.trace import TraceLogger
from lup.types import LupDoneEvent, LupEvent, LupResponse, model_backend

logger = logging.getLogger(__name__)

type PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]


class AdapterCapabilities(BaseModel):
    """What a backend can do — the parity contract as data.

    Consumers branch on these fields instead of matching backend names,
    devtools render them (``lup-devtools agent capabilities``), and the
    parity test asserts them. A new cross-backend feature must add a
    field here, which forces every adapter to take a position.
    """

    model_config = {"use_attribute_docstrings": True}

    hooks: bool
    """In-process LupHooksConfig is honored (PreToolUse/PostToolUse/Stop)."""

    native_subagents: bool
    """SubagentSpec runs natively in parallel (vs the run_subagent tool)."""

    streaming: Literal["live", "post_hoc"]
    """run_streamed yields events during the turn, or replays them after."""

    interrupt: bool
    """Conversation.interrupt() actually stops the current response."""

    stop_event: bool
    """Backend emits a stop event, so Stop hooks (completion guard) fire."""

    cost_reporting: Literal["native", "rates", "none"]
    """Cost is SDK-reported, estimated from caller-supplied rates, or absent."""

    duration_reporting: bool
    """Result messages carry duration_ms."""

    permission_modes: bool
    """Backend honors PermissionMode settings."""

    max_turns: bool
    """Backend enforces a per-session turn cap."""

    max_thinking_tokens: bool
    """Backend accepts an explicit thinking-token budget."""

    background_tools: bool
    """Background agents can act through tools (vs text-only summarizers)."""

    realtime: Literal["in_process", "relay"]
    """Persistent (sleep/wake) transport: in-process tools or the file relay."""

    turn_timeout: bool
    """Conversations enforce a wall-clock per-turn timeout (turn_timeout_seconds)."""


def canonical_capability_matrix() -> dict[str, AdapterCapabilities]:
    """The shipped backends' capabilities, in canonical display form.

    The single source for every rendering of the parity contract: the
    ``lup-devtools agent capabilities`` command, the README table, and
    the regression test that keeps the two identical. Codex/OpenAI are
    shown with budget rates configured (their best case) —
    ``cost_reporting`` degrades to ``none`` without ``CODEX_USD_PER_MTOK``
    rates.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    from lup.adapters.claude import ClaudeAdapter
    from lup.adapters.codex import CodexAdapter, per_mtok_usage_cost
    from lup.adapters.openai_compat import OpenAICompatibleAdapter

    rates = per_mtok_usage_cost(input_usd=1.0, output_usd=1.0)
    return {
        "claude": ClaudeAdapter(ClaudeAgentOptions()).capabilities,
        "codex": CodexAdapter(
            model="gpt-5.5", system_prompt="", usage_cost=rates
        ).capabilities,
        "openai": OpenAICompatibleAdapter(model="local", usage_cost=rates).capabilities,
    }


def capability_matrix_markdown(adapters: Mapping[str, AdapterCapabilities]) -> str:
    """Render a capability matrix as a markdown table.

    One row per capability field, one column per backend — the generated
    form of the parity contract. The README embeds it and a regression
    test regenerates and diffs it, so prose cannot drift from the
    declarations.
    """
    names = list(adapters)
    lines = [
        "| Capability | " + " | ".join(names) + " |",
        "|---" * (len(names) + 1) + "|",
    ]
    for field in AdapterCapabilities.model_fields:
        cells: list[str] = []
        for name in names:
            match getattr(adapters[name], field):
                case bool() as flag:
                    cells.append("✅" if flag else "—")
                case value:
                    cells.append(str(value))
        lines.append(f"| {field} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


class TurnTimeoutError(RuntimeError):
    """A turn exceeded its wall-clock timeout and was cancelled client-side.

    Raised by adapters with ``capabilities.turn_timeout`` when a single
    turn runs past ``turn_timeout_seconds``. The backend thread's state
    is undefined afterwards — close the conversation rather than sending
    further turns on it.
    """


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
        """Signal the backend to stop the current response.

        Backends without interruption support inherit this default, which
        logs and returns — check ``adapter.capabilities.interrupt`` before
        offering an interrupt affordance that would do nothing.
        """
        logger.warning("interrupt() is not supported on %s", type(self).__name__)


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

    @property
    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        """Declare what this backend supports — see :class:`AdapterCapabilities`.

        A property (not a constant) because some entries depend on
        instance configuration, e.g. Codex cost reporting requires a
        caller-supplied rate estimator.
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
        }
        requested = sorted(k for k, v in claude_only.items() if v is not None)
        if requested:
            raise ValueError(
                f"query() options {requested} are not supported on the "
                f"{backend} backend (model={effective_model!r}); use a "
                "Claude model or drop these options."
            )
        if max_budget_usd is not None:
            raise ValueError(
                "max_budget_usd cannot be enforced by a one-shot query() on "
                f"the {backend} backend: the Codex runtime enforces budgets "
                "between turns from caller-supplied rates, and a one-shot "
                "query has no next turn to refuse. Use "
                "CodexAdapter(max_budget_usd=..., usage_cost=...) for "
                "multi-turn enforcement."
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
