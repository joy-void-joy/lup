"""Trace logging and output utilities.

Provides utilities for logging agent execution traces and displaying
content blocks during agent runs. Used for feedback loop analysis.

Content blocks are displayed with color-coded tool use/result pairing
using Rich console, making it easy to visually track which result
belongs to which tool call.

Two output channels:
- **Console display** (``print_block`` / ``print_message``): real-time
  color-coded output for interactive sessions.
- **Trace accumulation** (``TraceLogger``): markdown-formatted log for
  post-hoc feedback loop analysis.

Pass a ``TraceLogger`` via the *trace* parameter to combine both in one
call, or use ``TraceLogger`` methods directly for trace-only logging.

Examples:
    Display a message with color-coded tool pairing::

        >>> print_message(assistant_message, prefix="  ")

    Display and trace together::

        >>> trace = TraceLogger(trace_path=Path("/tmp/trace.md"), title="Session 1")
        >>> print_message(assistant_message, trace=trace)
        >>> trace.save()
        PosixPath('/tmp/trace.md')
"""

from __future__ import annotations

import itertools
import json
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from rich.console import Console

from lup.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
)
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# JSON-like recursive type for truncation functions
type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)

# ---------------------------------------------------------------------------
# Color-coded tool use / result pairing
# ---------------------------------------------------------------------------

TOOL_COLORS = [
    "cyan",
    "green",
    "yellow",
    "magenta",
    "blue",
    "red",
    "bright_cyan",
    "bright_green",
    "bright_yellow",
    "bright_magenta",
    "bright_blue",
    "bright_red",
]


class ColorAssigner:
    """Rotating tool-color state for tool use / result pairing.

    One instance per concurrent output stream: sharing an assigner
    across sessions interleaves the palette rotation. ToolUseBlock
    assigns a color; the matching ToolResultBlock pops it. The
    module-level :data:`DEFAULT_COLORS` keeps the single-session
    default; pass a dedicated instance to ``print_block``/
    ``print_message`` for concurrent streams (background agents, relay
    watchers) so their pairings can't cross.
    """

    def __init__(self) -> None:
        self.cycle = itertools.cycle(TOOL_COLORS)
        self.by_id: dict[str, str] = {}


DEFAULT_COLORS = ColorAssigner()
console = Console(highlight=False, markup=False)
stream_log = logging.getLogger("lup.agent.stream")


# ---------------------------------------------------------------------------
# Content normalization
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Block info extraction
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Color tag resolution
# ---------------------------------------------------------------------------


class ColorTag(BaseModel):
    """Color-coded identifier for tool use / result pairing."""

    id: str
    color: str


def resolve_color_tag(
    block: LupContentBlock, colors: ColorAssigner = DEFAULT_COLORS
) -> ColorTag | None:
    """Assign or retrieve a color for tool use/result pairing.

    LupToolUseBlock gets a fresh color from the rotating palette and
    stores it by ID. LupToolResultBlock pops the matching color. Other
    blocks return None (no colored tag).
    """
    match block:
        case LupToolUseBlock():
            color = next(colors.cycle)
            colors.by_id[block.id] = color
            return ColorTag(id=block.id, color=color)
        case LupToolResultBlock():
            color = colors.by_id.pop(block.tool_use_id, "default")
            return ColorTag(id=block.tool_use_id, color=color)
        case _:
            return None


# ---------------------------------------------------------------------------
# Console display
# ---------------------------------------------------------------------------


def print_block(
    block: LupContentBlock,
    prefix: str = "",
    trace: TraceLogger | None = None,
    colors: ColorAssigner | None = None,
) -> None:
    """Print a content block with color-coded tool use/result pairing.

    LupToolUseBlock and LupToolResultBlock are linked by color: when a
    tool use is printed, its ID is assigned a color from a rotating
    palette. When the corresponding result arrives, the same color is
    used, making it easy to visually pair them. Concurrent streams pass
    their own :class:`ColorAssigner` so pairings can't cross.

    If *trace* is provided, the block is also logged to the trace.
    """
    info = extract_block_info(block)
    tag = resolve_color_tag(block, colors or DEFAULT_COLORS)

    display_content = (
        format_tool_result(block.content)
        if isinstance(block, LupToolResultBlock)
        else info.content
    )

    if tag:
        print(f"{prefix}{info.emoji} {info.label} ", end="")
        console.print(f"[{tag.id}]", style=tag.color)
        if display_content:
            print(display_content)
    else:
        print(f"{prefix}{info.emoji} {display_content}")

    match block:
        case LupToolUseBlock():
            stream_log.info(
                "%sTOOL_USE [%s] %s: %s",
                prefix,
                block.id,
                block.name,
                json.dumps(block.input) if block.input else "",
            )
        case LupToolResultBlock():
            stream_log.info(
                "%sTOOL_RESULT [%s]: %s",
                prefix,
                block.tool_use_id,
                display_content,
            )
        case _:
            stream_log.info("%s%s: %s", prefix, info.label.upper(), display_content)

    if trace:
        trace.log_block(block)


