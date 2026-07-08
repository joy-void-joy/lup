"""The Codex engine's run path: ``create_codex``, sessions, and the client.

Construction refuses through the shared consume-tracking seam
(:mod:`lup.adapters.clients.refusal`); the run path projects each
completed turn through
:func:`~lup.adapters.clients.codex.messages.build_lup_response` and
enforces the budget and turn-timeout knobs the runtime itself cannot.
"""

import asyncio
import importlib.util
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import AbstractContextManager, asynccontextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING

from lup.adapters.clients.Client import Client, Session
from lup.adapters.clients.codex.config import (
    CodexHookConfig,
    build_hook_config_overrides,
    build_mcp_config_overrides,
    build_sandbox_config_overrides,
)
from lup.adapters.clients.codex.messages import build_lup_response
from lup.adapters.clients.codex.options import (
    budget_if_priced,
    codex_effort,
    subprocess_sandbox_cleanup,
)
from lup.adapters.clients.codex.usage import CodexUsageNormalizer
from lup.adapters.clients.fallbacks import query_via_session, replay_stream
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.errors import (
    BudgetExceededError,
    TurnTimeoutError,
    UnsupportedOperationError,
)
from lup.adapters.options import LupAgentOptions
from lup.realtime.relay import RealtimeMailbox
from lup.telemetry.trace import TraceLogger
from lup.types import JsonObject, LupEvent, LupResponse, Usage, UsageCost

if TYPE_CHECKING:
    import openai_codex as codex
    import openai_codex.generated.v2_all as codex_items


def build_codex_client(opts: LupAgentOptions) -> "CodexClient":
    """Translate neutral options into a configured :class:`CodexClient`.

    Reads the knobs the runtime honors — ``reasoning_effort``,
    ``turn_timeout_seconds``, and ``max_budget_usd`` (only when priced by
    ``usage_cost``) — and leaves ``max_turns``/``max_thinking_tokens``/
    ``permission_mode``/``tools`` unread, which is how they come to be
    refused: the runtime has no per-session turn cap, thinking budget,
    permission mode, or builtin-toolset restriction.
    """
    return CodexClient(
        model=opts.model,
        system_prompt=opts.system_prompt,
        output_schema=opts.output_schema,
        sandbox=opts.codex_sandbox,
        effort=opts.reasoning_effort,
        approval_policy=opts.approval_policy,
        mcp_tools=bool(opts.served_tool_groups),
        mcp_env=dict(opts.mcp_env),
        writable_roots=list(opts.writable_roots),
        mcp_servers=opts.served_tool_groups,
        max_budget_usd=budget_if_priced(opts),
        usage_cost=opts.usage_cost,
        turn_timeout_seconds=opts.turn_timeout_seconds,
        cleanup=subprocess_sandbox_cleanup(opts),
    )


def create_codex(options: LupAgentOptions) -> Client:
    """Build a Codex-runtime client from neutral options.

    Consumes the subprocess mechanism payloads (served tool groups, env
    relay, writable roots) and ignores the in-process ones (hooks, tool
    servers — enforcement here is the runtime's native sandbox) and the
    Claude-only ``coding_harness_preset``/``sdk_sandbox`` shape flags. Subagent
    specs are served through the ``run_subagent`` tool group rather than
    run natively. Persistent mode surfaces the file-relay mailbox.
    """
    client = refuse_unconsumed("codex", options, build_codex_client)
    if options.realtime and options.realtime_dir is not None:
        client.mailbox = RealtimeMailbox(options.realtime_dir)
    return client


def require_codex_sdk() -> None:
    """Raise a clear error if the Codex SDK is not installed."""
    if importlib.util.find_spec("openai_codex") is None:
        raise ImportError("Codex SDK not installed. Install with: uv add openai-codex")


