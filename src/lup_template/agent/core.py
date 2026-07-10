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

    from lup.adapters.options import LupAgentOptions
    from lup.sandbox.container import Sandbox
    from lup.types import UsageCost

from lup_template.agent.config import (
    compat_api_key,
    compat_base_url,
    engine_for_settings,
    settings,
)
from lup_template.agent.models import AgentOutput, AgentSessionResult
from lup.adapters.clients.Client import Client
from lup.adapters.tools.names import WEB_TOOLS
from lup.telemetry.metrics import (
    get_metrics_summary,
    log_metrics_summary,
    reset_metrics,
)
from lup.telemetry.trace import TraceLogger
from lup.workspace.history import save_session
from lup.workspace.notes import NotesConfig, setup_notes
from lup.workspace.output import ensure_output_submitted, output_path
from lup.types import LupContentBlock, LupResponse, LupTextBlock, LupToolUseBlock
from lup.workspace.paths import agent_version

logger = logging.getLogger(__name__)

type McpEnv = dict[str, str]  # lup: ignore[dict-str-payload] — open env map


class CodexScaffold(BaseModel):
    """Shared scaffolding for the Codex-runtime adapters."""

    system_prompt: str
    mcp_env: McpEnv
    writable_roots: list[Path]


class PersistentSessionResult(BaseModel):
    """Outcome of a persistent (sleep/wake) session.

    A persistent session produces no submitted output to assemble, so its
    result is the relay bookkeeping — the number of wake-driven turns it ran.
    """

    turns: int


def extract_sources(blocks: list[LupContentBlock]) -> list[str]:
    """Extract source URLs/queries from tool use blocks."""

    def source_of(block: LupContentBlock) -> str | None:
        if not (isinstance(block, LupToolUseBlock) and block.name in WEB_TOOLS):
            return None
        if not isinstance(block.input, dict):
            return None
        payload = block.input
        found = payload.get("url") or payload.get("query")  # lup: ignore[dict-get]
        return str(found) if found else None

    return [source for block in blocks if (source := source_of(block))]


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
    from lup.telemetry.metrics import read_metrics_summary
    from lup.workspace.output import read_output

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
        sdk_session_id=response.session_id,
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


