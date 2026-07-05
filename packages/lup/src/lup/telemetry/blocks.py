"""Content-block extraction and truncation helpers.

The pure functions that turn a content block or raw tool-result content into
display-ready strings, shared by the console display (:mod:`lup.telemetry.display`)
and the markdown trace (:mod:`lup.telemetry.trace`). No console or file I/O.
"""

import json
from collections.abc import Sequence

from pydantic import BaseModel

from lup.types import (
    LupContentBlock,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
)

# JSON-like recursive type for truncation functions
type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)


def normalize_content(content: str | Sequence[object] | None) -> str:
    """Convert MCP content blocks to a plain string."""
    if content is None:
        return "(empty)"
    if isinstance(content, list):
        texts: list[str] = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(texts)
    return str(content)


def truncate_str(value: str, max_len: int = 500) -> str:
    """Truncate a string to max_len, appending '...' if trimmed."""
    if len(value) > max_len:
        return value[:max_len] + "..."
    return value


def truncate_str_fields(
    obj: JsonValue, max_len: int = 500, max_len_list: int = 10
) -> JsonValue:
    """Recursively truncate string values in a JSON-like structure."""
    match obj:
        case dict() as d:
            return {
                k: truncate_str_fields(v, max_len, max_len_list) for k, v in d.items()
            }
        case list() as items:
            return [truncate_str_fields(item, max_len, max_len_list) for item in items][
                :max_len_list
            ]
        case str() as s:
            return truncate_str(s, max_len)
        case _:
            return obj


def format_tool_result(
    content: str | Sequence[object] | None, max_len: int = 500
) -> str:
    """Format tool result content for display.

    If the content parses as a JSON dict, pretty-print it with string fields
    truncated. Otherwise fall back to plain truncation.
    """
    text = normalize_content(content)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return truncate_str(text, max_len)
    truncated = truncate_str_fields(parsed, max_len)
    return json.dumps(truncated, indent=2)


class BlockInfo(BaseModel):
    """Extracted display information from a content block."""

    emoji: str
    label: str
    content: str


def extract_block_info(block: LupContentBlock) -> BlockInfo:
    """Extract display information from a content block."""
    match block:
        case LupThinkingBlock():
            content = "[redacted]" if block.redacted else block.thinking
            return BlockInfo(emoji="💭", label="Thinking", content=content)
        case LupTextBlock():
            return BlockInfo(emoji="💬", label="Response", content=block.text)
        case LupToolUseBlock():
            content = json.dumps(block.input, indent=2) if block.input else ""
            return BlockInfo(emoji="🔧", label=f"Tool: {block.name}", content=content)
        case LupToolResultBlock():
            return BlockInfo(
                emoji="📋", label="Result", content=normalize_content(block.content)
            )
        case _:
            return BlockInfo(emoji="❓", label="Unknown", content=str(block))
