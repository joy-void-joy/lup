"""Main agent orchestration.

This is a TEMPLATE. Customize for your domain.

Dispatches to the appropriate SDK adapter based on ``settings.agent_sdk``.
SDK-specific imports are deferred (inline or TYPE_CHECKING) so the
module loads without requiring any particular SDK to be installed.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from lup.notes import NotesConfig
    from lup.options import BuiltAdapter, LupAgentOptions
    from lup.sandbox import Sandbox
    from lup.types import Backend, UsageCost

from lup_template.agent.config import settings
from lup_template.agent.models import AgentOutput, AgentSessionResult
from lup.adapters.common import AdapterCapabilities
from lup.history import save_session
from lup.metrics import get_metrics_summary, log_metrics_summary, reset_metrics
from lup.notes import setup_notes
from lup.output import ensure_output_submitted, output_path
from lup.trace import TraceLogger
from lup.types import LupContentBlock, LupResponse, LupTextBlock, LupToolUseBlock
from lup.paths import agent_version

logger = logging.getLogger(__name__)


class PersistentSessionResult(BaseModel):
    """Outcome of a persistent (sleep/wake) session.

    A persistent session produces no submitted output to assemble, so its
    result is the relay bookkeeping — the number of wake-driven turns it ran.
    """

    turns: int


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
        agent_sdk=settings.agent_sdk,
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


def build_inprocess_options(
    notes: "NotesConfig",
    *,
    sandbox: "Sandbox | None" = None,
) -> "LupAgentOptions":
    """Assemble the neutral options for an in-process (hook-enforced) session.

    Gathers the session's parts into one backend-agnostic value before the run
    can start: the MCP servers the tools live on, the prompt that briefs the
    agent, the hooks that police it, the subagents it may spawn, and the model
    settings. The parts depend on each other in order — the toolset names the
    MCP servers, the policy decides which of those the agent is allowed, and
    the hooks are layered so the last word on availability is the allowlist the
    policy produces. The adapter's builder translates this into its native
    option object; this function names no backend.

    Args:
        notes: Session notes config.
        sandbox: Optional Sandbox instance for sandboxed execution.

    Returns:
        Backend-agnostic ``LupAgentOptions``.
    """
    from lup.hooks import (
        create_completion_guard,
        create_permission_hooks,
        create_tool_allowlist_hook,
    )
    from lup.mcp import create_mcp_server
    from lup.options import LupAgentOptions
    from lup.reflect import create_reflection_gate
    from lup.types import merge_hooks

    from lup_template.agent.prompts import get_system_prompt
    from lup_template.agent.subagents import get_subagent_specs
    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.toolsets import EXAMPLE_GROUP, build_session_toolset

    toolset = build_session_toolset(
        session_dir=notes.session,
        outputs_dir=notes.output.parent,
        include_subagent_tool=False,
        sandbox=sandbox,
    )

    policy = ToolPolicy(settings)

    all_servers = [
        create_mcp_server(name, tools=policy.filter_tools(tools))
        for name, tools in toolset["groups"].items()
        if name != EXAMPLE_GROUP
    ]

    policy_servers = policy.get_mcp_servers(*all_servers)

    hooks = create_permission_hooks(rw_dirs=notes.rw, ro_dirs=notes.ro)

    reflection_hooks = create_reflection_gate(
        gate=toolset["gate"],
        gated_tool="mcp__notes__submit_output",
        reflection_tool_name="mcp__notes__review",
    )
    hooks = merge_hooks(hooks, reflection_hooks)

    completion_hooks = create_completion_guard(toolset["output_path"].exists)
    hooks = merge_hooks(hooks, completion_hooks)

    # Tool allowlist: allowed_tools in options is ignored under
    # bypassPermissions, so availability is enforced by a PreToolUse hook.
    allowed_tools = policy.get_allowed_tools(policy_servers)
    hooks = merge_hooks(hooks, create_tool_allowlist_hook(allowed_tools))

    return LupAgentOptions(
        model=settings.model,
        system_prompt=get_system_prompt(),
        tool_servers=policy_servers,
        subagents=get_subagent_specs(),
        hooks=hooks,
        allowed_tools=allowed_tools,
        add_dirs=list(notes.all_dirs),
        max_thinking_tokens=settings.max_thinking_tokens,
        permission_mode=settings.permission_mode,
        reasoning_effort=settings.reasoning_effort,
        max_turns=settings.max_turns,
        max_budget_usd=settings.max_budget_usd,
        persist_session=False,
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
        "turn_timeout_seconds": capabilities.turn_timeout,
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

    # The serve-tools subprocess resolves aux_model() from its own settings,
    # and the Codex runtime does not pass the parent's shell env through to
    # MCP servers — relay the inputs that resolution needs.
    mcp_env = {
        **context.to_env(),
        "AGENT_SDK": settings.agent_sdk,
        "AGENT_MODEL": settings.model,
    }
    if settings.aux_model:
        mcp_env["AGENT_AUX_MODEL"] = settings.aux_model

    return get_system_prompt(), mcp_env, list(notes.rw)


def codex_budget_options() -> tuple[float | None, "UsageCost | None"]:
    """Budget enforcement options for Codex-runtime adapters.

    The Codex SDK reports token counts, not cost — enforcing
    ``AGENT_MAX_BUDGET_USD`` requires per-MTok rates for the configured
    model (``CODEX_USD_PER_MTOK_INPUT`` / ``_OUTPUT``, optional
    ``_CACHED_INPUT``). A budget without rates fails loudly.
    """
    from lup.adapters.codex.adapter import per_mtok_usage_cost

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


def build_subprocess_options(
    notes: "NotesConfig",
    *,
    realtime: bool = False,
) -> "LupAgentOptions":
    """Assemble the neutral options for a subprocess (natively-sandboxed) session.

    Enforcement on these backends is native and in-tool: the runtime's
    workspace-write sandbox confines writes to the writable roots, and the
    reflection gate is checked inside submit_output (the serve-tools subprocess
    reads the flag path from the relayed env). The served tool groups gain the
    ``session`` group in realtime mode, and the realtime directory is relayed
    so the tool subprocess and the parent share one mailbox. This function
    names no backend; the adapter's builder reads ``opts.realtime`` to wire the
    mailbox.
    """
    from lup.options import CodexOptions, LupAgentOptions
    from lup.realtime_relay import REALTIME_DIRNAME

    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.toolsets import tool_group_names

    realtime_dir = notes.session / REALTIME_DIRNAME if realtime else None
    system_prompt, mcp_env, writable_roots = build_codex_session(
        notes, realtime_dir=realtime_dir
    )
    max_budget_usd, usage_cost = codex_budget_options()
    policy = ToolPolicy(settings)

    return LupAgentOptions(
        model=settings.model,
        system_prompt=system_prompt,
        served_tool_groups=policy.filter_group_names(
            tool_group_names(realtime=realtime)
        ),
        reasoning_effort=settings.codex_effort or settings.reasoning_effort,
        max_budget_usd=max_budget_usd,
        turn_timeout_seconds=settings.turn_timeout_seconds,
        usage_cost=usage_cost,
        realtime=realtime,
        codex=CodexOptions(
            sandbox=settings.codex_sandbox,
            approval_policy=settings.codex_approval_policy,
            mcp_env=mcp_env,
            writable_roots=writable_roots,
            session_id=notes.session.name,
            shared_dir=notes.session / "sandbox_shared",
            realtime_dir=realtime_dir,
            openai_base_url=settings.openai_base_url,
            openai_api_key=settings.openai_api_key,
            openai_model_provider=settings.openai_model_provider,
        ),
    )


def backend_for_settings() -> "Backend":
    """Map ``settings.agent_sdk`` to the adapter registry's backend id.

    The one place the application's SDK names meet the library's backend ids;
    everything downstream speaks ``Backend`` and routes through the registry.
    """
    match settings.agent_sdk:
        case "claude":
            return "anthropic"
        case "codex":
            return "openai"
        case "openai":
            return "openai-compatible"


def build_session_options(
    notes: "NotesConfig",
    capabilities: AdapterCapabilities,
    *,
    realtime: bool = False,
) -> "LupAgentOptions":
    """Assemble neutral options for a session, picking the assembly by capability.

    A backend with in-process hooks gets the hook-enforced assembly (in-process
    MCP servers, permission/reflection/allowlist hooks); one without gets the
    natively-sandboxed assembly (served tool groups, env relay). The choice is
    driven by ``capabilities.hooks``, never the backend name — adding a backend
    is choosing which assembly its capabilities select, not editing this code.
    """
    if capabilities.hooks:
        sandbox = build_session_sandbox(notes)
        return build_inprocess_options(notes, sandbox=sandbox)
    return build_subprocess_options(notes, realtime=realtime)


def build_session_sandbox(notes: "NotesConfig") -> "Sandbox | None":
    """The code-execution sandbox for a hook-enforced session, if enabled.

    Optional: ``AGENT_SANDBOX_ENABLED=false`` runs the agent without code
    execution tools (no Docker required).
    """
    if not settings.sandbox_enabled:
        return None
    from lup.sandbox import Sandbox

    return Sandbox(
        session_id=notes.session.name,
        shared_dir=notes.session / "sandbox_shared",
        timeout_seconds=settings.sandbox_timeout_seconds,
    )


def build_adapter(
    session_id: str,
    task_id: str | None = None,
    *,
    realtime: bool = False,
) -> tuple["BuiltAdapter", NotesConfig]:
    """Build the session adapter for ``settings.agent_sdk`` through the registry.

    Resolves the backend, assembles neutral :class:`~lup.options.LupAgentOptions`
    keyed off the backend's capabilities, and hands them to
    ``lup.adapters.build_adapter`` — no ``match`` on the backend, no native
    option type. Returns the built adapter bundle (adapter, lifecycle, optional
    mailbox) and the notes config; the caller enters ``built.lifecycle`` around
    the run and reads session artifacts from the notes.
    """
    from lup.adapters.registry import build_adapter as registry_build_adapter

    notes = setup_notes(session_id, task_id or "0")
    backend = backend_for_settings()
    capabilities = build_backend_capabilities(backend)
    check_settings_supported(capabilities)
    opts = build_session_options(notes, capabilities, realtime=realtime)
    return registry_build_adapter(backend, opts), notes


def build_backend_capabilities(backend: "Backend") -> AdapterCapabilities:
    """The capabilities of *backend*, used to gate settings and pick the assembly.

    Built without standing up a full session — the static support flags are
    what the assembly choice and the settings guard read.
    """
    from lup.adapters.registry import backend_capabilities

    return backend_capabilities(backend)


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

    built, notes = build_adapter(session_id, task_id)
    adapter = built.adapter

    trace_logger = TraceLogger(
        trace_path=notes.trace_log, title=f"Session {session_id}"
    )

    with built.lifecycle:
        async with adapter.conversation() as conv:
            response = await conv.send(task, trace_logger=trace_logger)
            if not adapter.capabilities.stop_event:
                retry = await ensure_output_submitted(
                    conv,
                    output_exists=output_path(notes.session).exists,
                    trace_logger=trace_logger,
                )
                if retry is not None:
                    response = retry

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


async def run_persistent_agent(
    task: str,
    *,
    session_id: str | None = None,
    on_reply: "Callable[[str], Awaitable[None]] | None" = None,
) -> PersistentSessionResult:
    """Run a persistent (sleep/wake) session through the file relay.

    The minimal wiring of the Persistent Agent pattern on the relay backends:
    the parent owns the Scheduler, each wake is one SDK turn, and the served
    ``session`` tools relay through the mailbox. Replies surface through
    ``on_reply`` (stdout by default) — replace it with your environment's
    delivery callback, and call ``scheduler.wake(...)`` from your event sources
    (customization step 8). Artifacts are the trace log and the relay
    directory; a persistent session has no ``submit_output`` finalization, so
    no session JSON is saved.

    The relay transport is for backends whose ``capabilities.realtime`` is
    ``"relay"`` (codex/openai). An in-process backend (Claude — one never-ending
    turn with a Stop hook, see PATTERNS.md, Persistent Agent) has no relay
    mailbox, so this entry point raises rather than running there.

    Returns:
        The completed-turn count.
    """
    from lup.realtime import Scheduler
    from lup.realtime_relay import run_relay_session

    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info(
        "Starting persistent session %s (sdk=%s)", session_id, settings.agent_sdk
    )
    reset_metrics()

    built, notes = build_adapter(session_id, realtime=True)
    if built.mailbox is None:
        raise ValueError(
            "Persistent mode on this backend runs in-process (customization "
            "step 8; PATTERNS.md 'Persistent Agent'); the relay entry point "
            "needs AGENT_SDK=codex or openai."
        )

    async def echo_reply(message: str) -> None:
        print(f"[lup] {message}")

    scheduler = Scheduler(on_action=on_reply or echo_reply)
    trace_logger = TraceLogger(
        trace_path=notes.trace_log, title=f"Session {session_id}"
    )

    with built.lifecycle:
        async with built.adapter.conversation() as conv:
            turns = await run_relay_session(
                conv,
                scheduler=scheduler,
                mailbox=built.mailbox,
                initial_prompt=task,
                trace_logger=trace_logger,
            )

    trace_logger.save()
    log_metrics_summary()
    return PersistentSessionResult(turns=turns)
