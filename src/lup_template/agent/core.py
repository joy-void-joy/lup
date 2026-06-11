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

    from lup.adapters.codex import UsageCost
    from lup.adapters.common import AgentAdapter
    from lup.notes import NotesConfig
    from lup.realtime_relay import RealtimeMailbox
    from lup.sandbox import Sandbox

from lup_template.agent.config import settings
from lup_template.agent.models import AgentOutput, AgentSessionResult
from lup.adapters.common import AdapterCapabilities
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
        output = AgentOutput.empty()

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
    from lup.types import merge_hooks

    from lup_template.agent.prompts import get_system_prompt
    from lup_template.agent.subagents import get_subagent_specs
    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.toolsets import EXAMPLE_GROUP, build_session_toolset

    session_sandbox: Sandbox | None = None
    if sandbox is not None:
        from lup.sandbox import Sandbox

        if isinstance(sandbox, Sandbox):
            session_sandbox = sandbox

    toolset = build_session_toolset(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
        include_subagent_tool=False,
        sandbox=session_sandbox,
    )

    all_servers = [
        create_mcp_server(name, tools=tools)
        for name, tools in toolset["groups"].items()
        if name != EXAMPLE_GROUP
    ]

    policy = ToolPolicy(settings)
    policy_servers = policy.get_mcp_servers(*all_servers)

    system_prompt = get_system_prompt()

    hooks = create_permission_hooks(
        rw_dirs=notes.rw,
        ro_dirs=notes.ro,
    )

    from lup.hooks import create_completion_guard, create_reflection_gate

    reflection_hooks = create_reflection_gate(
        gate=toolset["gate"],
        gated_tool="mcp__notes__submit_output",
        reflection_tool_name="mcp__notes__review",
    )
    hooks = merge_hooks(hooks, reflection_hooks)

    completion_hooks = create_completion_guard(toolset["output_path"].exists)
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
        max_thinking_tokens=settings.max_thinking_tokens,
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


def check_settings_supported(capabilities: AdapterCapabilities) -> None:
    """Reject explicitly-set settings the backend cannot honor.

    Only env-provided fields (``settings.model_fields_set``) are checked,
    so Claude-tier defaults don't break Codex/OpenAI runs. One policy for
    every capability-gated setting: explicit and unsupported is an error,
    defaulted and unsupported passes silently.
    """
    requirements = {
        "max_turns": capabilities.max_turns,
        "permission_mode": capabilities.permission_modes,
        "max_thinking_tokens": capabilities.max_thinking_tokens,
    }
    offenders = sorted(
        name
        for name, supported in requirements.items()
        if not supported and name in settings.model_fields_set
    )
    if offenders:
        env_names = ", ".join(f"AGENT_{name.upper()}" for name in offenders)
        raise ValueError(
            f"{env_names} not supported on the {settings.agent_sdk} "
            "backend; unset or use AGENT_SDK=claude."
        )