class CodexSession(Session):
    """Multi-turn conversation via a Codex thread."""

    def __init__(
        self,
        thread: "codex.AsyncThread",
        *,
        output_schema: JsonObject | None = None,
        effort: str | None = None,
        usage_normalizer: CodexUsageNormalizer | None = None,
        max_budget_usd: float | None = None,
        usage_cost: UsageCost | None = None,
        turn_timeout_seconds: float | None = None,
    ) -> None:
        self.thread = thread
        self.id = thread.id
        self.output_schema = output_schema
        self.effort = effort
        self.usage_normalizer = usage_normalizer
        self.max_budget_usd = max_budget_usd
        self.usage_cost = usage_cost
        self.turn_timeout_seconds = turn_timeout_seconds
        self.turns_usage = Usage()
        self.cost_usd: float | None = None

    def check_budget(self) -> None:
        """Refuse to start a turn once accumulated cost reached the budget.

        Codex turns are atomic from the caller's side, so enforcement is
        between turns: the turn that crosses the budget completes, and
        every turn after it raises.
        """
        if self.max_budget_usd is None or self.cost_usd is None:
            return
        if self.cost_usd >= self.max_budget_usd:
            raise BudgetExceededError(
                f"Session cost ${self.cost_usd:.4f} reached the "
                f"${self.max_budget_usd:.2f} budget; refusing to start a turn."
            )

    def record_turn_usage(self, usage: "codex_items.ThreadTokenUsage | None") -> None:
        """Accumulate one turn's token usage and re-estimate session cost."""
        if usage is None:
            return
        last = usage.last
        self.turns_usage = Usage(
            input_tokens=self.turns_usage.input_tokens + last.input_tokens,
            output_tokens=self.turns_usage.output_tokens + last.output_tokens,
            cache_read_input_tokens=(
                self.turns_usage.cache_read_input_tokens + last.cached_input_tokens
            ),
        )
        if self.usage_cost is not None:
            self.cost_usd = self.usage_cost(self.turns_usage)

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        import openai_codex.generated.v2_all as codex_items

        self.check_budget()
        mapped_effort = codex_effort(self.effort)
        effort = codex_items.ReasoningEffort(mapped_effort) if mapped_effort else None
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.turn_timeout_seconds):
                result = await self.thread.run(
                    prompt,
                    effort=effort,
                    output_schema=self.output_schema,
                )
        except TimeoutError as exc:
            raise TurnTimeoutError(
                f"Codex turn exceeded the {self.turn_timeout_seconds}s "
                "wall-clock timeout and was cancelled client-side; close "
                "the conversation rather than reusing this thread."
            ) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000
        response = build_lup_response(
            result,
            output_schema=self.output_schema,
            session_id=self.thread.id,
            trace_logger=trace_logger,
            prefix=prefix,
            usage_normalizer=self.usage_normalizer,
        )
        self.record_turn_usage(result.usage)
        if response.result is not None:
            # Wall-clock turn time, including MCP subprocess work — the
            # Codex SDK reports token usage but no duration of its own.
            response.result.duration_ms = elapsed_ms
            if self.cost_usd is not None:
                response.result.total_cost_usd = self.cost_usd
        return response

    async def interrupt(self) -> None:
        raise UnsupportedOperationError(
            "the codex runtime has no client-side interrupt; cap a runaway "
            "turn with turn_timeout_seconds instead."
        )


