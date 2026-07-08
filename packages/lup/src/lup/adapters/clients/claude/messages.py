"""SDK↔lup conversion: subagents, blocks, messages, and tools.

The projection layer between the Claude SDK's native vocabulary and the
backend-neutral ``Lup*`` types — every block and message an SDK turn
yields passes through here, and every lup-defined subagent and tool is
adapted to its SDK shape here.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any  # lup: ignore — confined to SdkDict, the SDK's payload type

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.mcp import LupMcpTool, LupToolHandler
from lup.types import (
    JsonObject,
    LupAssistantMessage,
    LupContentBlock,
    LupMessage,
    LupSystemMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
    SubagentSpec,
)


def spec_to_claude(spec: SubagentSpec) -> claude_types.AgentDefinition:
    """Convert a SubagentSpec to a Claude AgentDefinition.

    ``AgentDefinition.model`` is ``str | None`` and accepts both the
    short aliases (``sonnet``/``opus``/``haiku``) and full model IDs
    (``claude-opus-4-6``), so the spec's model passes straight through
    rather than collapsing unknown IDs to the inherited main-loop model.
    A spec without a model (``None``) inherits the main-loop model —
    the same semantics ``run_subagent`` gives it on other backends.
    """
    return claude_types.AgentDefinition(
        description=spec.description,
        prompt=spec.prompt,
        tools=spec.tools,
        model=spec.model,
    )


def claude_block_to_lup(block: claude.ContentBlock) -> LupContentBlock:
    """Convert a Claude SDK ContentBlock to a LupContentBlock."""
    if hasattr(block, "type") and getattr(block, "type", None) == "redacted_thinking":
        return LupThinkingBlock(thinking="", redacted=True)

    match block:
        case claude.ThinkingBlock():
            is_redacted = not block.thinking and bool(block.signature)
            return LupThinkingBlock(thinking=block.thinking or "", redacted=is_redacted)
        case claude.TextBlock():
            return LupTextBlock(text=block.text)
        case claude.ToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case claude.ToolResultBlock():
            return LupToolResultBlock(
                tool_use_id=block.tool_use_id, content=block.content
            )
        case claude_types.ServerToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case claude_types.ServerToolResultBlock():
            content = (
                block.content if isinstance(block.content, str) else str(block.content)
            )
            return LupToolResultBlock(tool_use_id=block.tool_use_id, content=content)
        case _:
            return LupTextBlock(text=str(block))


def claude_message_to_lup(message: claude.Message) -> LupMessage | None:
    """Convert a Claude SDK Message to a LupMessage.

    Returns None for message types that have no lup equivalent
    (e.g. stream events).
    """
    match message:
        case claude_types.AssistantMessage():
            blocks = [claude_block_to_lup(b) for b in message.content]
            return LupAssistantMessage(content=blocks)
        case claude_types.UserMessage():
            if isinstance(message.content, list):
                blocks = [claude_block_to_lup(b) for b in message.content]
                return LupUserMessage(content=blocks)
            return LupUserMessage(content=message.content)
        case claude_types.SystemMessage():
            data = (
                json.dumps(message.data)
                if isinstance(message.data, dict)
                else str(message.data)
            )
            return LupSystemMessage(subtype=message.subtype, data=data)
        case claude_types.ResultMessage():
            return None
        case _:
            return None


type SdkDict = dict[str, Any]  # lup: ignore — the SDK's tool-handler payload type


def lup_tools_to_sdk(
    tools: list[LupMcpTool],
) -> list[claude.SdkMcpTool[JsonObject]]:
    """Convert LupMcpTool list to Claude SDK SdkMcpTool list.

    ``SdkMcpTool.handler`` must return the SDK's untyped dict. A
    ``ToolResponse`` is a dict at runtime, so each handler is adapted
    with a shallow copy instead of widening ``LupToolHandler`` itself.
    """

    def as_sdk(handler: LupToolHandler) -> Callable[[JsonObject], Awaitable[SdkDict]]:
        async def call(args: JsonObject) -> SdkDict:
            return dict(await handler(args))

        return call

    return [
        claude.SdkMcpTool(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            handler=as_sdk(t.handler),
        )
        for t in tools
    ]
