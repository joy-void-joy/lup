"""Application composition roots over Lup's provider-neutral runtime."""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, SecretStr

from lup.adapters.claude.config import (
    ClaudeCompatibilityTransform,
    ClaudeCompatibleEndpoint,
)
from lup.adapters.claude.runtime import (
    SESSION_THINKING_TOKENS,
    ClaudeSandboxConfig,
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.adapters.codex.config import (
    CodexCompatibilityTransform,
    CodexCompatibleEndpoint,
)
from lup.adapters.codex.runtime import (
    CodexMcpServerConfig,
    CodexSessionConfig,
    create_codex_session_factory,
)
from lup.runtime.contracts import SessionFactory
from lup.runtime.composition import submission_gate_resolver
from lup.hooks import LupHooksConfig
from lup.runtime.models import (
    SessionHandle,
    SessionId,
    SubmissionDecision,
    SubmissionGate,
    SubmissionGateResolver,
    TurnBlock,
    TurnInput,
    TurnResult,
    TurnTextBlock,
    TurnThinkingBlock,
    TurnToolCallBlock,
    TurnToolResultBlock,
    turn_request,
)
from lup.runtime.usage import per_mtok_usage_cost
from lup.runtime.wrappers import (
    BudgetConfig,
    CorrectionConfig,
    DecoratingSessionFactory,
    DisplayConfig,
    DisplayRecord,
    PersistenceConfig,
    TimeoutConfig,
    TraceRecord,
    TracingConfig,
)
from lup.mcp import McpServerEntry
from lup.telemetry.metrics import (
    get_metrics_summary,
    log_metrics_summary,
    reset_metrics,
)
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupContentBlock,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    SubagentSpec,
    Usage,
    UsageCost,
)
from lup.workspace.history import save_session
from lup.workspace.notes import NotesConfig, setup_notes
from lup.workspace.paths import agent_version
from lup_template.agent.config import (
    compat_api_key,
    compat_base_url,
    settings,
)
from lup_template.agent.models import AgentOutput, AgentSessionResult
from lup_template.agent.prompts import get_system_prompt

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from lup.reflect import ReviewGate
    from lup.sandbox.container import Sandbox


class PersistentSessionResult(BaseModel):
    """Number of wake-driven turns completed by a persistent session."""

    turns: int


