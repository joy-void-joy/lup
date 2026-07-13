"""SDK→lup traffic conversion: blocks and messages.

The projection layer between the Claude SDK's native vocabulary and the
backend-neutral ``Lup*`` types — every block and message an SDK turn
yields passes through here. Construction-payload adaption lives with the
translation (:mod:`lup.adapters.clients.claude.translate`).
"""

import json

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupMessage,
    LupSystemMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
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
