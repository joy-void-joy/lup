"""The ``codex`` engine: the OpenAI Codex runtime behind the neutral seam.

Runs OpenAI models on the Codex app-server. The runtime is a subprocess,
so tools are served externally (``served_tool_groups``), writes are
confined natively (``writable_roots``), and persistent mode rides the
file-relay mailbox. Five sections, in order:

- construction — :func:`create_codex` and the session's sandbox cleanup
  guarantee;
- SDK adaptation — thread-item and usage conversion into lup types, and
  the ``config_overrides`` builders (MCP servers, native sandbox, hooks);
- sessions and clients — :class:`CodexSession` and :class:`CodexClient`,
  the run path;
- hook codegen — lup hook policies rendered as standalone Codex
  command-hook scripts. Quarantined: a live probe showed config.toml
  command hooks never fire on the Codex builds this project targets, so
  no live adapter wires it — enforcement is the native workspace-write
  sandbox (:func:`build_sandbox_config_overrides`) — and the section is
  kept as the wire-format reference, imported only by tests.

``openai-compat`` (:mod:`lup.adapters.clients.openai_compat`) fronts any
OpenAI-protocol endpoint through this same runtime. The Codex SDK is
imported as a qualified namespace (``codex`` for the package,
``codex_items`` for its generated item types) so every SDK type reads
with its origin visible.
"""

import asyncio
import importlib.util
import json
import logging
import sys
import time
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import (
    AbstractContextManager,
    asynccontextmanager,
    nullcontext,
)
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict

from lup.adapters.clients.Client import (
    Client,
    Session,
    query_via_session,
    refuse_unconsumed,
    replay_stream,
    safe_normalize_usage,
)
from lup.adapters.common import (
    BudgetExceededError,
    LupAgentOptions,
    TurnTimeoutError,
    UnsupportedOperationError,
)
from lup.adapters.tools.claude import WEB_SEARCH
from lup.hooks import LupHooksConfig
from lup.realtime.relay import RealtimeMailbox
from lup.telemetry.display import print_message
from lup.telemetry.trace import TraceLogger
from lup.types import (
    JsonObject,
    LupAssistantMessage,
    LupContentBlock,
    LupEvent,
    LupResponse,
    LupResultMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
    Usage,
    UsageCost,
)

if TYPE_CHECKING:
    import openai_codex as codex
    import openai_codex.generated.v2_all as codex_items

logger = logging.getLogger(__name__)

CODEX_EFFORT_MAP: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}


def codex_effort(reasoning_effort: str | None) -> str | None:
    """Map a generic effort level to the Codex runtime's ``ReasoningEffort``.

    An unrecognized level passes through unchanged for the enum to reject.
    """
    if reasoning_effort is None:
        return None
    return CODEX_EFFORT_MAP.get(reasoning_effort, reasoning_effort)


def subprocess_sandbox_cleanup(
    opts: LupAgentOptions,
) -> AbstractContextManager[object]:
    """Guarantee the session's subprocess sandbox container dies on exit.

    The Codex/OpenAI tool subprocess may be killed before it can clean up its
    own container; the parent removes it. A no-op without the docker extra, or
    when the build names no session.
    """
    if opts.session_id is None or opts.shared_dir is None:
        return nullcontext()
    try:
        from lup.sandbox.container import sandbox_cleanup
    except ImportError:
        return nullcontext()
    return sandbox_cleanup(session_id=opts.session_id, shared_dir=opts.shared_dir)


def budget_if_priced(opts: LupAgentOptions) -> float | None:
    """The budget cap, read only when a ``usage_cost`` makes it enforceable.

    Reading ``max_budget_usd`` solely under a present ``usage_cost`` is what
    makes the codex engines refuse an unpriced budget: with no estimator the
    read never happens, so consume-tracking sees the knob unconsumed and
    flags it. The Codex runtime reports token counts, never cost, so a
    budget with nothing to price it against cannot be enforced.
    """
    if opts.usage_cost is not None:
        return opts.max_budget_usd
    return None


