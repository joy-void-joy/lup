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

# lup: Feels like this file should maybe be split in several?

import itertools
import json
import logging
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

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
# Structured events (machine-readable sidecar)
# ---------------------------------------------------------------------------

# Capability-request phrasing. Applied to one already-isolated string at the
# moment it is logged (an assistant text or meta thought), not swept across a
# markdown document — so the persisted signal is structured, not regex-derived.
CAPABILITY_PHRASES: re.Pattern[str] = re.compile(
    r"would be useful|would have helped|would benefit from|wish I (had|could)|"
    r"if (only )?I could|need(s|ed)? access to|cannot .* because|"
    r"a tool that|missing (a )?tool",
    re.IGNORECASE,
)


class TraceEvent(BaseModel):
    """A typed, machine-readable record of one thing analysis cares about.

    Written one-per-line to the ``.events.jsonl`` sidecar beside the human
    ``.md`` trace as the trace is built. ``kind`` discriminates the three
    signals the feedback loop reads — tool outcomes, errors/exceptions, and
    capability requests — so analysis loads validated objects instead of
    re-deriving them with regex over free-form markdown.
    """

    kind: Literal["tool_call", "error", "capability_request"]
    timestamp: str = Field(description="ISO timestamp when the event was recorded")
    tool: str | None = Field(
        default=None, description="Tool name (for tool_call events)"
    )
    ok: bool | None = Field(
        default=None, description="Whether the tool call succeeded (for tool_call)"
    )
    brief: str = Field(
        default="", description="Short human summary: tool result, error, or request"
    )


def tool_result_ok(content: str | Sequence[object] | None) -> bool:
    """Decide whether a tool result reports success.

    MCP errors are carried inside the result content as ``is_error``; absent
    that flag a result is treated as successful. Reads the structured payload
    instead of keyword-scanning the rendered text.
    """
    text = normalize_content(content)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return True
    if isinstance(parsed, dict):
        return not bool(parsed.get("is_error"))
    return True


def capability_request_from_text(text: str) -> str | None:
    """Return the first capability-request sentence in *text*, or None.

    Splits on sentence boundaries and returns the matching fragment so the
    event's ``brief`` is the specific wish, not the whole block.
    """
    for fragment in re.split(r"(?<=[.!?\n])\s+", text):
        stripped = fragment.strip()
        if stripped and CAPABILITY_PHRASES.search(stripped):
            return truncate_str(stripped, 300)
    return None


def read_trace_events(events_path: Path) -> list[TraceEvent]:
    """Read a ``.events.jsonl`` sidecar into validated :class:`TraceEvent`s.

    Skips blank or malformed lines so a truncated tail (a crash mid-write)
    never loses the events that were flushed before it.
    """
    events: list[TraceEvent] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(TraceEvent.model_validate_json(line))
        except ValueError:
            logger.warning("Skipping malformed trace event line in %s", events_path)
    return events


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

    Alongside the human ``.md`` trace it appends a machine-readable
    ``.events.jsonl`` sidecar — one :class:`TraceEvent` per line, flushed as
    each block is logged — so analysis reads typed tool/error/capability
    records instead of regex-scanning the markdown. The ``.md`` trace is the
    human view and is never weakened by the sidecar.

    Typically passed to ``print_message(message, trace=trace)`` for
    combined display and tracing. Methods like ``log_message`` and
    ``log_text`` support trace-only logging without console output.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_path: Path = Field(description="Path to save the trace file")
    title: str = Field(description="Title for the trace")
    entries: list[TraceEntry] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    tool_names: dict[str, str] = Field(default_factory=dict, exclude=True)

    def model_post_init(self, _context: object) -> None:
        """Initialize the trace with header."""
        if not self.entries:
            self.append_entry(f"# Trace: {self.title}\n")
            self.append_entry(f"*Generated: {datetime.now().isoformat()}*\n\n")

    @property
    def events_path(self) -> Path:
        """Path to the machine-readable JSONL sidecar beside the .md trace."""
        return self.trace_path.with_suffix(".events.jsonl")

    def append_entry(self, content: str) -> None:
        """Create and append a new trace entry."""
        self.entries.append(
            TraceEntry(
                index=len(self.entries),
                timestamp=datetime.now().isoformat(),
                content=content,
            )
        )

    def emit_event(self, event: TraceEvent) -> None:
        """Record a structured event and append it to the JSONL sidecar.

        Appended immediately so the sidecar stays usable even if the run
        crashes before :meth:`save`. A write failure is logged, never raised:
        the sidecar is diagnostic and must not break a live agent.
        """
        self.events.append(event)
        try:
            self.events_path.parent.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
        except OSError:
            logger.exception("Failed to append trace event to %s", self.events_path)

    def log_block(self, block: LupContentBlock) -> None:
        """Add a formatted block to the trace and emit its structured event."""
        self.append_entry(format_block_markdown(block))
        self.emit_block_event(block)

    def emit_block_event(self, block: LupContentBlock) -> None:
        """Derive and emit the structured event(s) for a content block.

        Tool-use blocks record their name keyed by id; the paired tool-result
        block emits the ``tool_call`` event with name + ok/error + brief.
        Assistant text that voices a capability request emits one too.
        """
        now = datetime.now().isoformat()
        match block:
            case LupToolUseBlock():
                self.tool_names[block.id] = block.name
            case LupToolResultBlock():
                name = self.tool_names.pop(block.tool_use_id, "unknown")
                ok = tool_result_ok(block.content)
                brief = truncate_str(normalize_content(block.content), 300)
                self.emit_event(
                    TraceEvent(
                        kind="tool_call", timestamp=now, tool=name, ok=ok, brief=brief
                    )
                )
                if not ok:
                    self.emit_event(
                        TraceEvent(kind="error", timestamp=now, tool=name, brief=brief)
                    )
            case LupTextBlock():
                request = capability_request_from_text(block.text)
                if request is not None:
                    self.emit_event(
                        TraceEvent(
                            kind="capability_request", timestamp=now, brief=request
                        )
                    )
            case _:
                pass

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
        """Add raw text to the trace, emitting a capability event if voiced.

        Meta assessments and reflections flow through here; when one names a
        missing tool or access, that wish is captured as a structured event.
        """
        if heading:
            self.append_entry(f"## {heading}\n\n{text}\n")
        else:
            self.append_entry(f"{text}\n")
        request = capability_request_from_text(text)
        if request is not None:
            self.emit_event(
                TraceEvent(
                    kind="capability_request",
                    timestamp=datetime.now().isoformat(),
                    brief=request,
                )
            )

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
        """Write the accumulated trace to file, rendered from entries.

        Events are appended to the sidecar live by :meth:`emit_event`; here we
        only ensure the sidecar exists so a completed run is always recognized
        as structured (and analysis never falls back to line-scanning it),
        even when it produced no tool calls.
        """
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_path.write_text(
            "\n".join(entry.content for entry in self.entries), encoding="utf-8"
        )
        self.events_path.touch()
        logger.info("Saved trace to %s", self.trace_path)
        return self.trace_path