class SessionBuild(BaseModel):
    """Configured provider-neutral factory and its application workspace."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    factory: SessionFactory
    notes: NotesConfig
    trace_logger: TraceLogger


class CleaningSessionFactory(SessionFactory):
    """Run one application resource cleanup after every opened session."""

    def __init__(self, inner: SessionFactory, cleanup: Callable[[], None]) -> None:
        self.inner = inner
        self.cleanup = cleanup

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.open_cleaned(resume)

    @asynccontextmanager
    async def open_cleaned(
        self, resume: SessionId | None
    ) -> AsyncIterator[SessionHandle]:
        try:
            async with self.inner.open(resume) as handle:
                yield handle
        finally:
            self.cleanup()


def reflection_submission_gate(gate: "ReviewGate") -> SubmissionGate[AgentOutput]:
    """Adapt the domain review flag to portable turn submission semantics."""

    async def decide(_output: AgentOutput) -> SubmissionDecision:
        if gate.reflected:
            return SubmissionDecision(accepted=True)
        return SubmissionDecision(
            accepted=False,
            message="Call the review tool and address its verdict before submitting.",
        )

    return decide


def build_usage_cost() -> UsageCost | None:
    """Build configured token pricing without coupling it to an adapter."""
    if settings.agent_sdk in ("claude", "claude-compat"):
        return reported_usage_cost
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


def reported_usage_cost(usage: Usage) -> float:
    """Use the complete cost reported by providers that supply one."""
    if usage.cost_usd is None:
        raise ValueError("the provider completed without reporting turn cost")
    return usage.cost_usd


def provider_factory(
    *,
    model: str,
    system_prompt: str,
    cwd: Path,
    tools: list[str] | None = None,
    tool_servers: dict[str, McpServerEntry] | None = None,
    allowed_tools: list[str] | None = None,
    hooks: LupHooksConfig | None = None,
    add_dirs: list[Path] | None = None,
    coding_harness_preset: bool = True,
    session_defaults: bool = True,
    submission_gate: SubmissionGateResolver | None = None,
    codex_mcp_servers: dict[str, CodexMcpServerConfig] | None = None,
    writable_roots: list[Path] | None = None,
    subagents: list[SubagentSpec] | None = None,
) -> SessionFactory:
    """The one application-owned provider selection boundary.

    Native identifiers are intentionally confined to this concrete composition
    root. Every caller above it receives only a configured ``SessionFactory``.
    """
    if settings.agent_sdk in ("claude", "claude-compat"):
        config = ClaudeSessionConfig(
            model=model,
            system_prompt=system_prompt,
            coding_harness_preset=coding_harness_preset,
            tools=tools,
            allowed_tools=allowed_tools or [],
            tool_servers=tool_servers or {},
            permission_mode=(
                settings.permission_mode
                if settings.permission_mode is not None
                else "bypassPermissions"
                if session_defaults
                else None
            ),
            max_turns=settings.max_turns,
            max_thinking_tokens=(
                settings.max_thinking_tokens
                if settings.max_thinking_tokens is not None
                else SESSION_THINKING_TOKENS
                if session_defaults
                else None
            ),
            effort=normalize_claude_effort(settings.reasoning_effort),
            cwd=cwd,
            add_dirs=add_dirs or list(settings.extra_dirs),
            sandbox=ClaudeSandboxConfig() if session_defaults else None,
            hooks=hooks,
            submission_gate_resolver=submission_gate,
            subagents=subagents or [],
        )
        endpoint = compat_base_url()
        if endpoint is not None:
            config = ClaudeCompatibilityTransform(
                ClaudeCompatibleEndpoint(
                    base_url=AnyHttpUrl(endpoint),
                    api_key=(
                        SecretStr(key)
                        if (key := compat_api_key()) is not None
                        else None
                    ),
                )
            ).apply(config)
        return create_claude_session_factory(config)

    if settings.agent_sdk in ("codex", "openai", "openai-compat"):
        unsupported = [
            name
            for name, value in [
                ("AGENT_PERMISSION_MODE", settings.permission_mode),
                ("AGENT_MAX_TURNS", settings.max_turns),
                ("AGENT_MAX_THINKING_TOKENS", settings.max_thinking_tokens),
            ]
            if value is not None
        ]
        if tools:
            unsupported.append("tools")
        if unsupported:
            raise ValueError(
                "Codex app-server cannot honor configured option(s): "
                + ", ".join(unsupported)
            )
        config = CodexSessionConfig(
            model=model,
            developer_instructions=system_prompt,
            cwd=cwd,
            sandbox=(
                normalize_codex_sandbox(settings.codex_sandbox)
                or ("workspaceWrite" if session_defaults else None)
            ),
            approval_policy=(
                normalize_codex_approval(settings.codex_approval_policy)
                or ("never" if session_defaults else None)
            ),
            effort=normalize_codex_effort(
                settings.codex_effort or settings.reasoning_effort
            ),
            submission_gate_resolver=submission_gate,
            mcp_servers=codex_mcp_servers or {},
            writable_roots=writable_roots or [],
        )
        endpoint = compat_base_url()
        if settings.agent_sdk in ("openai", "openai-compat"):
            if endpoint is None:
                raise ValueError(
                    "OPENAI_BASE_URL is required for an OpenAI-compatible route"
                )
            config = CodexCompatibilityTransform(
                CodexCompatibleEndpoint(
                    identifier=settings.openai_model_provider or "lup_openai_compat",
                    base_url=AnyHttpUrl(endpoint),
                    api_key=(
                        SecretStr(key)
                        if (key := compat_api_key()) is not None
                        else None
                    ),
                )
            ).apply(config)
        return create_codex_session_factory(config)

    raise ValueError(f"unsupported AGENT_SDK {settings.agent_sdk!r}")


def normalize_claude_effort(
    value: str | None,
) -> Literal["low", "medium", "high", "xhigh", "max"] | None:
    """Validate the application setting at the Claude adapter boundary."""
    if value in (None, "low", "medium", "high", "xhigh", "max"):
        return value
    raise ValueError(f"unsupported Claude reasoning effort {value!r}")


def normalize_codex_sandbox(
    value: str | None,
) -> Literal["readOnly", "workspaceWrite", "dangerFullAccess"] | None:
    """Translate the documented environment spelling once at composition."""
    aliases = {
        None: None,
        "read_only": "readOnly",
        "workspace_write": "workspaceWrite",
        "danger_full_access": "dangerFullAccess",
        "readOnly": "readOnly",
        "workspaceWrite": "workspaceWrite",
        "dangerFullAccess": "dangerFullAccess",
    }
    try:
        return aliases[value]
    except KeyError as error:
        raise ValueError(f"unsupported Codex sandbox {value!r}") from error


def normalize_codex_approval(
    value: str | None,
) -> Literal["never"] | None:
    """Validate the Codex approval policy before model construction."""
    if value in (None, "never"):
        return value
    raise ValueError(
        f"Codex approval policy {value!r} is not supported by the app-server "
        "adapter; use 'never' with Lup's policy boundary"
    )


def normalize_codex_effort(
    value: str | None,
) -> Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None:
    """Validate reasoning effort at the Codex adapter boundary."""
    if value in (None, "none", "minimal", "low", "medium", "high", "xhigh"):
        return value
    raise ValueError(f"unsupported Codex reasoning effort {value!r}")


def decorate_factory(
    factory: SessionFactory,
    *,
    notes: NotesConfig | None = None,
    trace_logger: TraceLogger | None = None,
) -> SessionFactory:
    """Apply complete-logical-turn governance in its explicit order."""
    usage_cost = build_usage_cost()
    budget = None
    if settings.max_budget_usd is not None:
        if usage_cost is None:
            raise ValueError(
                "a budget requires CODEX_USD_PER_MTOK_INPUT and "
                "CODEX_USD_PER_MTOK_OUTPUT"
            )
        budget = BudgetConfig(
            maximum_usd=settings.max_budget_usd,
            usage_cost=usage_cost,
        )
    timeout = (
        TimeoutConfig(seconds=settings.turn_timeout_seconds)
        if settings.turn_timeout_seconds is not None
        else None
    )
    persistence = None
    tracing = None
    display = None
    if notes is not None and trace_logger is not None:
        from lup.telemetry.display import ColorAssigner, print_block
        from lup.telemetry.trace import TraceEvent

        colors = ColorAssigner()

        async def display_result(record: DisplayRecord) -> None:
            for block in record.blocks:
                print_block(
                    telemetry_block(block),
                    trace=trace_logger,
                    colors=colors,
                )

        async def trace_result(record: TraceRecord) -> None:
            if not record.succeeded and record.failure is not None:
                for block in record.failure.blocks:
                    trace_logger.log_block(telemetry_block(block))
                trace_logger.log_text(record.failure.message, heading="Turn error")
                trace_logger.emit_event(
                    TraceEvent(
                        kind="error",
                        timestamp=datetime.now().isoformat(),
                        brief=record.failure.message,
                    )
                )
            trace_logger.save()

        persistence = PersistenceConfig(directory=notes.trace_log.parent / "turns")
        tracing = TracingConfig(sink=trace_result)
        display = DisplayConfig(sink=display_result)
    return DecoratingSessionFactory(
        factory,
        timeout=timeout,
        budget=budget,
        correction=CorrectionConfig(cycles=2),
        persistence=persistence,
        tracing=tracing,
        display=display,
    )


def telemetry_block(block: TurnBlock) -> LupContentBlock:
    """Project one portable completed block into the existing telemetry view."""
    match block:
        case TurnTextBlock(text=text):
            return LupTextBlock(text=text)
        case TurnThinkingBlock(thinking=thinking, redacted=redacted):
            return LupThinkingBlock(thinking=thinking, redacted=redacted)
        case TurnToolCallBlock(id=identifier, name=name, arguments=arguments):
            return LupToolUseBlock(id=identifier, name=name, input=arguments)
        case TurnToolResultBlock(
            tool_call_id=identifier, content=content, is_error=is_error
        ):
            rendered = (
                json.dumps({"is_error": True, "content": content})
                if is_error
                else content
            )
            return LupToolResultBlock(tool_use_id=identifier, content=rendered)


def build_session_factory(
    session_id: str,
    task_id: str | None = None,
    *,
    realtime: bool = False,
    model: str | None = None,
    toolless: bool = False,
    bare_prompt: bool = False,
) -> SessionBuild:
    """Assemble tools and return a fully configured neutral factory."""
    from lup.hooks import (
        create_permission_hooks,
        create_tool_allowlist_hook,
        merge_hooks,
    )
    from lup.mcp import create_mcp_server
    from lup.realtime.relay import REALTIME_DIRNAME
    from lup_template.agent.tool_policy import ToolPolicy
    from lup_template.agent.subagents import get_subagent_specs
    from lup_template.agent.toolsets import EXAMPLE_GROUP, build_session_toolset

    notes = setup_notes(session_id, task_id or "0")
    no_subagents: list[SubagentSpec] = []
    subagents = no_subagents if toolless else get_subagent_specs()
    system_prompt = "" if bare_prompt else get_system_prompt()
    tool_servers: dict[str, McpServerEntry] = {}
    codex_mcp_servers: dict[str, CodexMcpServerConfig] = {}
    writable_roots: list[Path] = []
    allowed_tools: list[str] = []
    submission_gate: SubmissionGate[AgentOutput] | None = None
    hooks = create_permission_hooks(notes.rw, notes.ro)
    tools: list[str] | None = [] if toolless else None  # lup: ignore[empty-collection]
    sandbox: Sandbox | None = None
    if not toolless and settings.agent_sdk in ("claude", "claude-compat"):
        policy = ToolPolicy(settings)
        realtime_dir = notes.session / REALTIME_DIRNAME if realtime else None
        sandbox = build_session_sandbox(notes)
        toolset = build_session_toolset(
            session_dir=notes.session,
            outputs_dir=notes.output.parent,
            sandbox=sandbox,
            realtime_dir=realtime_dir,
        )
        servers = [
            create_mcp_server(name, tools=policy.filter_tools(group_tools))
            for name, group_tools in toolset["groups"].items()
            if name != EXAMPLE_GROUP
        ]
        tool_servers = dict(policy.get_mcp_servers(*servers))
        allowed_tools = policy.get_allowed_tools(
            tool_servers,
            builtin_tools=frozenset(  # lup: ignore[frozenset-shape] — immutable policy input
                {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "Bash"}
            ),
        )
        hooks = merge_hooks(hooks, create_tool_allowlist_hook(allowed_tools))
        submission_gate = reflection_submission_gate(toolset["gate"])
    elif not toolless:
        from lup.reflect import ReviewGate
        from lup.workspace.context import SessionContext
        from lup_template.agent.toolsets import tool_group_names

        policy = ToolPolicy(settings)
        realtime_dir = notes.session / REALTIME_DIRNAME if realtime else None
        gate = ReviewGate(flag_path=notes.trace_log.with_suffix(".reflection"))
        submission_gate = reflection_submission_gate(gate)
        context = SessionContext(
            session_dir=notes.session,
            outputs_dir=notes.output.parent,
            gate_flag=gate.flag_path,
            session_id=notes.session.name,
            task_id=notes.output.parent.name,
            realtime_dir=realtime_dir,
        )
        environment = {
            **context.to_env(),
            "AGENT_SDK": settings.agent_sdk,
            "AGENT_MODEL": model or settings.model,
            "AGENT_SANDBOX_ENABLED": str(settings.sandbox_enabled).lower(),
        }
        if settings.aux_model is not None:
            environment["AGENT_AUX_MODEL"] = settings.aux_model
        codex_mcp_servers = {
            name: CodexMcpServerConfig(
                command="uv",
                args=[
                    "run",
                    "lup-devtools",
                    "agent",
                    "serve-tools",
                    "--server",
                    name,
                ],
                env=environment,
            )
            for name in policy.filter_group_names(tool_group_names(realtime=realtime))
        }
        writable_roots = list(notes.rw)

    resolver = (
        submission_gate_resolver(AgentOutput, submission_gate)
        if submission_gate is not None
        else None
    )
    factory = provider_factory(
        model=model or settings.model,
        system_prompt=system_prompt,
        cwd=Path.cwd(),
        tools=tools,
        tool_servers=tool_servers,
        allowed_tools=allowed_tools,
        hooks=hooks,
        add_dirs=[*notes.all_dirs, *settings.extra_dirs],
        coding_harness_preset=not bare_prompt,
        submission_gate=resolver,
        codex_mcp_servers=codex_mcp_servers,
        writable_roots=writable_roots,
        subagents=subagents,
    )
    if sandbox is not None:
        factory = CleaningSessionFactory(factory, sandbox.stop)
    elif (
        not toolless
        and settings.sandbox_enabled
        and settings.agent_sdk
        in (
            "codex",
            "openai",
            "openai-compat",
        )
    ):
        factory = CleaningSessionFactory(factory, codex_sandbox_cleanup(notes))
    trace_logger = TraceLogger(
        trace_path=notes.trace_log,
        title=f"Session {session_id}",
    )
    return SessionBuild(
        factory=decorate_factory(
            factory,
            notes=notes,
            trace_logger=trace_logger,
        ),
        notes=notes,
        trace_logger=trace_logger,
    )


def build_auxiliary_factory(
    *,
    model: str,
    system_prompt: str = "",
    tools: list[str] | None = None,
) -> SessionFactory:
    """Build a one-shot nested/reviewer factory through the same route."""
    return decorate_factory(
        provider_factory(
            model=model,
            system_prompt=system_prompt,
            cwd=Path.cwd(),
            tools=tools,
            allowed_tools=tools,
            coding_harness_preset=False,
            session_defaults=False,
        )
    )


def resolve_resume_token(reference: str) -> SessionId:
    """Resolve a saved run name or accept an opaque provider session id."""
    from lup.workspace.history import latest_session_record

    record = latest_session_record(reference)
    if record is None:
        return SessionId(value=reference)
    if not record.sdk_session_id:
        raise ValueError(f"session {reference!r} has no provider resume identity")
    return SessionId(value=record.sdk_session_id)


def result_text[T: BaseModel | None](result: TurnResult[T]) -> str:
    """Concatenate completed portable text blocks."""
    return "\n\n".join(
        block.text for block in result.blocks if isinstance(block, TurnTextBlock)
    )


def result_sources[T: BaseModel | None](result: TurnResult[T]) -> list[str]:
    """Extract source URLs and search queries from semantic tool calls."""
    sources: list[str] = []  # lup: ignore[empty-collection]
    for block in result.blocks:
        if not isinstance(block, TurnToolCallBlock):
            continue
        if block.name in ("FetchUrl", "WebFetch"):
            value = block.arguments.get("url")  # lup: ignore[dict-get]
        elif block.name in ("SearchWeb", "WebSearch"):
            value = block.arguments.get("query")  # lup: ignore[dict-get]
        else:
            continue
        if isinstance(value, str) and value:
            sources.append(value)
    return sources


def application_result(
    result: TurnResult[AgentOutput],
    *,
    session_id: str,
    task_id: str | None,
) -> AgentSessionResult:
    """Project a strict typed turn result into the domain history model."""
    usage_cost = build_usage_cost()
    return AgentSessionResult(
        session_id=session_id,
        task_id=task_id,
        agent_version=agent_version(),
        agent_sdk=settings.agent_sdk,
        sdk_session_id=result.identifiers.session.value,
        timestamp=datetime.now().isoformat(),
        output=result.output,
        reasoning=result_text(result),
        sources_consulted=result_sources(result),
        duration_seconds=result.duration.total_seconds(),
        cost_usd=usage_cost(result.usage) if usage_cost is not None else None,
        token_usage=result.usage,
        tool_metrics=get_metrics_summary(),
    )


async def run_agent(
    task: str,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
    resume: SessionId | None = None,
) -> AgentSessionResult:
    """Run one strict typed turn and persist its application projection."""
    identifier = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    reset_metrics()
    build = build_session_factory(identifier, task_id)
    async with build.factory.open(resume) as handle:
        turn = await handle.session.start(
            turn_request(TurnInput(text=task), AgentOutput)
        )
        result = await turn.turn.result()
    log_metrics_summary()
    projected = application_result(
        result,
        session_id=identifier,
        task_id=task_id,
    )
    save_session(projected, session_id=identifier)
    return projected


async def run_persistent_agent(
    task: str,
    *,
    session_id: str | None = None,
    on_reply: Callable[[str], Awaitable[None]] | None = None,
) -> PersistentSessionResult:
    """Run the relay over the same ``Session`` contract as ordinary turns."""
    from lup.realtime.relay import REALTIME_DIRNAME, RealtimeMailbox, run_relay_session
    from lup.realtime.scheduler import Scheduler
    from lup_template.agent.tools.realtime import MISSING_SLEEP_MESSAGE

    identifier = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    build = build_session_factory(identifier, realtime=True)

    async def echo_reply(message: str) -> None:
        print(f"[lup] {message}")

    scheduler = Scheduler(on_action=on_reply or echo_reply)
    mailbox = RealtimeMailbox(build.notes.session / REALTIME_DIRNAME)
    from lup.reflect import ReflectionGate

    relay_gate = ReflectionGate(
        flag_path=build.notes.trace_log.with_suffix(".reflection")
    )
    async with build.factory.open() as handle:
        turns = await run_relay_session(
            handle.session,
            scheduler=scheduler,
            mailbox=mailbox,
            initial_prompt=task,
            missing_sleep_message=MISSING_SLEEP_MESSAGE,
            gate=relay_gate,
            trace_logger=build.trace_logger,
        )
    return PersistentSessionResult(turns=turns)


def build_session_sandbox(notes: NotesConfig) -> "Sandbox | None":
    """Build the optional application code-execution sandbox lazily."""
    if not settings.sandbox_enabled:
        return None
    try:
        from lup.sandbox.container import Sandbox
    except ImportError:
        logger.warning("docker extra not installed; code execution is unavailable")
        return None
    return Sandbox(
        session_id=notes.session.name,
        shared_dir=notes.session / "sandbox_shared",
        timeout_seconds=settings.sandbox_timeout_seconds,
    )


def codex_sandbox_cleanup(notes: NotesConfig) -> Callable[[], None]:
    """Build parent-side teardown for a sandbox hosted by an MCP subprocess."""

    def cleanup() -> None:
        try:
            from lup.sandbox.container import sandbox_cleanup

            with sandbox_cleanup(
                session_id=notes.session.name,
                shared_dir=notes.session / "sandbox_shared",
            ):
                pass
        except Exception:
            logger.exception("Post-session Codex sandbox cleanup failed")

    return cleanup
