"""TraceLogger behavior: entries as the single store, slicing, truncation."""

from pathlib import Path

from lup.trace import JsonValue, TraceLogger, truncate_str_fields


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


def test_entries_are_indexed_and_sliceable(tmp_path: Path) -> None:
    trace = TraceLogger(trace_path=tmp_path / "t.md", title="T")
    for i in range(5):
        trace.log_text(f"entry {i}")

    assert [entry.index for entry in trace.entries] == list(range(len(trace.entries)))

    last_two = trace.read_entries(after_n=-2)
    assert [entry.content for entry in last_two] == ["entry 3\n", "entry 4\n"]

    head = trace.read_entries(before_n=2)
    assert len(head) == 2
    assert head[0].content.startswith("# Trace: T")


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