def build_codex_client(opts: LupAgentOptions) -> "CodexClient":
    """Translate neutral options into a configured :class:`CodexClient`.

    Reads the knobs the runtime honors — ``reasoning_effort``,
    ``turn_timeout_seconds``, and ``max_budget_usd`` (only when priced by
    ``usage_cost``) — and leaves ``max_turns``/``max_thinking_tokens``/
    ``permission_mode``/``tools`` unread, which is how they come to be
    refused: the runtime has no per-session turn cap, thinking budget,
    permission mode, or builtin-toolset restriction.
    """
    return CodexClient(
        model=opts.model,
        system_prompt=opts.system_prompt,
        output_schema=opts.output_schema,
        sandbox=opts.codex_sandbox,
        effort=opts.reasoning_effort,
        approval_policy=opts.approval_policy,
        mcp_tools=bool(opts.served_tool_groups),
        mcp_env=dict(opts.mcp_env),
        writable_roots=list(opts.writable_roots),
        mcp_servers=opts.served_tool_groups,
        max_budget_usd=budget_if_priced(opts),
        usage_cost=opts.usage_cost,
        turn_timeout_seconds=opts.turn_timeout_seconds,
        cleanup=subprocess_sandbox_cleanup(opts),
    )


def create_codex(options: LupAgentOptions) -> Client:
    """Build a Codex-runtime client from neutral options.

    Consumes the subprocess mechanism payloads (served tool groups, env
    relay, writable roots) and ignores the in-process ones (hooks, tool
    servers — enforcement here is the runtime's native sandbox) and the
    Claude-only ``coding_harness_preset``/``sdk_sandbox`` shape flags. Subagent
    specs are served through the ``run_subagent`` tool group rather than
    run natively. Persistent mode surfaces the file-relay mailbox.
    """
    client = refuse_unconsumed("codex", options, build_codex_client)
    if options.realtime and options.realtime_dir is not None:
        client.mailbox = RealtimeMailbox(options.realtime_dir)
    return client


def require_codex_sdk() -> None:
    """Raise a clear error if the Codex SDK is not installed."""
    if importlib.util.find_spec("openai_codex") is None:
        raise ImportError("Codex SDK not installed. Install with: uv add openai-codex")


def codex_items_to_lup(
    items: "Sequence[codex_items.ThreadItem]",
) -> list[LupContentBlock]:
    """Convert Codex ThreadItem list into lup content blocks.

    Each ThreadItem is a RootModel wrapping a discriminated union.
    We extract ``.root`` to get the typed variant, then map by
    ``type`` field.
    """
    import openai_codex.generated.v2_all as codex_items

    blocks: list[LupContentBlock] = []
    for item in items:
        inner = item.root if hasattr(item, "root") else item

        match inner:
            case codex_items.AgentMessageThreadItem():
                if inner.phase == codex_items.MessagePhase.final_answer:
                    blocks.append(LupTextBlock(text=inner.text))
                else:
                    blocks.append(LupThinkingBlock(thinking=inner.text))

            case codex_items.ReasoningThreadItem():
                summary = "\n".join(inner.summary) if inner.summary else ""
                content = "\n".join(inner.content) if inner.content else ""
                blocks.append(LupThinkingBlock(thinking=content or summary))

            case codex_items.CommandExecutionThreadItem():
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name="command_execution",
                        input={"command": inner.command, "cwd": inner.cwd.root},
                    )
                )
                if inner.aggregated_output is not None or inner.exit_code is not None:
                    blocks.append(
                        LupToolResultBlock(
                            tool_use_id=inner.id,
                            content=inner.aggregated_output,
                        )
                    )

            case codex_items.McpToolCallThreadItem():
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name=f"mcp__{inner.server}__{inner.tool}",
                        input=inner.arguments
                        if isinstance(inner.arguments, dict)
                        else None,
                    )
                )
                result_text: str | None = None
                if inner.error is not None:
                    result_text = (
                        inner.error.message
                        if hasattr(inner.error, "message")
                        else str(inner.error)
                    )
                elif inner.result is not None:
                    result_text = (
                        json.dumps(inner.result.content)
                        if hasattr(inner.result, "content")
                        else str(inner.result)
                    )
                if result_text is not None:
                    blocks.append(
                        LupToolResultBlock(
                            tool_use_id=inner.id,
                            content=result_text,
                        )
                    )

            case codex_items.FileChangeThreadItem():
                changes_desc = "; ".join(f"{c.path} ({c.kind})" for c in inner.changes)
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name="file_change",
                        input={"changes": changes_desc},
                    )
                )
                diff_text = "\n".join(c.diff for c in inner.changes if c.diff)
                if diff_text:
                    blocks.append(
                        LupToolResultBlock(
                            tool_use_id=inner.id,
                            content=diff_text,
                        )
                    )

            case codex_items.WebSearchThreadItem():
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name=WEB_SEARCH,
                        input={"query": inner.query},
                    )
                )

            case _:
                item_type = getattr(inner, "type", type(inner).__name__)
                logger.warning(
                    "codex_items_to_lup: unhandled ThreadItem variant %r (%s); "
                    "emitting diagnostic text block",
                    item_type,
                    type(inner).__name__,
                )
                blocks.append(LupTextBlock(text=f"[unhandled codex item: {item_type}]"))

    return blocks


