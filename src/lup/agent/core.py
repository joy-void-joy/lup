"""Main agent orchestration.

This is a TEMPLATE. Customize for your domain.

Dispatches to the appropriate SDK adapter based on ``settings.agent_sdk``.
No ``claude_agent_sdk`` imports here — all SDK-specific logic lives in
``lup.lib.adapters.*``.
"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from lup.lib.adapters.common import AgentAdapter

from lup.agent.config import settings
from lup.agent.models import AgentOutput, AgentSessionResult
from lup.lib.types import TokenUsage
from lup.lib.history import save_session
from lup.lib.metrics import get_metrics_summary, log_metrics_summary, reset_metrics
from lup.lib.notes import setup_notes
from lup.lib.trace import TraceLogger
from lup.lib.types import LupContentBlock, LupResponse, LupTextBlock, LupToolUseBlock
from lup.version import AGENT_VERSION

logger = logging.getLogger(__name__)

NOTES_PATH = Path(settings.notes_path)
TRACES_PATH = NOTES_PATH / "traces"


def extract_sources(blocks: list[LupContentBlock]) -> list[str]:
    """Extract source URLs/queries from tool use blocks."""
    sources: list[str] = []
    for block in blocks:
        if isinstance(block, LupToolUseBlock) and block.name in (
            "WebSearch",
            "WebFetch",
        ):
            if isinstance(block.input, dict):
                source = block.input.get("url") or block.input.get("query")
                if source:
                    sources.append(str(source))
    return sources


def build_result(
    *,
    session_id: str,
    task_id: str | None,
    response: LupResponse,
) -> AgentSessionResult:
    """Build an AgentSessionResult from the completed agent run."""
    result = response.result
    if result is None:
        raise RuntimeError("No result in response")

    output = AgentOutput(summary="No output produced", factors=[], confidence=0.5)
    if result.structured_output:
        output = AgentOutput.model_validate(result.structured_output)

    return AgentSessionResult(
        session_id=session_id,
        task_id=task_id,
        agent_version=AGENT_VERSION,
        timestamp=datetime.now().isoformat(),
        output=output,
        reasoning="".join(
            b.text for b in response.blocks if isinstance(b, LupTextBlock)
        ),
        sources_consulted=extract_sources(response.blocks),
        duration_seconds=(result.duration_ms / 1000) if result.duration_ms else None,
        cost_usd=result.total_cost_usd,
        token_usage=cast(TokenUsage, result.usage) if result.usage else None,
        tool_metrics=get_metrics_summary(),
    )


def build_adapter(
    session_id: str,
    task_id: str | None = None,
) -> tuple[AgentAdapter, AbstractContextManager[object]]:
    """Build the appropriate adapter for ``settings.agent_sdk``.

    Returns (adapter, context_manager) — the caller enters the context
    (e.g. sandbox lifecycle) around the adapter run.
    """
    notes = setup_notes(session_id, task_id or "0")

    match settings.agent_sdk:
        case "claude":
            from lup.lib.adapters.claude import ClaudeAdapter, build_options
            from lup.lib.sandbox import Sandbox

            sb = Sandbox(
                session_id=session_id,
                shared_dir=notes.session / "sandbox_shared",
                timeout_seconds=settings.sandbox_timeout_seconds,
            )
            options = build_options(notes, sandbox=sb)
            adapter: AgentAdapter = ClaudeAdapter(options)
            return adapter, sb

        case "codex":
            from lup.lib.adapters.codex import build_codex_adapter

            return build_codex_adapter(notes), nullcontext()


async def run_agent(
    task: str,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
) -> AgentSessionResult:
    """Run the agent on a task.

    Dispatches to the Claude or Codex adapter based on
    ``settings.agent_sdk``.
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("Starting session %s (sdk=%s)", session_id, settings.agent_sdk)
    reset_metrics()

    trace_path = TRACES_PATH / session_id / f"{datetime.now().strftime('%H%M%S')}.md"
    trace_logger = TraceLogger(trace_path=trace_path, title=f"Session {session_id}")

    adapter, ctx = build_adapter(session_id, task_id)

    with ctx:
        response = await adapter.run(task, trace_logger=trace_logger)

    trace_logger.save()
    log_metrics_summary()

    session_result = build_result(
        session_id=session_id,
        task_id=task_id,
        response=response,
    )

    save_session(session_result, session_id=session_result.session_id)

    return session_result
