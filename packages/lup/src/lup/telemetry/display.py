"""Color-coded console display of agent content blocks.

Real-time output for interactive sessions: tool use and tool result blocks
are linked by a rotating color so a result visibly pairs with its call. Pass
a ``TraceLogger`` via *trace* to also accumulate a markdown trace in the same
call, or use the logger's methods directly for trace-only logging.

Examples:
    Display a message with color-coded tool pairing::

        >>> print_message(assistant_message, prefix="  ")

    Display and trace together::

        >>> trace = TraceLogger(trace_path=Path("/tmp/trace.md"), title="Session 1")
        >>> print_message(assistant_message, trace=trace)
"""

import itertools
import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel
from rich.console import Console

from lup.telemetry.blocks import extract_block_info, format_tool_result
from lup.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupMessage,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
)

if TYPE_CHECKING:
    from lup.telemetry.trace import TraceLogger

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
        # Open tool-use-id -> color map, filled as blocks arrive.
        by_id: dict[str, str] = {}  # lup: ignore[dict-str-payload, empty-collection]
        self.by_id = by_id


DEFAULT_COLORS = ColorAssigner()
console = Console(highlight=False, markup=False)
stream_log = logging.getLogger("lup.agent.stream")


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


def print_block(
    block: LupContentBlock,
    prefix: str = "",
    trace: "TraceLogger | None" = None,
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
    trace: "TraceLogger | None" = None,
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