def build_mcp_config_overrides(
    serve_tools_command: str = "uv",
    serve_tools_args: list[str] | None = None,
    env: dict[str, str] | None = None,
    servers: Sequence[str] = ("notes", "sandbox"),
) -> list[str]:
    """Build config_overrides for lup MCP tools via serve-tools.

    The Codex app-server is a Rust subprocess with no in-process tool
    registration. Tools must be configured as external MCP servers via
    TOML config. This generates the config_overrides that point Codex
    at the lup-devtools serve-tools command.

    One entry is emitted per server group so tool names match the
    Claude path exactly (``mcp__notes__submit_output``,
    ``mcp__sandbox__execute_code``); each subprocess serves one group
    via ``serve-tools --server <name>``.

    Args:
        serve_tools_command: Executable that launches the tool server.
        serve_tools_args: Base arguments for the launcher (the
            ``--server <name>`` selector is appended per group).
        env: Session-context env vars for the subprocesses (see
            :class:`lup.workspace.context.SessionContext`).
        servers: Server groups to register.
    """
    base_args = serve_tools_args or ["run", "lup-devtools", "agent", "serve-tools"]
    overrides: list[str] = []
    for name in servers:
        args = [*base_args, "--server", name]
        overrides.append(f'mcp_servers.{name}.command="{serve_tools_command}"')
        overrides.append(f"mcp_servers.{name}.args={json.dumps(args)}")
        for key, value in (env or {}).items():
            overrides.append(f'mcp_servers.{name}.env.{key}="{value}"')
    return overrides


def build_sandbox_config_overrides(writable_roots: Sequence[Path]) -> list[str]:
    """Native Codex filesystem enforcement via workspace-write sandbox.

    Replaces hook-script permission enforcement on Codex: the runtime's
    own sandbox confines writes to the workspace plus these roots. (A
    live probe showed config.toml command hooks never fire on current
    codex builds, so enforcement must be native or in-tool.)
    """
    roots_json = json.dumps([str(p) for p in writable_roots])
    return [
        'sandbox_mode="workspace-write"',
        f"sandbox_workspace_write.writable_roots={roots_json}",
    ]


class CodexHookConfigRequired(TypedDict):
    """Required fields for a Codex command hook."""

    event: str
    command: str


class CodexHookConfig(CodexHookConfigRequired, total=False):
    """Configuration for a single Codex command hook."""

    matcher: str


def build_hook_config_overrides(
    hooks: list[CodexHookConfig],
) -> list[str]:
    """Build config_overrides for Codex command hooks.

    Each hook dict has: event, matcher (optional), command.
    Generates TOML-style config_overrides for the Codex hook system.
    """
    overrides: list[str] = []
    overrides.append("features.codex_hooks=true")

    event_counts: dict[str, int] = {}
    for hook in hooks:
        event = hook["event"]
        idx = event_counts.get(event, 0)
        event_counts[event] = idx + 1

        if "matcher" in hook:
            overrides.append(f'hooks.{event}[{idx}].matcher="{hook["matcher"]}"')
        overrides.append(f'hooks.{event}[{idx}].hooks[0].type="command"')
        overrides.append(f'hooks.{event}[{idx}].hooks[0].command="{hook["command"]}"')

    return overrides


