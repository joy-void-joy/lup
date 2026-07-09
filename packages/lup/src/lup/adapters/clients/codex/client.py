"""The Codex engine's run path: ``create_codex``, sessions, composition.

Construction refuses through the shared consume-tracking seam
(:mod:`lup.adapters.clients.refusal`) over the translation in
:mod:`lup.adapters.clients.codex.options`, then composes
:class:`CodexSessions` — the runtime's one native component — into the
one client shape (the runtime reports a turn only once complete, so the
stream slot is filled by replay); the run path projects each completed
turn through :func:`~lup.adapters.clients.codex.messages.build_lup_response`
and enforces the budget and turn-timeout knobs the runtime itself cannot.
"""

import asyncio
import importlib.util
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, nullcontext
from typing import TYPE_CHECKING

from lup.adapters.clients.Client import Client
from lup.adapters.clients.codex.messages import build_lup_response
from lup.adapters.clients.codex.options import (
    CodexNativeConfig,
    build_codex_native,
    codex_effort,
)
from lup.adapters.clients.codex.usage import CodexUsageNormalizer
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.clients.refusal import refuse_unconsumed
from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.errors import (
    BudgetExceededError,
    TurnTimeoutError,
    UnsupportedOperationError,
)
from lup.adapters.options import LupAgentOptions
from lup.realtime.relay import RealtimeMailbox
from lup.telemetry.trace import TraceLogger
from lup.types import JsonObject, LupResponse, Usage, UsageCost

if TYPE_CHECKING:
    import openai_codex as codex
    import openai_codex.generated.v2_all as codex_items


def create_codex(options: LupAgentOptions) -> Client:
    """Build a Codex-runtime client from neutral options.

    Consumes the subprocess mechanism payloads (served tool groups, env
    relay, writable roots) and ignores the in-process ones (hooks, tool
    servers — enforcement here is the runtime's native sandbox) and the
    Claude-only ``coding_harness_preset``/``sdk_sandbox`` shape flags. Subagent
    specs are served through the ``run_subagent`` tool group rather than
    run natively. Persistent mode surfaces the file-relay mailbox.
    """
    client = compose_codex(refuse_unconsumed("codex", options, build_codex_native))
    if options.realtime and options.realtime_dir is not None:
        client.mailbox = RealtimeMailbox(options.realtime_dir)
    return client


def compose_codex(native: CodexNativeConfig) -> ComposedClient:
    """Compose the Codex runtime's components into the one client shape.

    Codex contributes only its sessions — the runtime reports a turn only
    once complete, so the stream slot is left to the replay gap-filler.
    ``openai-compat`` reuses this composition over its own translation.
    """
    return ComposedClient(CodexSessions(native))


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


class CodexSessions(Sessions):
    """Opens Codex-runtime sessions.

    Args:
        native: Translated native configuration built by
            :func:`~lup.adapters.clients.codex.options.build_codex_native`
            (the ``openai-compat`` translation appends its provider lines
            to the same shape).
    """

    def __init__(self, native: CodexNativeConfig) -> None:
        self.native = native

    def make_session(self, thread: "codex.AsyncThread") -> CodexSession:
        """Wrap a thread in a conversation carrying the native config.

        The single construction point for the send path — effort,
        output-schema, and budget wiring all come off ``native``.
        """
        return CodexSession(
            thread,
            output_schema=self.native.output_schema,
            effort=self.native.effort,
            max_budget_usd=self.native.max_budget_usd,
            usage_cost=self.native.usage_cost,
            turn_timeout_seconds=self.native.turn_timeout_seconds,
        )

    def codex_config(self) -> "codex.CodexConfig":
        """The runtime config — overrides and env were rendered at translation."""
        import openai_codex as codex

        return codex.CodexConfig(
            config_overrides=tuple(self.native.config_overrides),
            env=self.native.env or None,
        )

    async def open_thread(
        self, codex_client: "codex.AsyncCodex", *, resume: str | None
    ) -> "codex.AsyncThread":
        """Start the session's thread, or restore a saved one."""
        import openai_codex as codex

        native = self.native
        sandbox = codex.Sandbox(native.sandbox) if native.sandbox else None
        approval_mode = (
            codex.ApprovalMode(native.approval_policy)
            if native.approval_policy
            else codex.ApprovalMode.auto_review
        )
        if resume is not None:
            return await codex_client.thread_resume(
                resume,
                model=native.model,
                model_provider=native.model_provider,
                developer_instructions=native.system_prompt,
                sandbox=sandbox,
                approval_mode=approval_mode,
            )
        return await codex_client.thread_start(
            model=native.model,
            model_provider=native.model_provider,
            developer_instructions=native.system_prompt,
            sandbox=sandbox,
            approval_mode=approval_mode,
        )

    @asynccontextmanager
    async def open(self, *, resume: str | None = None) -> AsyncGenerator[Session, None]:
        require_codex_sdk()

        import openai_codex as codex

        cleanup = self.native.cleanup
        with cleanup() if cleanup is not None else nullcontext():
            async with codex.AsyncCodex(config=self.codex_config()) as codex_client:
                thread = await self.open_thread(codex_client, resume=resume)
                yield self.make_session(thread)
