"""Agent adapter interface and unified ``query()`` frontend.

Each SDK engine implements this interface (``AgentAdapter`` +
``Conversation``) and declares what it supports (``AdapterCapabilities``).
Consumer code (core.py) obtains adapters through the registry and calls
``run()`` (one-shot) or ``conversation()`` (multi-turn).

The module-level ``query()`` routes by model name through the registry's
one-shot builders. This module defines the seam and never imports an
engine; consumer code never imports from SDK packages.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager

from typing import Literal

from pydantic import BaseModel

from lup.trace import TraceLogger
from lup.types import (
    Backend,
    JsonObject,
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
    model_backend,
)

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


class BackendCapabilities(BaseModel):
    """One backend's capability declaration, labeled for display."""

    name: str
    capabilities: AdapterCapabilities


def capability_matrix_markdown(backends: list[BackendCapabilities]) -> str:
    """Render a capability matrix as a markdown table.

    One row per capability field, one column per backend — the generated
    form of the parity contract. The README embeds it and a regression
    test regenerates and diffs it, so prose cannot drift from the
    declarations.
    """
    lines = [
        "| Capability | " + " | ".join(b.name for b in backends) + " |",
        "|---" * (len(backends) + 1) + "|",
    ]
    for field in AdapterCapabilities.model_fields:
        cells: list[str] = []
        for backend in backends:
            match getattr(backend.capabilities, field):
                case bool() as flag:
                    cells.append("✅" if flag else "—")
                case value:
                    cells.append(str(value))
        lines.append(f"| {field} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


class OneShotOptions(BaseModel):
    """The capability-gated options of a one-shot :func:`query`.

    Carries only the knobs a weak backend may not honor. ``tools``,
    ``allowed_tools``, and ``permission_mode`` need the in-process hook/permission
    machinery (``capabilities.hooks``); ``max_turns`` and ``max_thinking_tokens``
    map to their own capability flags. :func:`degrade_unsupported` returns a copy
    with the unsupported ones cleared.
    """

    tools: list[str] | None = None
    allowed_tools: list[str] | None = None
    permission_mode: PermissionMode | None = None
    max_turns: int | None = None
    max_thinking_tokens: int | None = None


def degrade_unsupported(
    options: OneShotOptions,
    capabilities: AdapterCapabilities,
    *,
    backend: Backend,
    model: str,
) -> OneShotOptions:
    """Drop one-shot options the backend cannot honor, logging each.

    The one-shot counterpart of ``core.check_settings_supported``: a single
    ``query()`` has no session the caller manages, so over-asking degrades to
    what the backend supports (with a log line) rather than raising. A tool can
    therefore express its full intent — file tools, a turn cap — and let the
    adapter layer honor what it can. Tool-using options need ``hooks`` (the
    permission machinery); the turn and thinking caps need their own flags.
    """
    kept = options.model_copy()
    dropped: list[str] = []
    if not capabilities.hooks:
        for field in ("tools", "allowed_tools", "permission_mode"):
            if getattr(kept, field) is not None:
                setattr(kept, field, None)
                dropped.append(field)
    if not capabilities.max_turns and kept.max_turns is not None:
        kept.max_turns = None
        dropped.append("max_turns")
    if not capabilities.max_thinking_tokens and kept.max_thinking_tokens is not None:
        kept.max_thinking_tokens = None
        dropped.append("max_thinking_tokens")
    if dropped:
        logger.info(
            "query() options %s are not supported on the %s backend "
            "(model=%r); proceeding without them.",
            sorted(dropped),
            backend,
            model,
        )
    return kept


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
        """Run with streaming events.

        The default runs the turn to completion and replays its blocks as
        events — the ``post_hoc`` tier of ``capabilities.streaming``.
        Engines with a live event stream override this.
        """
        response = await self.run(prompt, trace_logger=trace_logger, prefix=prefix)
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


# ---------------------------------------------------------------------------
# Unified query() — dispatches to the right adapter by model name
# ---------------------------------------------------------------------------


class OneShotRequest(BaseModel):
    """A resolved one-shot :func:`query`, after capability degradation.

    What an engine's one-shot builder needs to construct its adapter. The
    capability-gated knobs (``tools``/``permission_mode``/``max_turns``/…) have
    already been cleared by :func:`degrade_unsupported` for the chosen backend,
    so each builder can pass them through without re-checking support.
    """

    model: str
    system_prompt: str | None = None
    output_schema: JsonObject | None = None
    options: OneShotOptions = OneShotOptions()
    max_budget_usd: float | None = None


type OneShotBuilder = Callable[[OneShotRequest], AgentAdapter]
"""An engine's one-shot construction entry point: resolved request in, adapter out."""


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
    backend: Backend | None = None,
) -> LupResponse:
    """One-shot query that routes to the right SDK adapter by model name.

    For Claude models (``claude-*``, ``haiku``, ``sonnet``, ``opus``),
    uses the Claude Agent SDK. For Codex/GPT models, uses the Codex SDK.
    For everything else, uses the OpenAI-compatible adapter via Codex.
    An explicit ``backend`` bypasses the prefix inference — use it for
    aliased or gateway model ids the tables in ``lup.types`` can't know.

    Options a one-shot has no way to honor on the chosen backend (file tools
    or a turn cap on a runtime with no in-process hooks) are dropped with a log
    line rather than raising — a caller can express full intent and let the
    adapter layer keep what it can. Session-level enforcement that needs a
    managed conversation is the multi-turn adapters' job, not this path's.

    Returns a ``LupResponse`` — use ``.text`` for text or
    ``.output(MyModel)`` for structured output.
    """
    from lup.adapters.registry import backend_capabilities, one_shot_adapter

    effective_model = model or "claude-opus-4-6"
    backend = backend or model_backend(effective_model)
    capabilities = backend_capabilities(backend)

    kept = degrade_unsupported(
        OneShotOptions(
            tools=tools,
            allowed_tools=allowed_tools,
            permission_mode=permission_mode,
            max_turns=max_turns,
            max_thinking_tokens=max_thinking_tokens,
        ),
        capabilities,
        backend=backend,
        model=effective_model,
    )

    budget = max_budget_usd
    if budget is not None and capabilities.cost_reporting != "native":
        logger.info(
            "query() max_budget_usd cannot be enforced on the %s backend "
            "(model=%r): a one-shot query has no next turn to refuse, and the "
            "runtime reports tokens, not cost. Proceeding without a budget; use "
            "a multi-turn CodexAdapter(max_budget_usd=..., usage_cost=...) to "
            "enforce one.",
            backend,
            effective_model,
        )
        budget = None

    request = OneShotRequest(
        model=effective_model,
        system_prompt=system_prompt,
        output_schema=output_type.model_json_schema() if output_type else None,
        options=kept,
        max_budget_usd=budget,
    )
    adapter = one_shot_adapter(backend, request)
    return await adapter.run(prompt, trace_logger=trace_logger, prefix=prefix)