type CodexUsageNormalizer = Callable[["codex_items.ThreadTokenUsage"], Usage | None]
"""Transforms the Codex SDK usage object into a (subclass of) Usage."""


def per_mtok_usage_cost(
    *,
    input_usd: float,
    output_usd: float,
    cached_input_usd: float | None = None,
) -> UsageCost:
    """Build a usage→USD estimator from per-million-token rates.

    The Codex runtime reports token counts, never cost — budget
    enforcement needs the caller to supply pricing. Cached input tokens
    are treated as a subset of ``input_tokens`` (OpenAI-style usage
    reporting); when ``cached_input_usd`` is given, that subset is
    billed at the cached rate instead of the input rate.
    """

    def cost(usage: Usage) -> float:
        cached = usage.cache_read_input_tokens
        uncached = max(usage.input_tokens - cached, 0)
        cached_rate = input_usd if cached_input_usd is None else cached_input_usd
        return (
            uncached * input_usd
            + cached * cached_rate
            + usage.output_tokens * output_usd
        ) / 1_000_000

    return cost


def codex_usage_to_lup(usage: "codex_items.ThreadTokenUsage") -> Usage | None:
    """Default Codex usage normalizer — portable token counts only."""
    total = usage.total
    return Usage(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cache_read_input_tokens=total.cached_input_tokens,
    )


def build_lup_response(
    result: "codex.TurnResult",
    *,
    output_schema: JsonObject | None = None,
    session_id: str | None = None,
    trace_logger: TraceLogger | None = None,
    prefix: str = "",
    usage_normalizer: CodexUsageNormalizer | None = None,
) -> LupResponse:
    """Convert a Codex TurnResult into a LupResponse."""

    blocks = codex_items_to_lup(result.items)
    response = LupResponse(blocks=blocks)

    for block in blocks:
        if isinstance(block, LupToolResultBlock):
            response.tool_results.append(block)

    assistant_blocks: list[LupContentBlock] = [
        b for b in blocks if not isinstance(b, LupToolResultBlock)
    ]
    result_blocks: list[LupContentBlock] = [
        b for b in blocks if isinstance(b, LupToolResultBlock)
    ]
    if assistant_blocks:
        response.messages.append(LupAssistantMessage(content=assistant_blocks))
    if result_blocks:
        response.messages.append(LupUserMessage(content=result_blocks))

    if trace_logger:
        for block in blocks:
            trace_logger.log_block(block)
        lup_msg = LupAssistantMessage(content=blocks)
        print_message(lup_msg, prefix=prefix)

    structured_output: JsonObject | None = None
    if result.final_response and output_schema:
        try:
            structured_output = json.loads(result.final_response)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "Codex structured-output parse failed; final_response was not "
                "JSON matching the schema. Offending text (truncated): %r",
                result.final_response[:500],
            )

    result_usage = safe_normalize_usage(
        usage_normalizer or codex_usage_to_lup, result.usage
    )

    response.result = LupResultMessage(
        structured_output=structured_output,
        result=result.final_response,
        usage=result_usage,
    )
    response.session_id = session_id
    return response


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


