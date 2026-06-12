"""Trace formatting and the TraceLogger save path.

The trace file is the feedback loop's raw material: if block formatting,
entry accumulation, or the save round-trip break, every downstream
analysis reads garbage. Also pins the tool-use/result color pairing,
which is stateful (a result must pop its use's color, not leak it),
and the entries-as-single-store rendering contract.
"""

from pathlib import Path

from lup.trace import (
    JsonValue,
    TraceLogger,
    format_block_markdown,
    format_tool_result,
    resolve_color_tag,
    truncate_str_fields,
)
from lup.types import (
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
)


def test_logger_accumulates_and_saves(tmp_path: Path) -> None:
    trace_path = tmp_path / "logs" / "trace.md"
    logger = TraceLogger(trace_path=trace_path, title="Session X")

    logger.log_block(LupTextBlock(text="hello"))
    logger.log_text("raw note", heading="Note")
    saved = logger.save()

    assert saved == trace_path
    content = trace_path.read_text(encoding="utf-8")
    assert content.startswith("# Trace: Session X")
    assert "hello" in content
    assert "## Note" in content
    # Two header entries plus the two logged entries, indexed in order
    assert [entry.index for entry in logger.entries] == [0, 1, 2, 3]


def test_save_renders_file_from_entries(tmp_path: Path) -> None:
    trace = TraceLogger(trace_path=tmp_path / "deep" / "t.md", title="Session X")
    trace.log_text("hello world", heading="Step")
    trace.log_text("plain text")

    saved = trace.save()

    content = saved.read_text(encoding="utf-8")
    assert content == "\n".join(entry.content for entry in trace.entries)
    assert "# Trace: Session X" in content
    assert "## Step" in content
    assert "plain text" in content


def test_read_entries_slices_with_negative_index(tmp_path: Path) -> None:
    logger = TraceLogger(trace_path=tmp_path / "t.md", title="S")
    for n in range(3):
        logger.log_text(f"entry {n}")

    tail = logger.read_entries(after_n=-2)

    assert len(tail) == 2
    assert "entry 2" in tail[-1].content


def test_read_entries_slices_head_with_before_n(tmp_path: Path) -> None:
    trace = TraceLogger(trace_path=tmp_path / "t.md", title="T")
    for i in range(5):
        trace.log_text(f"entry {i}")

    head = trace.read_entries(before_n=2)
    assert len(head) == 2
    assert head[0].content.startswith("# Trace: T")


def test_block_markdown_fences_by_block_type() -> None:
    tool_use = format_block_markdown(
        LupToolUseBlock(id="t1", name="Read", input={"file_path": "x"})
    )
    tool_result = format_block_markdown(
        LupToolResultBlock(tool_use_id="t1", content="data")
    )
    thinking = format_block_markdown(LupThinkingBlock(thinking="", redacted=True))

    assert "```json" in tool_use
    assert "Tool: Read" in tool_use
    assert "```" in tool_result
    assert "[redacted]" in thinking


def test_color_tag_pairs_use_with_result() -> None:
    use_tag = resolve_color_tag(LupToolUseBlock(id="pair-1", name="Read", input={}))
    result_tag = resolve_color_tag(
        LupToolResultBlock(tool_use_id="pair-1", content="x")
    )
    orphan_tag = resolve_color_tag(
        LupToolResultBlock(tool_use_id="pair-1", content="x")
    )

    assert use_tag is not None and result_tag is not None and orphan_tag is not None
    assert result_tag.color == use_tag.color
    # The pairing is popped on first use; an orphan result gets the default
    assert orphan_tag.color == "default"
    assert resolve_color_tag(LupTextBlock(text="plain")) is None


def test_separate_color_assigners_isolate_pairings() -> None:
    """Concurrent streams with their own assigners can't cross-pair: an
    assigner that never saw a tool use resolves its result to default."""
    from lup.trace import ColorAssigner

    own = ColorAssigner()
    other = ColorAssigner()
    use_tag = resolve_color_tag(LupToolUseBlock(id="iso-1", name="Read", input={}), own)
    crossed = resolve_color_tag(
        LupToolResultBlock(tool_use_id="iso-1", content="x"), other
    )
    paired = resolve_color_tag(
        LupToolResultBlock(tool_use_id="iso-1", content="x"), own
    )

    assert use_tag is not None and crossed is not None and paired is not None
    assert crossed.color == "default"
    assert paired.color == use_tag.color


def test_tool_result_formatting_truncates_inside_json() -> None:
    long_value = "x" * 600
    formatted = format_tool_result(f'{{"key": "{long_value}"}}')

    assert formatted.startswith("{")
    assert "..." in formatted
    assert len(formatted) < 600


def test_truncate_str_fields_caps_lists() -> None:
    truncated = truncate_str_fields([str(n) for n in range(50)], max_len_list=10)

    assert isinstance(truncated, list)
    assert len(truncated) == 10


def test_truncate_keeps_list_limit_in_nested_structures() -> None:
    data: JsonValue = {"outer": [[f"x{i}" for i in range(20)]]}

    result = truncate_str_fields(data, max_len=500, max_len_list=3)

    assert isinstance(result, dict)
    outer = result["outer"]
    assert isinstance(outer, list)
    inner = outer[0]
    assert isinstance(inner, list)
    assert len(inner) == 3


def test_truncate_shortens_nested_strings() -> None:
    data: JsonValue = {"a": {"b": ["y" * 100]}}

    result = truncate_str_fields(data, max_len=10, max_len_list=5)

    assert isinstance(result, dict)
    a = result["a"]
    assert isinstance(a, dict)
    b = a["b"]
    assert isinstance(b, list)
    assert b[0] == "y" * 10 + "..."
