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
    from lup.types import SubagentSpec

from lup_template.agent.config import settings
from lup_template.agent.models import AgentOutput, AgentSessionResult
from lup.types import TokenUsage
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
        agent_version=agent_version(),
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

    from lup.adapters.claude import lup_hooks_to_claude, lup_server_to_claude, spec_to_claude
    from lup.hooks import create_permission_hooks
    from lup.mcp import create_mcp_server
    from lup.types import merge_hooks

    from lup_template.agent.prompts import get_system_prompt
    from lup_template.agent.subagents import get_subagent_specs
    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.tools.reflect import create_reflect_tools

    reflect_kit = create_reflect_tools(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
    )

    reflect_server = create_mcp_server(
        name="notes",
        tools=reflect_kit["tools"],
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

    from lup.hooks import create_reflection_gate

    reflection_hooks = create_reflection_gate(
        gate=reflect_kit["gate"],
        gated_tool="StructuredOutput",
    )
    hooks = merge_hooks(hooks, reflection_hooks)

    claude_hooks = lup_hooks_to_claude(hooks)

    mcp_servers = {
        name: lup_server_to_claude(server)
        if hasattr(server, "server")
        else server
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
        output_format={
            "type": "json_schema",
            "schema": AgentOutput.model_json_schema(),
        },
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


def build_codex_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build a CodexAdapter for the agent session.

    Args:
        notes: Session notes config.

    Returns:
        Configured CodexAdapter.
    """
    import tempfile

    from lup.adapters.codex import CodexAdapter
    from lup.adapters.codex_hooks import lup_hooks_to_codex
    from lup.hooks import create_permission_hooks, create_reflection_gate
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
        gated_tool="StructuredOutput",
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

    system_prompt = get_system_prompt()
    subagent_specs = get_subagent_specs()
    system_prompt += format_subagent_prompt_section(subagent_specs)

    return CodexAdapter(
        model=settings.model,
        system_prompt=system_prompt,
        output_schema=AgentOutput.model_json_schema(),
        sandbox=settings.codex_sandbox,
        effort=settings.codex_effort or settings.reasoning_effort,
        approval_policy=settings.codex_approval_policy,
        mcp_tools=True,
        hook_overrides=hook_configs,
    )


def build_openai_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build an OpenAICompatibleAdapter with full hooks and tools.

    Reuses the same hook scaffolding as the Codex path (file-backed
    gate, permission scripts) since OpenAICompatibleAdapter extends
    CodexAdapter.
    """
    import tempfile

    from lup.adapters.codex_hooks import lup_hooks_to_codex
    from lup.adapters.openai_compat import OpenAICompatibleAdapter
    from lup.hooks import create_permission_hooks, create_reflection_gate
    from lup.reflect import ReflectionGate
    from lup.types import merge_hooks

    from lup_template.agent.prompts import get_system_prompt
    from lup_template.agent.subagents import get_subagent_specs

    script_dir = Path(tempfile.mkdtemp(prefix="lup_openai_hooks_"))
    gate_flag_path = script_dir / "reflection_gate_flag"
    gate = ReflectionGate(flag_path=gate_flag_path)

    permission_hooks = create_permission_hooks(notes.rw, notes.ro)
    gate_hooks = create_reflection_gate(
        gate=gate,
        gated_tool="StructuredOutput",
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

    system_prompt = get_system_prompt()
    subagent_specs = get_subagent_specs()
    system_prompt += format_subagent_prompt_section(subagent_specs)

    return OpenAICompatibleAdapter(
        model=settings.model,
        system_prompt=system_prompt,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model_provider=settings.openai_model_provider,
        output_schema=AgentOutput.model_json_schema(),
        sandbox=settings.codex_sandbox,
        effort=settings.codex_effort or settings.reasoning_effort,
        approval_policy=settings.codex_approval_policy,
        mcp_tools=True,
        hook_overrides=hook_configs,
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
            from lup.adapters.claude import ClaudeAdapter
            from lup.sandbox import Sandbox

            sb = Sandbox(
                session_id=session_id,
                shared_dir=notes.session / "sandbox_shared",
                timeout_seconds=settings.sandbox_timeout_seconds,
            )
            options = build_options(notes, sandbox=sb)
            adapter: AgentAdapter = ClaudeAdapter(options)
            return adapter, sb

        case "codex":
            return build_codex_adapter(notes), nullcontext()

        case "openai":
            return build_openai_adapter(notes), nullcontext()


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