def build_session_options(
    notes: "NotesConfig",
    *,
    realtime: bool = False,
    model: str | None = None,
    toolless: bool = False,
    bare_prompt: bool = False,
) -> "LupAgentOptions":
    """Assemble the whole session in neutral terms — no engine named.

    Describes both enforcement mechanisms and lets the engine consume its
    own side: hook-enforced engines read the in-process assembly (MCP
    servers, the permission/reflection/completion hooks, the allowlist the
    policy produces), and natively-sandboxed engines read the subprocess
    assembly (served tool groups, env relay, writable roots). Intent knobs
    pass through as the user set them — an engine refuses at construction
    what it cannot honor, and unset knobs get engine defaults. Sessions
    persist, so ``lup run --resume`` can continue them.

    The keyword overrides are assembly knobs (the REPL's ``--model``,
    ``--no-tools``, ``--no-prompt``): ``model`` replaces the configured
    session model everywhere it is read, ``toolless`` skips the tool
    assembly on both sides — no tool servers, no served groups, none of
    the tool-coupled hooks (reflection gate, completion guard, allowlist),
    no code-execution sandbox; the permission hooks stay — and
    ``bare_prompt`` sends an empty system prompt with the coding-harness
    preset off. Overrides are realized here, in neutral terms, never by
    patching a translated client.
    """
    from lup.adapters.wiring import resolve_engine
    from lup.hooks import (
        create_completion_guard,
        create_permission_hooks,
        create_tool_allowlist_hook,
        merge_hooks,
    )
    from lup.adapters.options import LupAgentOptions
    from lup.mcp import McpServerEntry, create_mcp_server
    from lup.realtime.relay import REALTIME_DIRNAME
    from lup.reflect import create_reflection_gate

    from lup_template.agent.subagents import get_subagent_specs
    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.toolsets import (
        EXAMPLE_GROUP,
        build_session_toolset,
        tool_group_names,
    )

    effective_model = model or settings.model
    policy = ToolPolicy(settings)

    hooks = create_permission_hooks(rw_dirs=notes.rw, ro_dirs=notes.ro)
    policy_servers: dict[str, McpServerEntry] = {}  # lup: ignore[empty-collection]
    allowed_tools: list[str] = []  # lup: ignore[empty-collection]
    served_groups: list[str] = []  # lup: ignore[empty-collection]
    if not toolless:
        # In-process assembly — consumed by hook-enforced engines (claude*).
        toolset = build_session_toolset(
            session_dir=notes.session,
            outputs_dir=notes.output.parent,
            include_subagent_tool=False,
            sandbox=build_session_sandbox(notes),
        )
        all_servers = [
            create_mcp_server(name, tools=policy.filter_tools(tools))
            for name, tools in toolset["groups"].items()
            if name != EXAMPLE_GROUP
        ]
        policy_servers = policy.get_mcp_servers(*all_servers)
        hooks = merge_hooks(
            hooks,
            create_reflection_gate(
                gate=toolset["gate"],
                gated_tool="mcp__notes__submit_output",
                reflection_tool_name="mcp__notes__review",
            ),
        )
        hooks = merge_hooks(
            hooks, create_completion_guard(toolset["output_path"].exists)
        )
        # Tool allowlist: allowed_tools in options is ignored under
        # bypassPermissions, so availability is enforced by a PreToolUse hook.
        builtin_tools = resolve_engine(
            engine_for_settings(), model=effective_model
        ).builtin_tools()
        allowed_tools = policy.get_allowed_tools(
            policy_servers, builtin_tools=builtin_tools
        )
        hooks = merge_hooks(hooks, create_tool_allowlist_hook(allowed_tools))
        served_groups = policy.filter_group_names(tool_group_names(realtime=realtime))

    # Subprocess assembly — consumed by natively-sandboxed engines (codex*).
    realtime_dir = notes.session / REALTIME_DIRNAME if realtime else None
    scaffold = build_codex_session(
        notes, realtime_dir=realtime_dir, model=effective_model
    )
    system_prompt, mcp_env, writable_roots = (
        scaffold.system_prompt,
        scaffold.mcp_env,
        scaffold.writable_roots,
    )
    if bare_prompt:
        system_prompt = ""

    return LupAgentOptions(
        model=effective_model,
        system_prompt=system_prompt,
        coding_harness_preset=not bare_prompt,
        tool_servers=policy_servers,
        subagents=get_subagent_specs(),
        hooks=hooks,
        allowed_tools=allowed_tools,
        served_tool_groups=served_groups,
        add_dirs=list(notes.all_dirs),
        permission_mode=settings.permission_mode,
        max_turns=settings.max_turns,
        max_thinking_tokens=settings.max_thinking_tokens,
        reasoning_effort=settings.codex_effort or settings.reasoning_effort,
        max_budget_usd=settings.max_budget_usd,
        turn_timeout_seconds=settings.turn_timeout_seconds,
        usage_cost=build_usage_cost(),
        realtime=realtime,
        base_url=compat_base_url(),
        api_key=compat_api_key(),
        model_provider=settings.openai_model_provider,
        codex_sandbox=settings.codex_sandbox,
        approval_policy=settings.codex_approval_policy,
        mcp_env=mcp_env,
        writable_roots=writable_roots,
        session_id=notes.session.name,
        shared_dir=notes.session / "sandbox_shared",
        realtime_dir=realtime_dir,
    )


def build_codex_session(
    notes: "NotesConfig",
    *,
    realtime_dir: Path | None = None,
    model: str | None = None,
) -> CodexScaffold:
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

    from lup.workspace.context import SessionContext

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
        "AGENT_MODEL": model or settings.model,
    }
    if settings.aux_model:
        mcp_env["AGENT_AUX_MODEL"] = settings.aux_model

    return CodexScaffold(
        system_prompt=get_system_prompt(),
        mcp_env=mcp_env,
        writable_roots=list(notes.rw),
    )


def build_usage_cost() -> "UsageCost | None":
    """The token→USD estimator from the configured per-MTok rates.

    The Codex runtime reports token counts, not cost — budget enforcement
    there needs ``CODEX_USD_PER_MTOK_INPUT`` / ``_OUTPUT`` (optional
    ``_CACHED_INPUT``). Without rates this stays ``None``, and a codex-tier
    engine given a budget refuses the construction.
    """
    from lup.adapters.clients.usage import per_mtok_usage_cost

    if (
        settings.codex_usd_per_mtok_input is None
        or settings.codex_usd_per_mtok_output is None
    ):
        return None
    return per_mtok_usage_cost(
        input_usd=settings.codex_usd_per_mtok_input,
        output_usd=settings.codex_usd_per_mtok_output,
        cached_input_usd=settings.codex_usd_per_mtok_cached_input,
    )


def resolve_resume_token(reference: str) -> str:
    """Turn a ``--resume`` reference into an engine session id.

    A saved run's session name resolves to its stored ``sdk_session_id``
    (the engine-native resume token). An unknown reference is assumed to
    already be an engine session id and passes through — a saved run that
    recorded no token fails loudly instead of silently starting fresh.
    """
    from lup.workspace.history import latest_session_record

    record = latest_session_record(reference)
    if record is None:
        return reference
    token = record.sdk_session_id
    if not token:
        raise ValueError(
            f"Session {reference!r} recorded no engine session id to resume "
            "from (it predates resume support or its engine reported none)."
        )
    return token