class CodexClient(Client):
    """Run prompts via the OpenAI Codex SDK."""

    model_provider: str | None = None
    """Codex model-provider selector — set by the OpenAI-compatible
    subclass; ``None`` runs on the account's default provider."""

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str,
        output_schema: JsonObject | None = None,
        sandbox: str | None = None,
        effort: str | None = None,
        approval_policy: str | None = None,
        mcp_tools: bool = True,
        mcp_env: dict[str, str] | None = None,
        writable_roots: list[Path] | None = None,
        hook_overrides: list[CodexHookConfig] | None = None,
        usage_normalizer: CodexUsageNormalizer | None = None,
        mcp_servers: Sequence[str] = ("notes", "sandbox"),
        max_budget_usd: float | None = None,
        usage_cost: UsageCost | None = None,
        turn_timeout_seconds: float | None = None,
        cleanup: AbstractContextManager[object] | None = None,
    ) -> None:
        if max_budget_usd is not None and usage_cost is None:
            raise ValueError(
                "max_budget_usd on the Codex runtime requires a usage_cost "
                "estimator — the SDK reports token counts, not cost. Build "
                "one with per_mtok_usage_cost(...)."
            )
        self.model = model
        self.system_prompt = system_prompt
        self.output_schema = output_schema
        self.sandbox = sandbox
        self.effort = effort
        self.approval_policy = approval_policy
        self.mcp_tools = mcp_tools
        self.mcp_env = mcp_env
        self.writable_roots = writable_roots
        self.hook_overrides = hook_overrides
        self.usage_normalizer = usage_normalizer
        self.mcp_servers = mcp_servers
        self.max_budget_usd = max_budget_usd
        self.usage_cost = usage_cost
        self.turn_timeout_seconds = turn_timeout_seconds
        self.cleanup = cleanup

    def build_config_overrides(self) -> list[str]:
        """Assemble all config_overrides for this adapter run."""
        overrides: list[str] = []
        if self.mcp_tools:
            overrides.extend(
                build_mcp_config_overrides(env=self.mcp_env, servers=self.mcp_servers)
            )
        if self.writable_roots:
            overrides.extend(build_sandbox_config_overrides(self.writable_roots))
        if self.hook_overrides:
            overrides.extend(build_hook_config_overrides(self.hook_overrides))
        return overrides

    def make_session(self, thread: "codex.AsyncThread") -> CodexSession:
        """Wrap a thread in a conversation carrying this client's settings.

        The single construction point for the send path, shared with the
        OpenAI-compatible subclass so both inherit identical effort,
        output-schema, and budget wiring.
        """
        return CodexSession(
            thread,
            output_schema=self.output_schema,
            effort=self.effort,
            usage_normalizer=self.usage_normalizer,
            max_budget_usd=self.max_budget_usd,
            usage_cost=self.usage_cost,
            turn_timeout_seconds=self.turn_timeout_seconds,
        )

    def codex_config(self) -> "codex.CodexConfig":
        """Assemble the runtime config — the compat subclass adds provider env."""
        import openai_codex as codex

        return codex.CodexConfig(config_overrides=tuple(self.build_config_overrides()))

    async def open_thread(
        self, codex_client: "codex.AsyncCodex", *, resume: str | None
    ) -> "codex.AsyncThread":
        """Start the session's thread, or restore a saved one."""
        import openai_codex as codex

        sandbox = codex.Sandbox(self.sandbox) if self.sandbox else None
        approval_mode = (
            codex.ApprovalMode(self.approval_policy)
            if self.approval_policy
            else codex.ApprovalMode.auto_review
        )
        if resume is not None:
            return await codex_client.thread_resume(
                resume,
                model=self.model,
                model_provider=self.model_provider,
                developer_instructions=self.system_prompt,
                sandbox=sandbox,
                approval_mode=approval_mode,
            )
        return await codex_client.thread_start(
            model=self.model,
            model_provider=self.model_provider,
            developer_instructions=self.system_prompt,
            sandbox=sandbox,
            approval_mode=approval_mode,
        )

    @asynccontextmanager
    async def session(
        self, *, resume: str | None = None
    ) -> AsyncGenerator[Session, None]:
        require_codex_sdk()

        import openai_codex as codex

        with self.cleanup if self.cleanup is not None else nullcontext():
            async with codex.AsyncCodex(config=self.codex_config()) as codex_client:
                thread = await self.open_thread(codex_client, resume=resume)
                yield self.make_session(thread)

    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        return await query_via_session(
            self, prompt, trace_logger=trace_logger, prefix=prefix
        )

    def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        return replay_stream(self, prompt, trace_logger=trace_logger, prefix=prefix)


class CodexHookInput(TypedDict, total=False):
    """Input JSON received by Codex hook scripts on stdin."""

    hook_event_name: str
    tool_name: str
    tool_input: dict[str, str]