def print_message(
    message: LupMessage,
    prefix: str = "",
    trace: TraceLogger | None = None,
    colors: ColorAssigner | None = None,
) -> None:
    """Print all content blocks in a message.

    Handles LupAssistantMessage and LupUserMessage (which carry content
    blocks). Other message types are silently ignored. If *trace* is
    provided, blocks are also logged to it.
    """
    match message:
        case LupAssistantMessage() | LupUserMessage():
            blocks = message.content if isinstance(message.content, list) else []
            for block in blocks:
                print_block(block, prefix=prefix, trace=trace, colors=colors)


# ---------------------------------------------------------------------------
# Markdown formatting for traces
# ---------------------------------------------------------------------------


def format_block_markdown(block: LupContentBlock) -> str:
    """Format a content block as markdown for trace logs."""
    info = extract_block_info(block)
    header = f"## {info.emoji} {info.label}"
    match block:
        case LupToolUseBlock():
            return f"{header}\n\n```json\n{info.content}\n```\n"
        case LupToolResultBlock():
            return f"{header}\n\n```\n{info.content}\n```\n"
        case _:
            return f"{header}\n\n{info.content}\n"


# ---------------------------------------------------------------------------
# Trace logger
# ---------------------------------------------------------------------------


class TraceEntry(BaseModel):
    """A single indexed entry in a session trace."""

    index: int = Field(description="0-based entry index")
    timestamp: str = Field(description="ISO timestamp when entry was logged")
    content: str = Field(description="Markdown content for this entry")


class TraceLogger(BaseModel):
    """Accumulates agent reasoning for feedback loop analysis.

    Collects content blocks during agent execution and saves them
    as a markdown trace file for later analysis. ``entries`` is the
    single store: ``save()`` renders the markdown stream from it, and
    ``read_entries()`` slices it for in-session replay.

    Typically passed to ``print_message(message, trace=trace)`` for
    combined display and tracing. Methods like ``log_message`` and
    ``log_text`` support trace-only logging without console output.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_path: Path = Field(description="Path to save the trace file")
    title: str = Field(description="Title for the trace")
    entries: list[TraceEntry] = Field(default_factory=list)

    def model_post_init(self, _context: object) -> None:
        """Initialize the trace with header."""
        if not self.entries:
            self.append_entry(f"# Trace: {self.title}\n")
            self.append_entry(f"*Generated: {datetime.now().isoformat()}*\n\n")

    def append_entry(self, content: str) -> None:
        """Create and append a new trace entry."""
        self.entries.append(
            TraceEntry(
                index=len(self.entries),
                timestamp=datetime.now().isoformat(),
                content=content,
            )
        )

    def log_block(self, block: LupContentBlock) -> None:
        """Add a formatted block to the trace."""
        self.append_entry(format_block_markdown(block))

    def log_message(self, message: LupMessage) -> None:
        """Log all content blocks in a message.

        Handles LupAssistantMessage and LupUserMessage. Other message
        types are silently ignored.
        """
        match message:
            case LupAssistantMessage() | LupUserMessage():
                blocks = message.content if isinstance(message.content, list) else []
                for block in blocks:
                    self.log_block(block)

    def log_text(self, text: str, heading: str | None = None) -> None:
        """Add raw text to the trace."""
        if heading:
            self.append_entry(f"## {heading}\n\n{text}\n")
        else:
            self.append_entry(f"{text}\n")

    def read_entries(
        self,
        after_n: int | None = None,
        before_n: int | None = None,
    ) -> list[TraceEntry]:
        """Slice entries by index. Supports negative indexing.

        Lets a persistent agent replay recent trace context (e.g. the
        last N entries) without re-reading the saved file.
        """
        return self.entries[after_n:before_n]

    def save(self) -> Path:
        """Write the accumulated trace to file, rendered from entries."""
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_path.write_text(
            "\n".join(entry.content for entry in self.entries), encoding="utf-8"
        )
        logger.info("Saved trace to %s", self.trace_path)
        return self.trace_path
