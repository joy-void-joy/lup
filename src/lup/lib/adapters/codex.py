"""OpenAI Codex SDK adapter.

Wraps the Codex Python SDK (``codex_app_server``) behind the
``AgentAdapter`` interface. Exposes lup MCP tools via external
stdio server (serve-tools), permission hooks via config.toml
command hooks, and the reflection gate via a file-backed flag.

Install the Codex SDK to use this adapter::

    uv sync --extra codex
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from codex_app_server import ThreadItem
    from codex_app_server.models import JsonObject

from lup.lib.adapters.common import AgentAdapter
from lup.lib.trace import TraceLogger, print_message
from lup.lib.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupResponse,
    LupResultMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
)

logger = logging.getLogger(__name__)


def require_codex_sdk() -> None:
    """Raise a clear error if the Codex SDK is not installed."""
    try:
        import codex_app_server as _  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Codex SDK not installed. Install with: uv sync --extra codex"
        ) from exc


def codex_items_to_lup(items: Sequence[ThreadItem]) -> list[LupContentBlock]:
    """Convert Codex ThreadItem list into lup content blocks.

    Each ThreadItem is a RootModel wrapping a discriminated union.
    We extract ``.root`` to get the typed variant, then map by
    ``type`` field.
    """
    from codex_app_server.generated.v2_all import (
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
                        input=inner.arguments if isinstance(inner.arguments, dict) else None,
                    )
                )
                result_text: str | None = None
                if inner.error is not None:
                    result_text = inner.error.message if hasattr(inner.error, "message") else str(inner.error)
                elif inner.result is not None:
                    result_text = json.dumps(inner.result.content) if hasattr(inner.result, "content") else str(inner.result)
                if result_text is not None:
                    blocks.append(
                        LupToolResultBlock(
                            tool_use_id=inner.id,
                            content=result_text,
                        )
                    )

            case FileChangeThreadItem():
                changes_desc = "; ".join(
                    f"{c.path} ({c.kind})" for c in inner.changes
                )
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
) -> tuple[str, ...]:
    """Build config_overrides for lup MCP tools via serve-tools.

    The Codex app-server is a Rust subprocess with no in-process tool
    registration. Tools must be configured as external MCP servers via
    TOML config. This generates the config_overrides that point Codex
    at the lup-devtools serve-tools command.
    """
    args = serve_tools_args or ["run", "lup-devtools", "agent", "serve-tools"]
    args_toml = json.dumps(args)
    return (
        f'mcp_servers.lup-tools.command="{serve_tools_command}"',
        f"mcp_servers.lup-tools.args={args_toml}",
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
        hook_overrides: list[CodexHookConfig] | None = None,
        session_id: str | None = None,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.output_schema = output_schema
        self.sandbox = sandbox
        self.effort = effort
        self.approval_policy = approval_policy
        self.mcp_tools = mcp_tools
        self.hook_overrides = hook_overrides
        self.session_id = session_id

    def build_config_overrides(self) -> tuple[str, ...]:
        """Assemble all config_overrides for this adapter run."""
        overrides: list[str] = []
        if self.mcp_tools:
            overrides.extend(build_mcp_config_overrides())
        if self.hook_overrides:
            overrides.extend(build_hook_config_overrides(self.hook_overrides))
        return tuple(overrides)

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        require_codex_sdk()

        from codex_app_server import (
            AppServerConfig,
            AskForApproval,
            AsyncCodex,
            ReasoningEffort,
            SandboxMode,
        )
        from codex_app_server.generated.v2_all import AskForApprovalValue

        config_overrides = self.build_config_overrides()
        config = AppServerConfig(config_overrides=config_overrides)

        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_start(
                model=self.model,
                developer_instructions=self.system_prompt,
                sandbox=SandboxMode(self.sandbox) if self.sandbox else None,
                approval_policy=(
                    AskForApproval(root=AskForApprovalValue(self.approval_policy))
                    if self.approval_policy
                    else None
                ),
            )

            effort = ReasoningEffort(self.effort) if self.effort else None
            result = await thread.run(
                prompt,
                effort=effort,
                output_schema=cast("JsonObject | None", self.output_schema),
            )

            blocks = codex_items_to_lup(result.items)

            response = LupResponse(blocks=blocks)

            for block in blocks:
                match block:
                    case LupToolResultBlock():
                        response.tool_results.append(block)

            assistant_blocks: list[LupContentBlock] = [
                b for b in blocks
                if not isinstance(b, LupToolResultBlock)
            ]
            result_blocks: list[LupContentBlock] = [
                b for b in blocks
                if isinstance(b, LupToolResultBlock)
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
            if result.final_response and self.output_schema:
                try:
                    structured_output = json.loads(result.final_response)
                except (json.JSONDecodeError, TypeError):
                    pass

            result_usage: dict[str, int] | None = None
            if result.usage is not None:
                result_usage = {
                    "input_tokens": result.usage.total.input_tokens,
                    "output_tokens": result.usage.total.output_tokens,
                }

            response.result = LupResultMessage(
                structured_output=structured_output,
                result=result.final_response,
                usage=result_usage,
            )
            response.session_id = thread.id or self.session_id

            return response

    async def resume(self, session_id: str, prompt: str) -> LupResponse:
        """Resume a Codex thread by ID."""
        require_codex_sdk()

        from codex_app_server import AppServerConfig, AsyncCodex

        config_overrides = self.build_config_overrides()
        config = AppServerConfig(config_overrides=config_overrides)

        async with AsyncCodex(config=config) as codex:
            thread = await codex.thread_resume(thread_id=session_id)
            result = await thread.run(prompt)

            blocks = codex_items_to_lup(result.items)
            response = LupResponse(blocks=blocks)
            response.session_id = session_id

            if result.final_response and self.output_schema:
                try:
                    structured_output = json.loads(result.final_response)
                    response.result = LupResultMessage(
                        structured_output=structured_output,
                        result=result.final_response,
                    )
                except (json.JSONDecodeError, TypeError):
                    response.result = LupResultMessage(result=result.final_response)
            else:
                response.result = LupResultMessage(result=result.final_response)

            return response

    async def fork(self, session_id: str, prompt: str) -> LupResponse:
        """Fork a Codex thread and run on the fork."""
        require_codex_sdk()

        from codex_app_server import AppServerConfig, AsyncCodex

        config_overrides = self.build_config_overrides()
        config = AppServerConfig(config_overrides=config_overrides)

        async with AsyncCodex(config=config) as codex:
            forked_thread = await codex.thread_fork(thread_id=session_id)
            result = await forked_thread.run(prompt)

            blocks = codex_items_to_lup(result.items)
            response = LupResponse(blocks=blocks)
            response.session_id = forked_thread.id
            response.result = LupResultMessage(result=result.final_response)

            return response