class CodexHookOutput(TypedDict, total=False):
    """Output JSON emitted by Codex hook scripts to stdout."""

    decision: Literal["allow", "deny", "block"]
    reason: str
    systemMessage: str


def format_codex_hook_output(
    decision: Literal["allow", "deny", "block"],
    reason: str = "",
) -> CodexHookOutput:
    """Format a hook decision as Codex-compatible JSON."""
    output = CodexHookOutput(decision=decision)
    if reason:
        output["reason"] = reason
    return output


def read_hook_input() -> CodexHookInput:
    """Read hook input JSON from stdin (used by hook scripts)."""
    raw = sys.stdin.read()
    return json.loads(raw)


def write_hook_output(output: CodexHookOutput) -> None:
    """Write hook output JSON to stdout (used by hook scripts)."""
    sys.stdout.write(json.dumps(output))
    sys.stdout.flush()


def build_permission_hooks(
    rw_dirs: list[Path],
    ro_dirs: list[Path],
    script_dir: Path,
) -> list[CodexHookConfig]:
    """Generate Codex hook configs for directory-based permission control.

    Creates a PreToolUse hook config that runs a permission check script.
    The script path must be written to disk separately (see
    write_permission_hook_script).

    Args:
        rw_dirs: Directories where Write/Edit/Read are allowed.
        ro_dirs: Additional directories where only Read is allowed.
        script_dir: Directory where hook scripts will be written.

    Returns:
        List of CodexHookConfig entries for config_overrides.
    """
    script_path = script_dir / "codex_permission_hook.py"
    write_permission_hook_script(script_path, rw_dirs, ro_dirs)

    return [
        CodexHookConfig(
            event="PreToolUse",
            command=f"python3 {script_path}",
        ),
    ]


def write_permission_hook_script(
    script_path: Path,
    rw_dirs: list[Path],
    ro_dirs: list[Path],
) -> None:
    """Write a standalone permission hook script to disk.

    The script reads CodexHookInput from stdin, checks directory
    permissions, and writes CodexHookOutput to stdout.
    """
    rw_list = json.dumps([str(d) for d in rw_dirs])
    ro_list = json.dumps([str(d) for d in ro_dirs])

    script = f'''\
"""Auto-generated Codex permission hook script."""
import json
import sys
from pathlib import Path

RW_DIRS = [Path(p) for p in {rw_list}]
RO_DIRS = [Path(p) for p in {ro_list}]
ALL_READABLE = RW_DIRS + RO_DIRS


def path_is_under(file_path: str, dirs: list[Path]) -> bool:
    p = Path(file_path).resolve()
    return any(p == d or d in p.parents for d in dirs)


def check_permission(hook_input: dict) -> dict:
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {{}})

    match tool_name:
        case "Write" | "Edit":
            file_path = tool_input.get("file_path", "")
            if not file_path:
                return {{"decision": "allow"}}
            if path_is_under(file_path, RW_DIRS):
                return {{"decision": "allow"}}
            return {{"decision": "deny", "reason": f"{{tool_name}} denied outside RW dirs"}}

        case "Read":
            file_path = tool_input.get("file_path", "")
            if not file_path:
                return {{"decision": "allow"}}
            if path_is_under(file_path, ALL_READABLE):
                return {{"decision": "allow"}}
            return {{"decision": "deny", "reason": "Read denied outside allowed dirs"}}

        case "Glob" | "Grep":
            file_path = tool_input.get("path", "")
            if not file_path:
                return {{"decision": "deny", "reason": f"Path required for {{tool_name}}"}}
            if path_is_under(file_path, ALL_READABLE):
                return {{"decision": "allow"}}
            return {{"decision": "deny", "reason": f"{{tool_name}} denied outside allowed dirs"}}

        case _:
            return {{"decision": "allow"}}


raw = sys.stdin.read()
hook_input = json.loads(raw)
result = check_permission(hook_input)
sys.stdout.write(json.dumps(result))
'''
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")


