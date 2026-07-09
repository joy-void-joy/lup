"""The Codex engine's session implementation: one thread, one opener.

``CodexSessions`` opens runtime threads over the translated native
configuration; each ``CodexSession`` turn projects through
:func:`~lup.adapters.clients.codex.messages.build_lup_response`. Pure
thread driving — the governance the runtime lacks (budget, turn timeout)
is composed over these sessions by the recipe in
:mod:`lup.adapters.clients.codex.create`.
"""

import importlib.util
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, nullcontext
from typing import TYPE_CHECKING

from lup.adapters.clients.codex.messages import build_lup_response
from lup.adapters.clients.codex.native import CodexNativeConfig
from lup.adapters.clients.codex.usage import CodexUsageNormalizer
from lup.adapters.clients.display import console_tap
from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.errors import UnsupportedOperationError
from lup.telemetry.trace import TraceLogger
from lup.types import JsonObject, LupResponse

if TYPE_CHECKING:
    import openai_codex as codex


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
    ) -> None:
        self.thread = thread
        self.id = thread.id
        self.output_schema = output_schema
        self.effort = effort
        self.usage_normalizer = usage_normalizer

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        import openai_codex.generated.v2_all as codex_items

        effort = codex_items.ReasoningEffort(self.effort) if self.effort else None
        started = time.perf_counter()
        result = await self.thread.run(
            prompt,
            effort=effort,
            output_schema=self.output_schema,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response = build_lup_response(
            result,
            output_schema=self.output_schema,
            session_id=self.thread.id,
            usage_normalizer=self.usage_normalizer,
            tap=console_tap(prefix=prefix, trace_logger=trace_logger),
        )
        if response.result is not None:
            # Wall-clock turn time, including MCP subprocess work — the
            # Codex SDK reports token usage but no duration of its own.
            response.result.duration_ms = elapsed_ms
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
            :func:`~lup.adapters.clients.codex.translate.build_codex_native`
            (the ``openai-compat`` translation appends its provider lines
            to the same shape).
    """

    def __init__(self, native: CodexNativeConfig) -> None:
        self.native = native

    def make_session(self, thread: "codex.AsyncThread") -> CodexSession:
        """Wrap a thread in a conversation carrying the native config.

        The single construction point for the send path — effort and
        output-schema wiring come off ``native``; the governance knobs
        it also carries are composed on by the create recipe, not here.
        """
        return CodexSession(
            thread,
            output_schema=self.native.output_schema,
            effort=self.native.effort,
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