def build_session_sandbox(notes: "NotesConfig") -> "Sandbox | None":
    """The code-execution sandbox for the in-process toolset, if available.

    Optional twice over: ``AGENT_SANDBOX_ENABLED=false`` runs the agent
    without code execution tools, and a missing docker extra degrades the
    same way instead of failing sessions that never use these tools
    (subprocess engines run their own sandbox tool-side).
    """
    if not settings.sandbox_enabled:
        return None
    try:
        from lup.sandbox.container import Sandbox
    except ImportError:
        logger.warning(
            "docker extra not installed; running without code-execution tools"
        )
        return None

    return Sandbox(
        session_id=notes.session.name,
        shared_dir=notes.session / "sandbox_shared",
        timeout_seconds=settings.sandbox_timeout_seconds,
    )


class SessionBuild(BaseModel):
    """A constructed session client plus the notes it reports into."""

    model_config = {"arbitrary_types_allowed": True}

    client: Client
    notes: NotesConfig


def build_session_client(
    session_id: str,
    task_id: str | None = None,
    *,
    realtime: bool = False,
    model: str | None = None,
    toolless: bool = False,
    bare_prompt: bool = False,
) -> SessionBuild:
    """Build the session's client for ``settings.agent_sdk``.

    Assembles neutral :class:`~lup.adapters.options.LupAgentOptions` and hands them
    to ``create_client`` with the configured engine — no ``match`` on the
    backend, no native option type. Session-scoped resources live inside
    ``client.session()``; session artifacts are read from the notes.
    ``model``/``toolless``/``bare_prompt`` pass through to
    :func:`build_session_options` (the REPL's overrides).
    """
    from lup.adapters.wiring import create_client

    notes = setup_notes(session_id, task_id or "0")
    opts = build_session_options(
        notes,
        realtime=realtime,
        model=model,
        toolless=toolless,
        bare_prompt=bare_prompt,
    )
    return SessionBuild(
        client=create_client(options=opts, engine=engine_for_settings()),
        notes=notes,
    )


async def run_agent(
    task: str,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
    resume: str | None = None,
) -> AgentSessionResult:
    """Run the agent on a task, on the engine ``settings.agent_sdk`` names.

    ``resume`` takes a previous run's SDK session id (``lup run --resume``
    resolves it from history) and continues that conversation instead of
    starting fresh.
    """
    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("Starting session %s (sdk=%s)", session_id, settings.agent_sdk)
    reset_metrics()

    build = build_session_client(session_id, task_id)
    notes = build.notes

    trace_logger = TraceLogger(
        trace_path=notes.trace_log, title=f"Session {session_id}"
    )

    async with build.client.session(resume=resume) as session:
        response = await session.send(task, trace_logger=trace_logger)
        # A no-op where the engine's Stop hook already forced submission;
        # elsewhere this is the one retry nudge toward submit_output.
        retry = await ensure_output_submitted(
            session,
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

    The relay transport is for subprocess engines (codex/openai-compat) —
    they surface a ``client.mailbox``. An in-process engine (Claude — one
    never-ending turn with a Stop hook, see PATTERNS.md, Persistent Agent)
    has no relay mailbox, so this entry point raises rather than running
    there.

    Returns:
        The completed-turn count.
    """
    from lup.realtime.relay import run_relay_session
    from lup.realtime.scheduler import Scheduler
    from lup.reflect import ReflectionGate

    from lup_template.agent.tools.realtime import MISSING_SLEEP_MESSAGE

    if session_id is None:
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info(
        "Starting persistent session %s (sdk=%s)", session_id, settings.agent_sdk
    )
    reset_metrics()

    build = build_session_client(session_id, realtime=True)
    notes = build.notes
    mailbox = build.client.mailbox
    if mailbox is None:
        raise ValueError(
            "Persistent mode on this engine runs in-process (customization "
            "step 8; PATTERNS.md 'Persistent Agent'); the relay entry point "
            "needs AGENT_SDK=codex or openai."
        )

    async def echo_reply(message: str) -> None:
        print(f"[lup] {message}")

    scheduler = Scheduler(on_action=on_reply or echo_reply)
    meta_gate = ReflectionGate(flag_path=mailbox.meta_flag_path)
    trace_logger = TraceLogger(
        trace_path=notes.trace_log, title=f"Session {session_id}"
    )

    async with build.client.session() as session:
        turns = await run_relay_session(
            session,
            scheduler=scheduler,
            mailbox=mailbox,
            initial_prompt=task,
            missing_sleep_message=MISSING_SLEEP_MESSAGE,
            gate=meta_gate,
            trace_logger=trace_logger,
        )

    trace_logger.save()
    log_metrics_summary()
    return PersistentSessionResult(turns=turns)