def build_reflection_gate_hook(
    gate_flag_path: Path,
    gated_tool: str,
    reflection_tool_name: str,
    script_dir: Path,
) -> list[CodexHookConfig]:
    """Generate a Codex hook config for the reflection gate.

    The gate blocks gated_tool until a flag file exists at
    gate_flag_path (set by the reflect tool's MCP handler).

    Args:
        gate_flag_path: Path to the flag file that indicates reflection occurred.
        gated_tool: Tool name to block (e.g., "StructuredOutput").
        reflection_tool_name: Name shown in the denial message.
        script_dir: Directory where hook scripts will be written.

    Returns:
        List of CodexHookConfig entries for config_overrides.
    """
    script_path = script_dir / "codex_reflection_gate_hook.py"
    write_reflection_gate_script(
        script_path, gate_flag_path, gated_tool, reflection_tool_name
    )

    return [
        CodexHookConfig(
            event="PreToolUse",
            matcher=gated_tool,
            command=f"python3 {script_path}",
        ),
    ]


def write_reflection_gate_script(
    script_path: Path,
    gate_flag_path: Path,
    gated_tool: str,
    reflection_tool_name: str,
) -> None:
    """Write a standalone reflection gate hook script to disk."""
    script = f'''\
"""Auto-generated Codex reflection gate hook script."""
import json
import sys
from pathlib import Path

GATE_FLAG = Path("{gate_flag_path}")
GATED_TOOL = "{gated_tool}"
REFLECTION_TOOL = "{reflection_tool_name}"

raw = sys.stdin.read()
hook_input = json.loads(raw)
tool_name = hook_input.get("tool_name", "")

if tool_name == GATED_TOOL and not GATE_FLAG.exists():
    result = {{
        "decision": "deny",
        "reason": f"You must call {{REFLECTION_TOOL}}() before {{GATED_TOOL}}. Reflect first.",
    }}
else:
    result = {{"decision": "allow"}}

sys.stdout.write(json.dumps(result))
'''
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")


def build_tool_allowlist_hook(
    allowed_tools: list[str],
    script_dir: Path,
) -> list[CodexHookConfig]:
    """Generate a Codex hook config that restricts the agent to allowed tools.

    Equivalent to Claude's :func:`~lup.hooks.create_tool_allowlist_hook`.

    Args:
        allowed_tools: Tool names the agent is allowed to use.
        script_dir: Directory where the hook script will be written.

    Returns:
        List of CodexHookConfig entries for config_overrides.
    """
    script_path = script_dir / "codex_tool_allowlist_hook.py"
    write_tool_allowlist_script(script_path, allowed_tools)

    return [
        CodexHookConfig(
            event="PreToolUse",
            command=f"python3 {script_path}",
        ),
    ]


def write_tool_allowlist_script(
    script_path: Path,
    allowed_tools: list[str],
) -> None:
    """Write a standalone tool allowlist hook script to disk."""
    tools_json = json.dumps(allowed_tools)

    script = f'''\
"""Auto-generated Codex tool allowlist hook script."""
import json
import sys

ALLOWED_TOOLS = set({tools_json})

raw = sys.stdin.read()
hook_input = json.loads(raw)
tool_name = hook_input.get("tool_name", "")

if tool_name in ALLOWED_TOOLS:
    result = {{"decision": "allow"}}
else:
    result = {{"decision": "deny", "reason": f"Tool '{{tool_name}}' not in allowed list."}}

sys.stdout.write(json.dumps(result))
'''
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")


def build_nudge_hook(
    nudges: dict[str, str],
    script_dir: Path,
) -> list[CodexHookConfig]:
    """Generate a Codex PostToolUse hook that nudges the agent toward alternatives.

    Equivalent to Claude's :func:`~lup.hooks.create_nudge_hook`, but
    simplified: each nudge is a static message string rather than a callable,
    since Codex hooks are external scripts without access to in-process state.

    Args:
        nudges: Mapping of tool_name to nudge message. When the tool runs,
            the message is injected as a systemMessage.
        script_dir: Directory where the hook script will be written.

    Returns:
        List of CodexHookConfig entries for config_overrides.
    """
    script_path = script_dir / "codex_nudge_hook.py"
    write_nudge_script(script_path, nudges)

    return [
        CodexHookConfig(
            event="PostToolUse",
            command=f"python3 {script_path}",
        ),
    ]


