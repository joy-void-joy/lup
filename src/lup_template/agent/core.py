"""Main agent orchestration.

This is a TEMPLATE. Customize for your domain.

Dispatches to the appropriate SDK adapter based on ``settings.agent_sdk``.
SDK-specific imports are deferred (inline or TYPE_CHECKING) so the
module loads without requiring any particular SDK to be installed.
"""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions
    from claude_agent_sdk.types import EffortLevel

    from lup.adapters.common import AgentAdapter
    from lup.notes import NotesConfig

from lup_template.agent.config import settings
from lup_template.agent.models import AgentOutput, AgentSessionResult
from lup.history import save_session
from lup.metrics import get_metrics_summary, log_metrics_summary, reset_metrics
from lup.notes import setup_notes
from lup.trace import TraceLogger
from lup.types import LupContentBlock, LupResponse, LupTextBlock, LupToolUseBlock
from lup.paths import agent_version

logger = logging.getLogger(__name__)


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
    session_dir: Path,
) -> AgentSessionResult:
    """Build an AgentSessionResult from the completed agent run.

    The output is what the agent submitted via the submit_output tool
    (``session_dir/output.json``) — the single finalization mechanism
    on every backend. Tool metrics come from the session's flushed
    metrics file when tools ran in a subprocess (Codex/OpenAI paths),
    falling back to the in-process collector (Claude path).
    """
    from lup.metrics import read_metrics_summary
    from lup.output import read_output

    result = response.result
    if result is None:
        raise RuntimeError("No result in response")

    output = read_output(session_dir, AgentOutput)
    if output is None:
        logger.error("Session %s finished without submitting output", session_id)
        output = AgentOutput(summary="No output produced", factors=[], confidence=0.5)

    return AgentSessionResult(
        session_id=session_id,
        task_id=task_id,
        agent_version=agent_version(),
        timestamp=datetime.now().isoformat(),
        output=output,
        reasoning="".join(
            b.text for b in response.blocks if isinstance(b, LupTextBlock)
        ),
        sources_consulted=extract_sources(response.blocks),
        duration_seconds=(result.duration_ms / 1000) if result.duration_ms else None,
        cost_usd=result.total_cost_usd,
        token_usage=result.usage,
        tool_metrics=read_metrics_summary(session_dir) or get_metrics_summary(),
    )


def build_options(
    notes: "NotesConfig",
    *,
    sandbox: object | None = None,
) -> "ClaudeAgentOptions":
    """Build ClaudeAgentOptions for the agent session.

    Composes system prompt, MCP servers, hooks, subagents, and
    model settings into a single options object.

    Args:
        notes: Session notes config.
        sandbox: Optional Sandbox instance for sandboxed execution.

    Returns:
        Configured ClaudeAgentOptions.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    from lup.adapters.claude import (
        lup_hooks_to_claude,
        lup_server_to_claude,
        spec_to_claude,
    )
    from lup.hooks import create_permission_hooks
    from lup.mcp import create_mcp_server
    from lup.output import create_output_tool
    from lup.types import merge_hooks

    from lup_template.agent.prompts import get_system_prompt
    from lup_template.agent.subagents import get_subagent_specs
    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.tools.reflect import create_reflect_tools

    reflect_kit = create_reflect_tools(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
    )

    output_kit = create_output_tool(
        AgentOutput,
        session_dir=notes.session,
        gate=reflect_kit["gate"],
        reflection_tool_name="mcp__notes__review",
    )

    reflect_server = create_mcp_server(
        name="notes",
        tools=[*reflect_kit["tools"], *output_kit["tools"]],
    )

    all_servers = [reflect_server]
    if sandbox is not None:
        from lup.sandbox import Sandbox

        if isinstance(sandbox, Sandbox):
            all_servers.append(sandbox.create_mcp_server())

    policy = ToolPolicy.from_settings(settings)
    policy_servers = policy.get_mcp_servers(*all_servers)

    system_prompt = get_system_prompt()

    hooks = create_permission_hooks(
        rw_dirs=notes.rw,
        ro_dirs=notes.ro,
    )

    from lup.hooks import create_completion_guard, create_reflection_gate

    reflection_hooks = create_reflection_gate(
        gate=reflect_kit["gate"],
        gated_tool="mcp__notes__submit_output",
        reflection_tool_name="mcp__notes__review",
    )
    hooks = merge_hooks(hooks, reflection_hooks)

    completion_hooks = create_completion_guard(output_kit["output_path"].exists)
    hooks = merge_hooks(hooks, completion_hooks)

    claude_hooks = lup_hooks_to_claude(hooks)

    mcp_servers = {
        name: lup_server_to_claude(server) if hasattr(server, "server") else server
        for name, server in policy_servers.items()
    }

    subagent_specs = get_subagent_specs()
    subagents = {spec.name: spec_to_claude(spec) for spec in subagent_specs}

    return ClaudeAgentOptions(
        model=settings.model,
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": system_prompt,
        },
        # ThinkingConfigEnabled(budget_tokens=N) is the newer alternative, but
        # max_thinking_tokens is simpler and avoids adaptive mode's variable allocation.
        max_thinking_tokens=settings.max_thinking_tokens or (128_000 - 1),
        permission_mode=settings.permission_mode,
        extra_args={"no-session-persistence": None},
        hooks=claude_hooks,
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
        },
        mcp_servers=mcp_servers,
        agents=subagents,
        add_dirs=[str(d) for d in notes.all_dirs],
        allowed_tools=policy.get_allowed_tools(),
        max_turns=settings.max_turns,
        max_budget_usd=settings.max_budget_usd,
        effort=cast("EffortLevel | None", settings.reasoning_effort),
    )


def build_codex_session(
    notes: "NotesConfig",
) -> tuple[str, dict[str, str], list[Path]]:
    """Shared scaffolding for Codex-runtime adapters.

    Returns (system_prompt, mcp_env, writable_roots). Enforcement on
    Codex is native and in-tool: the runtime's workspace-write sandbox
    confines writes to ``writable_roots``, and the reflection gate is
    checked inside submit_output (the serve-tools subprocess reads the
    flag path from the relayed env). Codex config.toml command hooks
    are not wired — a live probe showed they never fire on current
    codex builds.
    """
    import tempfile

    from lup.paths import SessionContext

    from lup_template.agent.prompts import get_system_prompt

    if settings.max_turns is not None or settings.max_budget_usd is not None:
        raise ValueError(
            "AGENT_MAX_TURNS / AGENT_MAX_BUDGET_USD are not supported on "
            f"the {settings.agent_sdk} backend; unset them or use "
            "AGENT_SDK=claude."
        )

    state_dir = Path(tempfile.mkdtemp(prefix="lup_codex_session_"))
    gate_flag_path = state_dir / "reflection_gate_flag"

    context = SessionContext(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
        gate_flag=gate_flag_path,
        session_id=notes.session.name,
        task_id=notes.output.parent.name,
    )

    return get_system_prompt(), context.to_env(), list(notes.rw)


def build_codex_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build a CodexAdapter for the agent session."""
    from lup.adapters.codex import CodexAdapter

    system_prompt, mcp_env, writable_roots = build_codex_session(notes)

    return CodexAdapter(
        model=settings.model,
        system_prompt=system_prompt,
        sandbox=settings.codex_sandbox,
        effort=settings.codex_effort or settings.reasoning_effort,
        approval_policy=settings.codex_approval_policy,
        mcp_tools=True,
        mcp_env=mcp_env,
        writable_roots=writable_roots,
    )