class CodexClient(Client):
    """Run prompts via the OpenAI Codex SDK."""

    model_provider: str | None = None
    """Codex model-provider selector — set by the OpenAI-compatible
    subclass; ``None`` runs on the account's default provider."""

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str,
        output_schema: JsonObject | None = None,
        sandbox: str | None = None,
        effort: str | None = None,
        approval_policy: str | None = None,
        mcp_tools: bool = True,
        mcp_env: dict[str, str] | None = None,
        writable_roots: list[Path] | None = None,
        hook_overrides: list[CodexHookConfig] | None = None,
        usage_normalizer: CodexUsageNormalizer | None = None,
        mcp_servers: Sequence[str] = ("notes", "sandbox"),
        max_budget_usd: float | None = None,
        usage_cost: UsageCost | None = None,
        turn_timeout_seconds: float | None = None,
        cleanup: AbstractContextManager[object] | None = None,
    ) -> None:
        if max_budget_usd is not None and usage_cost is None:
            raise ValueError(
                "max_budget_usd on the Codex runtime requires a usage_cost "
                "estimator — the SDK reports token counts, not cost. Build "
                "one with per_mtok_usage_cost(...)."
            )
        self.model = model
        self.system_prompt = system_prompt
        self.output_schema = output_schema
        self.sandbox = sandbox
        self.effort = effort
        self.approval_policy = approval_policy
        self.mcp_tools = mcp_tools
        self.mcp_env = mcp_env
        self.writable_roots = writable_roots
        self.hook_overrides = hook_overrides
        self.usage_normalizer = usage_normalizer
        self.mcp_servers = mcp_servers
        self.max_budget_usd = max_budget_usd
        self.usage_cost = usage_cost
        self.turn_timeout_seconds = turn_timeout_seconds
        self.cleanup = cleanup

    def build_config_overrides(self) -> list[str]:
        """Assemble all config_overrides for this adapter run."""
        overrides: list[str] = []
        if self.mcp_tools:
            overrides.extend(
                build_mcp_config_overrides(env=self.mcp_env, servers=self.mcp_servers)
            )
        if self.writable_roots:
            overrides.extend(build_sandbox_config_overrides(self.writable_roots))
        if self.hook_overrides:
            overrides.extend(build_hook_config_overrides(self.hook_overrides))
        return overrides

    def make_session(self, thread: "codex.AsyncThread") -> CodexSession:
        """Wrap a thread in a conversation carrying this client's settings.

        The single construction point for the send path, shared with the
        OpenAI-compatible subclass so both inherit identical effort,
        output-schema, and budget wiring.
        """
        return CodexSession(
            thread,
            output_schema=self.output_schema,
            effort=self.effort,
            usage_normalizer=self.usage_normalizer,
            max_budget_usd=self.max_budget_usd,
            usage_cost=self.usage_cost,
            turn_timeout_seconds=self.turn_timeout_seconds,
        )

    def codex_config(self) -> "codex.CodexConfig":
        """Assemble the runtime config — the compat subclass adds provider env."""
        import openai_codex as codex

        return codex.CodexConfig(config_overrides=tuple(self.build_config_overrides()))

    async def open_thread(
        self, codex_client: "codex.AsyncCodex", *, resume: str | None
    ) -> "codex.AsyncThread":
        """Start the session's thread, or restore a saved one."""
        import openai_codex as codex

        sandbox = codex.Sandbox(self.sandbox) if self.sandbox else None
        approval_mode = (
            codex.ApprovalMode(self.approval_policy)
            if self.approval_policy
            else codex.ApprovalMode.auto_review
        )
        if resume is not None:
            return await codex_client.thread_resume(
                resume,
                model=self.model,
                model_provider=self.model_provider,
                developer_instructions=self.system_prompt,
                sandbox=sandbox,
                approval_mode=approval_mode,
            )
        return await codex_client.thread_start(
            model=self.model,
            model_provider=self.model_provider,
            developer_instructions=self.system_prompt,
            sandbox=sandbox,
            approval_mode=approval_mode,
        )

    @asynccontextmanager
    async def session(
        self, *, resume: str | None = None
    ) -> AsyncGenerator[Session, None]:
        require_codex_sdk()

        import openai_codex as codex

        with self.cleanup if self.cleanup is not None else nullcontext():
            async with codex.AsyncCodex(config=self.codex_config()) as codex_client:
                thread = await self.open_thread(codex_client, resume=resume)
                yield self.make_session(thread)

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

    def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        return replay_stream(self, prompt, trace_logger=trace_logger, prefix=prefix)