def write_nudge_script(
    script_path: Path,
    nudges: dict[str, str],
) -> None:
    """Write a standalone nudge hook script to disk."""
    nudges_json = json.dumps(nudges)

    script = f'''\
"""Auto-generated Codex nudge hook script."""
import json
import sys

NUDGES = {nudges_json}

raw = sys.stdin.read()
hook_input = json.loads(raw)
tool_name = hook_input.get("tool_name", "")

nudge_message = NUDGES.get(tool_name)
if nudge_message:
    result = {{"systemMessage": nudge_message}}
else:
    result = {{}}

sys.stdout.write(json.dumps(result))
'''
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script, encoding="utf-8")


def lup_hooks_to_codex(
    hooks: LupHooksConfig,
    script_dir: Path,
    rw_dirs: list[Path] | None = None,
    ro_dirs: list[Path] | None = None,
    gate_flag_path: Path | None = None,
    nudges: dict[str, str] | None = None,
    allowed_tools: list[str] | None = None,
) -> list[CodexHookConfig]:
    """Convert SDK-agnostic LupHooksConfig to Codex hook configs.

    Dispatches on each ``LupHookMatcher.tag`` to generate the correct
    Codex hook script. Unrecognized tags are logged and skipped rather
    than silently dropped.

    Quarantined with the rest of the hook codegen (see the module
    docstring): config.toml command hooks never fire on current Codex
    builds, so do not wire this into a live adapter without re-verifying
    that the runtime honors the generated hooks.

    Args:
        hooks: SDK-agnostic hook configuration.
        script_dir: Directory to write hook scripts.
        rw_dirs: Read-write directories (for permission hooks).
        ro_dirs: Read-only directories (for permission hooks).
        gate_flag_path: Path for reflection gate flag file.
        nudges: Static nudge messages keyed by tool name (for PostToolUse hooks).
        allowed_tools: Tool allowlist (for PreToolUse allowlist hooks).

    Returns:
        List of CodexHookConfig entries for config_overrides.
    """
    configs: list[CodexHookConfig] = []
    seen_tags: set[str] = set()

    for _event_name, matchers in hooks.by_event():
        for matcher in matchers:
            tag = matcher.tag or ""
            if tag in seen_tags:
                continue

            match tag:
                case "permission":
                    if rw_dirs is not None:
                        configs.extend(
                            build_permission_hooks(
                                rw_dirs=rw_dirs,
                                ro_dirs=ro_dirs or [],
                                script_dir=script_dir,
                            )
                        )
                        seen_tags.add(tag)
                    else:
                        logger.warning("permission hook requires rw_dirs")

                case "reflection_gate":
                    if gate_flag_path and matcher.matcher:
                        configs.extend(
                            build_reflection_gate_hook(
                                gate_flag_path=gate_flag_path,
                                gated_tool=matcher.matcher,
                                reflection_tool_name="mcp__notes__review",
                                script_dir=script_dir,
                            )
                        )
                        seen_tags.add(tag)
                    else:
                        logger.warning(
                            "reflection_gate hook requires gate_flag_path and matcher"
                        )

                case "allowlist":
                    if allowed_tools:
                        configs.extend(
                            build_tool_allowlist_hook(
                                allowed_tools=allowed_tools,
                                script_dir=script_dir,
                            )
                        )
                        seen_tags.add(tag)
                    else:
                        logger.warning("allowlist hook requires allowed_tools")

                case "nudge":
                    if nudges:
                        configs.extend(
                            build_nudge_hook(
                                nudges=nudges,
                                script_dir=script_dir,
                            )
                        )
                        seen_tags.add(tag)
                    else:
                        logger.warning("nudge hook requires nudges dict")

                case "capture":
                    logger.info(
                        "capture hook has no Codex equivalent (in-process only)"
                    )

                case _:
                    if tag:
                        logger.warning("Unknown hook tag %r — skipping", tag)

    return configs