def build_codex_session(
    notes: "NotesConfig",
    *,
    realtime_dir: Path | None = None,
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

    state_dir = Path(tempfile.mkdtemp(prefix="lup_codex_session_"))
    gate_flag_path = state_dir / "reflection_gate_flag"

    context = SessionContext(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
        gate_flag=gate_flag_path,
        session_id=notes.session.name,
        task_id=notes.output.parent.name,
        realtime_dir=realtime_dir,
    )

    return get_system_prompt(), context.to_env(), list(notes.rw)


def codex_budget_options() -> tuple[float | None, "UsageCost | None"]:
    """Budget enforcement options for Codex-runtime adapters.

    The Codex SDK reports token counts, not cost — enforcing
    ``AGENT_MAX_BUDGET_USD`` requires per-MTok rates for the configured
    model (``CODEX_USD_PER_MTOK_INPUT`` / ``_OUTPUT``, optional
    ``_CACHED_INPUT``). A budget without rates fails loudly.
    """
    from lup.adapters.codex import per_mtok_usage_cost

    usage_cost: UsageCost | None = None
    if (
        settings.codex_usd_per_mtok_input is not None
        and settings.codex_usd_per_mtok_output is not None
    ):
        usage_cost = per_mtok_usage_cost(
            input_usd=settings.codex_usd_per_mtok_input,
            output_usd=settings.codex_usd_per_mtok_output,
            cached_input_usd=settings.codex_usd_per_mtok_cached_input,
        )
    if settings.max_budget_usd is not None and usage_cost is None:
        raise ValueError(
            "AGENT_MAX_BUDGET_USD on the codex/openai backends requires "
            "CODEX_USD_PER_MTOK_INPUT and CODEX_USD_PER_MTOK_OUTPUT — the "
            "Codex SDK reports tokens, not cost."
        )
    return settings.max_budget_usd, usage_cost


def build_codex_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build a CodexAdapter for the agent session."""
    from lup.adapters.codex import CodexAdapter

    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.toolsets import tool_group_names

    system_prompt, mcp_env, writable_roots = build_codex_session(notes)
    max_budget_usd, usage_cost = codex_budget_options()
    policy = ToolPolicy(settings)

    return CodexAdapter(
        model=settings.model,
        system_prompt=system_prompt,
        sandbox=settings.codex_sandbox,
        effort=settings.codex_effort or settings.reasoning_effort,
        approval_policy=settings.codex_approval_policy,
        mcp_tools=True,
        mcp_env=mcp_env,
        writable_roots=writable_roots,
        mcp_servers=policy.filter_group_names(tool_group_names(realtime=False)),
        max_budget_usd=max_budget_usd,
        usage_cost=usage_cost,
    )


def build_codex_realtime_adapter(
    notes: "NotesConfig",
) -> tuple["AgentAdapter", "RealtimeMailbox"]:
    """Build a CodexAdapter wired for persistent (sleep/wake) mode.

    Adds the ``session`` tool group (reply, sleep, context, meta, …) to
    the served servers and relays the realtime directory so the tool
    subprocess and the parent share one mailbox. The returned mailbox is
    the parent-side endpoint: construct a ``Scheduler`` with your
    environment's action callback, open ``adapter.conversation()``, and
    drive it with :func:`lup.realtime_relay.run_relay_session`
    (customization step 8 — see PATTERNS.md, Persistent Agent).
    """
    from lup.adapters.codex import CodexAdapter
    from lup.realtime_relay import REALTIME_DIRNAME, RealtimeMailbox

    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.toolsets import tool_group_names

    realtime_dir = notes.session / REALTIME_DIRNAME
    system_prompt, mcp_env, writable_roots = build_codex_session(
        notes, realtime_dir=realtime_dir
    )
    max_budget_usd, usage_cost = codex_budget_options()
    policy = ToolPolicy(settings)

    adapter = CodexAdapter(
        model=settings.model,
        system_prompt=system_prompt,
        sandbox=settings.codex_sandbox,
        effort=settings.codex_effort or settings.reasoning_effort,
        approval_policy=settings.codex_approval_policy,
        mcp_tools=True,
        mcp_env=mcp_env,
        writable_roots=writable_roots,
        mcp_servers=policy.filter_group_names(tool_group_names(realtime=True)),
        max_budget_usd=max_budget_usd,
        usage_cost=usage_cost,
    )
    check_settings_supported(adapter.capabilities)
    return adapter, RealtimeMailbox(realtime_dir)


def build_openai_adapter(
    notes: "NotesConfig",
) -> "AgentAdapter":
    """Build an OpenAICompatibleAdapter with full tools and enforcement."""
    from lup.adapters.openai_compat import OpenAICompatibleAdapter

    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.toolsets import tool_group_names

    system_prompt, mcp_env, writable_roots = build_codex_session(notes)
    max_budget_usd, usage_cost = codex_budget_options()
    policy = ToolPolicy(settings)

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
        mcp_servers=policy.filter_group_names(tool_group_names(realtime=False)),
        max_budget_usd=max_budget_usd,
        usage_cost=usage_cost,
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

    adapter: AgentAdapter
    ctx: AbstractContextManager[object]
    match settings.agent_sdk:
        case "claude":
            from lup.adapters.claude import ClaudeAdapter
            from lup.sandbox import Sandbox

            sb = Sandbox(
                session_id=session_id,
                shared_dir=notes.session / "sandbox_shared",
                timeout_seconds=settings.sandbox_timeout_seconds,
            )
            adapter, ctx = ClaudeAdapter(build_options(notes, sandbox=sb)), sb

        case "codex":
            adapter, ctx = (
                build_codex_adapter(notes),
                subprocess_sandbox_cleanup(notes),
            )

        case "openai":
            adapter, ctx = (
                build_openai_adapter(notes),
                subprocess_sandbox_cleanup(notes),
            )

    check_settings_supported(adapter.capabilities)
    return adapter, ctx, notes


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