def build_openai_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build an OpenAICompatibleAdapter with full tools and enforcement."""
    from lup.adapters.openai_compat import OpenAICompatibleAdapter

    system_prompt, mcp_env, writable_roots = build_codex_session(notes)

    return OpenAICompatibleAdapter(
        model=settings.model,
        system_prompt=system_prompt,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model_provider=settings.openai_model_provider,
        sandbox=settings.codex_sandbox,
        effort=settings.codex_effort or settings.reasoning_effort,
        approval_policy=settings.codex_approval_policy,
        mcp_tools=True,
        mcp_env=mcp_env,
        writable_roots=writable_roots,
    )


def subprocess_sandbox_cleanup(
    notes: "NotesConfig",
) -> AbstractContextManager[object]:
    """Session context guaranteeing subprocess sandbox containers die.

    The Codex/OpenAI tool subprocess may be killed without running its
    own cleanup; the parent removes the session's container on exit.
    No-op when the docker extra is not installed.
    """
    try:
        from lup.sandbox import sandbox_cleanup
    except ImportError:
        return nullcontext()
    return sandbox_cleanup(
        session_id=notes.session.name,
        shared_dir=notes.session / "sandbox_shared",
    )


def build_adapter(
    session_id: str,
    task_id: str | None = None,
) -> tuple[AgentAdapter, AbstractContextManager[object], NotesConfig]:
    """Build the appropriate adapter for ``settings.agent_sdk``.

    Returns (adapter, context_manager, notes) — the caller enters the
    context (e.g. sandbox lifecycle) around the adapter run and reads
    session artifacts from the notes config.
    """
    notes = setup_notes(session_id, task_id or "0")

    match settings.agent_sdk:
        case "claude":
            from lup.adapters.claude import ClaudeAdapter
            from lup.sandbox import Sandbox

            sb = Sandbox(
                session_id=session_id,
                shared_dir=notes.session / "sandbox_shared",
                timeout_seconds=settings.sandbox_timeout_seconds,
            )
            options = build_options(notes, sandbox=sb)
            adapter: AgentAdapter = ClaudeAdapter(options)
            return adapter, sb, notes

        case "codex":
            return build_codex_adapter(notes), subprocess_sandbox_cleanup(notes), notes

        case "openai":
            return (
                build_openai_adapter(notes),
                subprocess_sandbox_cleanup(notes),
                notes,
            )


async def run_agent(
    task: str,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
) -> AgentSessionResult:
    """Run the agent on a task.

    Dispatches to the Claude, Codex, or OpenAI adapter based on
    ``settings.agent_sdk``.
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("Starting session %s (sdk=%s)", session_id, settings.agent_sdk)
    reset_metrics()

    adapter, ctx, notes = build_adapter(session_id, task_id)

    trace_logger = TraceLogger(
        trace_path=notes.trace_log, title=f"Session {session_id}"
    )

    with ctx:
        response = await adapter.run(task, trace_logger=trace_logger)

    trace_logger.save()
    log_metrics_summary()

    session_result = build_result(
        session_id=session_id,
        task_id=task_id,
        response=response,
        session_dir=notes.session,
    )

    save_session(session_result, session_id=session_result.session_id)

    return session_result
