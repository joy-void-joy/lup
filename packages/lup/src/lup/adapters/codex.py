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
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from openai_codex import AsyncThread, TurnResult
    from openai_codex.models import JsonObject

    from openai_codex.generated.v2_all import ThreadItem, ThreadTokenUsage

from lup.adapters.common import (
    AgentAdapter,
    Conversation,
    LupDoneEvent,
    LupEvent,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
)
from lup.trace import TraceLogger, print_message
from lup.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupResponse,
    LupResultMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
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
            pass

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
    ) -> None:
        self.thread = thread
        self.output_schema = output_schema
        self.effort = effort
        self.usage_normalizer = usage_normalizer

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        from openai_codex.generated.v2_all import ReasoningEffort

        effort = ReasoningEffort(self.effort) if self.effort else None
        result = await self.thread.run(
            prompt,
            effort=effort,
            output_schema=cast("JsonObject | None", self.output_schema),
        )
        return build_lup_response(
            result,
            output_schema=self.output_schema,
            session_id=self.thread.id,
            trace_logger=trace_logger,
            prefix=prefix,
            usage_normalizer=self.usage_normalizer,
        )


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
    ) -> None:
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

    def build_config_overrides(self) -> tuple[str, ...]:
        """Assemble all config_overrides for this adapter run."""
        overrides: list[str] = []
        if self.mcp_tools:
            overrides.extend(build_mcp_config_overrides(env=self.mcp_env))
        if self.writable_roots:
            overrides.extend(build_sandbox_config_overrides(self.writable_roots))
        if self.hook_overrides:
            overrides.extend(build_hook_config_overrides(self.hook_overrides))
        return tuple(overrides)

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
            yield CodexConversation(
                thread,
                output_schema=self.output_schema,
                effort=self.effort,
                usage_normalizer=self.usage_normalizer,
            )

    async def resume(self, session_id: str, prompt: str) -> LupResponse:
        """Resume a Codex thread by ID."""
        require_codex_sdk()

        from openai_codex import AsyncCodex, CodexConfig

        config = CodexConfig(config_overrides=self.build_config_overrides())

        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_resume(thread_id=session_id)
            result = await thread.run(prompt)
            return build_lup_response(
                result,
                output_schema=self.output_schema,
                session_id=session_id,
                usage_normalizer=self.usage_normalizer,
            )

    async def fork(self, session_id: str, prompt: str) -> LupResponse:
        """Fork a Codex thread and run on the fork."""
        require_codex_sdk()

        from openai_codex import AsyncCodex, CodexConfig

        config = CodexConfig(config_overrides=self.build_config_overrides())

        async with AsyncCodex(config=config) as codex:
            forked_thread = await codex.thread_fork(thread_id=session_id)
            result = await forked_thread.run(prompt)
            return build_lup_response(
                result,
                output_schema=self.output_schema,
                session_id=forked_thread.id,
                usage_normalizer=self.usage_normalizer,
            )

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
