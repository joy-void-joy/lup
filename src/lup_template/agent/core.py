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

    from lup.adapters.codex import CodexHookConfig
    from lup.adapters.common import AgentAdapter
    from lup.notes import NotesConfig
    from lup.types import SubagentSpec

from lup_template.agent.config import settings
from lup_template.agent.models import AgentOutput, AgentSessionResult
from lup.history import save_session
from lup.metrics import get_metrics_summary, log_metrics_summary, reset_metrics
from lup.notes import setup_notes
from lup.trace import TraceLogger
from lup.types import LupContentBlock, LupResponse, LupTextBlock, LupToolUseBlock
from lup.paths import agent_version

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
        permission_mode="bypassPermissions",
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
        effort=cast("EffortLevel | None", settings.reasoning_effort),
    )


def format_subagent_prompt_section(specs: list["SubagentSpec"]) -> str:
    """Format subagent specs as a system prompt section for non-Claude adapters."""
    if not specs:
        return ""
    lines = ["\n\n## Available Subagent Roles\n"]
    for spec in specs:
        lines.append(f"### {spec.name}\n{spec.description}\n")
    return "\n".join(lines)


def build_codex_session(
    notes: "NotesConfig",
) -> tuple[str, list["CodexHookConfig"], dict[str, str]]:
    """Shared scaffolding for Codex-runtime adapters.

    Returns (system_prompt, hook_configs, mcp_env). The reflection gate
    is enforced inside submit_output — the serve-tools subprocess reads
    the same flag path from the relayed env — so structured output and
    gating behave identically to the Claude path. The generated
    PreToolUse hook script is optional hardening on top.
    """
    import tempfile

    from lup.adapters.codex_hooks import lup_hooks_to_codex
    from lup.hooks import create_permission_hooks, create_reflection_gate
    from lup.paths import SessionContext
    from lup.reflect import ReflectionGate
    from lup.types import merge_hooks

    from lup_template.agent.prompts import get_system_prompt
    from lup_template.agent.subagents import get_subagent_specs

    script_dir = Path(tempfile.mkdtemp(prefix="lup_codex_hooks_"))
    gate_flag_path = script_dir / "reflection_gate_flag"
    gate = ReflectionGate(flag_path=gate_flag_path)

    permission_hooks = create_permission_hooks(notes.rw, notes.ro)
    gate_hooks = create_reflection_gate(
        gate=gate,
        gated_tool="mcp__notes__submit_output",
        reflection_tool_name="mcp__notes__review",
    )
    lup_hooks = merge_hooks(permission_hooks, gate_hooks)

    hook_configs = lup_hooks_to_codex(
        lup_hooks,
        script_dir=script_dir,
        rw_dirs=notes.rw,
        ro_dirs=notes.ro,
        gate_flag_path=gate_flag_path,
    )

    context = SessionContext(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
        gate_flag=gate_flag_path,
        session_id=notes.session.name,
        task_id=notes.output.parent.name,
    )

    system_prompt = get_system_prompt()
    system_prompt += format_subagent_prompt_section(get_subagent_specs())

    return system_prompt, hook_configs, context.to_env()


def build_codex_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build a CodexAdapter for the agent session."""
    from lup.adapters.codex import CodexAdapter

    system_prompt, hook_configs, mcp_env = build_codex_session(notes)

    return CodexAdapter(
        model=settings.model,
        system_prompt=system_prompt,
        sandbox=settings.codex_sandbox,
        effort=settings.codex_effort or settings.reasoning_effort,
        approval_policy=settings.codex_approval_policy,
        mcp_tools=True,
        mcp_env=mcp_env,
        hook_overrides=hook_configs,
    )


def build_openai_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build an OpenAICompatibleAdapter with full hooks and tools."""
    from lup.adapters.openai_compat import OpenAICompatibleAdapter

    system_prompt, hook_configs, mcp_env = build_codex_session(notes)

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
        hook_overrides=hook_configs,
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
            return build_codex_adapter(notes), nullcontext(), notes

        case "openai":
            return build_openai_adapter(notes), nullcontext(), notes


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

    trace_path = TRACES_PATH / session_id / f"{datetime.now().strftime('%H%M%S')}.md"
    trace_logger = TraceLogger(trace_path=trace_path, title=f"Session {session_id}")

    adapter, ctx, notes = build_adapter(session_id, task_id)

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
