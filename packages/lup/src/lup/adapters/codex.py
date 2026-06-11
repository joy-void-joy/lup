# claude: ignore
"""OpenAI Codex SDK adapter.

Wraps the Codex Python SDK (``openai_codex``) behind the
``AgentAdapter`` interface. Exposes lup MCP tools via external
stdio server (serve-tools), permission hooks via config.toml
command hooks, and the reflection gate via a file-backed flag.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from openai_codex import AsyncThread, TurnResult
    from openai_codex.models import JsonObject

    from openai_codex.generated.v2_all import ThreadItem, ThreadTokenUsage

from lup.adapters.common import (
    AdapterCapabilities,
    AgentAdapter,
    BudgetExceededError,
    Conversation,
)
from lup.trace import TraceLogger, print_message
from lup.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupDoneEvent,
    LupEvent,
    LupResponse,
    LupResultMessage,
    LupTextBlock,
    LupTextEvent,
    LupThinkingBlock,
    LupThinkingEvent,
    LupToolResultBlock,
    LupToolResultEvent,
    LupToolUseBlock,
    LupToolUseEvent,
    LupUserMessage,
    Usage,
    safe_normalize_usage,
)

logger = logging.getLogger(__name__)


def require_codex_sdk() -> None:
    """Raise a clear error if the Codex SDK is not installed."""
    try:
        import openai_codex as _  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Codex SDK not installed. Install with: uv add openai-codex"
        ) from exc


def codex_items_to_lup(items: Sequence[ThreadItem]) -> list[LupContentBlock]:
    """Convert Codex ThreadItem list into lup content blocks.

    Each ThreadItem is a RootModel wrapping a discriminated union.
    We extract ``.root`` to get the typed variant, then map by
    ``type`` field.
    """
    from openai_codex.generated.v2_all import (
        AgentMessageThreadItem,
        CommandExecutionThreadItem,
        FileChangeThreadItem,
        McpToolCallThreadItem,
        MessagePhase,
        ReasoningThreadItem,
        WebSearchThreadItem,
    )

    blocks: list[LupContentBlock] = []
    for item in items:
        inner = item.root if hasattr(item, "root") else item

        match inner:
            case AgentMessageThreadItem():
                if inner.phase == MessagePhase.final_answer:
                    blocks.append(LupTextBlock(text=inner.text))
                else:
                    blocks.append(LupThinkingBlock(thinking=inner.text))

            case ReasoningThreadItem():
                summary = "\n".join(inner.summary) if inner.summary else ""
                content = "\n".join(inner.content) if inner.content else ""
                blocks.append(LupThinkingBlock(thinking=content or summary))

            case CommandExecutionThreadItem():
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

            case McpToolCallThreadItem():
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

            case FileChangeThreadItem():
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

            case WebSearchThreadItem():
                blocks.append(
                    LupToolUseBlock(
                        id=inner.id,
                        name="WebSearch",
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
) -> tuple[str, ...]:
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
            :class:`lup.paths.SessionContext`).
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
    return tuple(overrides)


def build_sandbox_config_overrides(writable_roots: Sequence[Path]) -> tuple[str, ...]:
    """Native Codex filesystem enforcement via workspace-write sandbox.

    Replaces hook-script permission enforcement on Codex: the runtime's
    own sandbox confines writes to the workspace plus these roots. (A
    live probe showed config.toml command hooks never fire on current
    codex builds, so enforcement must be native or in-tool.)
    """
    roots_json = json.dumps([str(p) for p in writable_roots])
    return (
        'sandbox_mode="workspace-write"',
        f"sandbox_workspace_write.writable_roots={roots_json}",
    )


class CodexHookConfigRequired(TypedDict):
    """Required fields for a Codex command hook."""

    event: str
    command: str


class CodexHookConfig(CodexHookConfigRequired, total=False):
    """Configuration for a single Codex command hook."""

    matcher: str


def build_hook_config_overrides(
    hooks: list[CodexHookConfig],
) -> tuple[str, ...]:
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

    return tuple(overrides)


type CodexUsageNormalizer = Callable[[ThreadTokenUsage], Usage | None]
"""Transforms the Codex SDK usage object into a (subclass of) Usage."""

type UsageCost = Callable[[Usage], float]
"""Estimates the USD cost of accumulated token usage."""


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


def codex_usage_to_lup(usage: ThreadTokenUsage) -> Usage | None:
    """Default Codex usage normalizer — portable token counts only."""
    total = usage.total
    return Usage(
        input_tokens=total.input_tokens,
        output_tokens=total.output_tokens,
        cache_read_input_tokens=total.cached_input_tokens,
    )


def build_lup_response(
    result: "TurnResult",
    *,
    output_schema: dict[str, object] | None = None,
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

    structured_output: dict[str, object] | None = None
    if result.final_response and output_schema:
        try:
            structured_output = json.loads(result.final_response)
        except json.JSONDecodeError, TypeError:
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


class CodexConversation(Conversation):
    """Multi-turn conversation via a Codex thread."""

    def __init__(
        self,
        thread: "AsyncThread",
        *,
        output_schema: dict[str, object] | None = None,
        effort: str | None = None,
        usage_normalizer: CodexUsageNormalizer | None = None,
        max_budget_usd: float | None = None,
        usage_cost: UsageCost | None = None,
    ) -> None:
        self.thread = thread
        self.output_schema = output_schema
        self.effort = effort
        self.usage_normalizer = usage_normalizer
        self.max_budget_usd = max_budget_usd
        self.usage_cost = usage_cost
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

    def record_turn_usage(self, usage: "ThreadTokenUsage | None") -> None:
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
        from openai_codex.generated.v2_all import ReasoningEffort

        self.check_budget()
        effort = ReasoningEffort(self.effort) if self.effort else None
        started = time.perf_counter()
        result = await self.thread.run(
            prompt,
            effort=effort,
            output_schema=cast("JsonObject | None", self.output_schema),
        )
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


class CodexAdapter(AgentAdapter):
    """Run prompts via the OpenAI Codex SDK."""

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str,
        output_schema: dict[str, object] | None = None,
        sandbox: str | None = None,
        effort: str | None = None,
        approval_policy: str | None = None,
        mcp_tools: bool = True,
        mcp_env: dict[str, str] | None = None,
        writable_roots: list[Path] | None = None,
        hook_overrides: list[CodexHookConfig] | None = None,
        session_id: str | None = None,
        usage_normalizer: CodexUsageNormalizer | None = None,
        mcp_servers: Sequence[str] = ("notes", "sandbox"),
        max_budget_usd: float | None = None,
        usage_cost: UsageCost | None = None,
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
        self.session_id = session_id
        self.usage_normalizer = usage_normalizer
        self.mcp_servers = mcp_servers
        self.max_budget_usd = max_budget_usd
        self.usage_cost = usage_cost

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            hooks=False,
            native_subagents=False,
            streaming="post_hoc",
            interrupt=False,
            stop_event=False,
            cost_reporting="rates" if self.usage_cost is not None else "none",
            duration_reporting=True,
            permission_modes=False,
            max_turns=False,
            max_thinking_tokens=False,
        )

    def build_config_overrides(self) -> tuple[str, ...]:
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
        return tuple(overrides)

    def make_conversation(self, thread: "AsyncThread") -> CodexConversation:
        """Wrap a thread in a conversation carrying this adapter's settings.

        The single construction point for the send path so resume/fork
        inherit identical effort, output-schema, and budget wiring.
        """
        return CodexConversation(
            thread,
            output_schema=self.output_schema,
            effort=self.effort,
            usage_normalizer=self.usage_normalizer,
            max_budget_usd=self.max_budget_usd,
            usage_cost=self.usage_cost,
        )

    @asynccontextmanager
    async def conversation(self) -> AsyncGenerator[Conversation, None]:
        require_codex_sdk()

        from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

        config_overrides = self.build_config_overrides()
        config = CodexConfig(config_overrides=config_overrides)

        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_start(
                model=self.model,
                developer_instructions=self.system_prompt,
                sandbox=Sandbox(self.sandbox) if self.sandbox else None,
                approval_mode=(
                    ApprovalMode(self.approval_policy)
                    if self.approval_policy
                    else ApprovalMode.auto_review
                ),
            )
            yield self.make_conversation(thread)

    async def resume(self, session_id: str, prompt: str) -> LupResponse:
        """Resume a Codex thread by ID."""
        require_codex_sdk()

        from openai_codex import AsyncCodex, CodexConfig

        config = CodexConfig(config_overrides=self.build_config_overrides())

        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_resume(thread_id=session_id)
            return await self.make_conversation(thread).send(prompt)

    async def fork(self, session_id: str, prompt: str) -> LupResponse:
        """Fork a Codex thread and run on the fork."""
        require_codex_sdk()

        from openai_codex import AsyncCodex, CodexConfig

        config = CodexConfig(config_overrides=self.build_config_overrides())

        async with AsyncCodex(config=config) as codex:
            forked_thread = await codex.thread_fork(thread_id=session_id)
            return await self.make_conversation(forked_thread).send(prompt)

    async def run_streamed(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Yield streaming events from a Codex turn.

        Codex returns completed items (not a real token stream), so this
        converts each item into the corresponding LupEvent after the
        turn finishes.
        """
        response = await self.run(prompt, trace_logger=trace_logger, prefix=prefix)
        for block in response.blocks:
            match block:
                case LupThinkingBlock():
                    yield LupThinkingEvent(thinking=block.thinking)
                case LupTextBlock():
                    yield LupTextEvent(text=block.text)
                case LupToolUseBlock():
                    yield LupToolUseEvent(id=block.id, name=block.name)
                case LupToolResultBlock():
                    yield LupToolResultEvent(
                        tool_use_id=block.tool_use_id,
                        content=str(block.content),
                    )
        yield LupDoneEvent(blocks=response.blocks)
