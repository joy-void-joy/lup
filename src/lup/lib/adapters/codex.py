"""OpenAI Codex SDK adapter.

Wraps the Codex Python SDK (``codex_app_server``) behind the
``AgentAdapter`` interface. On the Codex path, lup features that
require in-process hooks or MCP servers (reflection gate, custom
tools, subagents) are not available — the agent runs with built-in
Codex tools only.

Install the Codex SDK to use this adapter::

    uv sync --extra codex
"""

import json
import logging

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


def codex_items_to_lup(items: list[object]) -> list[LupContentBlock]:
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
                        input={"command": inner.command, "cwd": str(inner.cwd)},
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
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.output_schema = output_schema
        self.sandbox = sandbox
        self.effort = effort
        self.approval_policy = approval_policy

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        require_codex_sdk()

        from codex_app_server import AsyncCodex, ReasoningEffort, SandboxMode

        async with AsyncCodex() as codex:
            thread = await codex.thread_start(
                model=self.model,
                developer_instructions=self.system_prompt,
                sandbox=SandboxMode(self.sandbox) if self.sandbox else None,
            )

            run_kwargs: dict[str, object] = {}
            if self.output_schema is not None:
                run_kwargs["output_schema"] = self.output_schema
            if self.effort is not None:
                run_kwargs["effort"] = ReasoningEffort(self.effort)
            if self.approval_policy is not None:
                run_kwargs["approval_policy"] = self.approval_policy
            if self.sandbox is not None:
                run_kwargs["sandbox_policy"] = self.sandbox

            result = await thread.run(prompt, **run_kwargs)

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

            return response
