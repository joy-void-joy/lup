"""The building blocks a view is laid out from: what a view answers, read as the page and as text."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, TypeAdapter

import lup
from lup.blocks import (
    SHELL_FOLDS,
    Block,
    BlockError,
    Blocks,
    Code,
    Diff,
    FileBytes,
    FileText,
    Fold,
    Gauge,
    Line,
    Load,
    Mark,
    Markdown,
    OfAgent,
    Span,
    Ticking,
)


class Called(BaseModel):
    """What a call's view takes."""

    call: str


class Viewing(BaseModel):
    """A class of views."""

    @lup.view(place=lup.Drawer(letter="v", called="the conversation", colour="cyan"))
    async def conversation(self, viewed: OfAgent) -> Blocks:
        """The whole conversation."""
        return Blocks(blocks=[Line.of("1", viewed.session)])

    @lup.view
    async def call(self, viewed: Called) -> Blocks:
        """One call's input and output."""
        return Blocks(blocks=[Line.of(viewed.call, "input")])


def test_a_view_answers_blocks_that_read_back_as_they_were_sent() -> None:
    view = Blocks(
        summary=[Span(text="conversation · 1 step")],
        waiting=True,
        blocks=[
            Line(id="1", spans=[Span(text="you: ", tone="operator"), Span(text="hi")]),
            Markdown(id="2", text="**done**"),
            Fold(
                id="3",
                kind="calls",
                summary=[Span(text="called Bash")],
                content=[Line.of("4", "ls")],
            ),
        ],
    )
    assert Blocks.model_validate_json(view.model_dump_json()) == view


def test_a_block_is_read_by_its_kind() -> None:
    read = TypeAdapter[Block](Block).validate_python(
        {"block": "markdown", "id": "1", "text": "hi"}
    )
    assert read == Markdown(id="1", text="hi")


def test_the_text_form_says_open_folds_whole_and_closed_ones_as_their_summary() -> None:
    view = Blocks(
        blocks=[
            Fold(
                id="1",
                kind="earlier",
                summary=[Span(text="you: first")],
                content=[Line.of("2", "old")],
            ),
            Fold(
                id="3",
                kind="calls",
                open=True,
                summary=[Span(text="called Read")],
                content=[Line.of("4", "Read: a.py")],
            ),
            Markdown(id="5", text="one\ntwo"),
        ]
    )
    assert view.text() == "▸ you: first\n▾ called Read\n  Read: a.py\none\ntwo"


def test_a_fold_loads_another_view_with_what_it_takes() -> None:
    load = Load.of(Viewing.call, Called(call="c1"))
    assert load == Load(view="call", argument={"call": "c1"})
    opened = Fold(
        id="c1", kind="call", open=True, summary=[Span(text="Bash: ls")], content=load
    )
    assert Blocks(blocks=[opened]).text() == "▾ Bash: ls  [call call=c1]"


def test_a_fold_loads_only_a_view_and_what_it_takes() -> None:
    with pytest.raises(BlockError, match="doesn't take"):
        Load.of(Viewing.call, OfAgent(runtime="claude", session="s"))


def test_a_diff_and_a_code_read_back_as_they_were_sent_and_by_their_kind() -> None:
    view = Blocks(
        count=2,
        blocks=[
            Diff(
                id="file a.py",
                version="4b1d",
                path="a.py",
                before=FileText(text="a\nb\n"),
                after=FileText(text="a\nc\n"),
                says=["adds an ignore"],
                marks=[Mark(taken="held", said="adds an ignore", first=2)],
                design=True,
            ),
            Diff(id="file b.png", path="b.png", after=FileBytes(size=3), open=False),
            Code(id="file c.py", path="c.py", text="x = 1\n"),
        ],
    )
    assert Blocks.model_validate_json(view.model_dump_json()) == view
    read = TypeAdapter[Block](Block).validate_python(
        {
            "block": "diff",
            "id": "1",
            "path": "a.py",
            "after": {"kind": "text", "text": "x"},
        }
    )
    assert read == Diff(id="1", path="a.py", after=FileText(text="x"))


def test_a_diff_shows_each_line_it_removes_in_place_before_those_replacing_it() -> None:
    diff = Diff(
        id="a",
        path="a.py",
        before=FileText(text="a\nb\nc\n"),
        after=FileText(text="a\nB\nc\nd\n"),
    )
    assert [(row.change, row.side, row.number, row.text) for row in diff.rows()] == [
        ("same", "after", 1, "a"),
        ("removed", "before", 2, "b"),
        ("added", "after", 2, "B"),
        ("same", "after", 3, "c"),
        ("added", "after", 4, "d"),
    ]
    assert diff.header() == "a.py · changed · +2 \N{MINUS SIGN}1"


def test_a_diff_s_header_says_what_the_change_did_to_the_file_then_what_it_says() -> (
    None
):
    created = Diff(
        id="a", path="a.py", after=FileText(text="x\ny\n"), says=["new file"]
    )
    deleted = Diff(id="b", path="b.py", before=FileText(text="x\n"))
    same = Diff(
        id="c", path="c.py", before=FileText(text="x\n"), after=FileText(text="x\n")
    )
    binary = Diff(
        id="d", path="d.png", before=FileBytes(size=1200), after=FileBytes(size=1300)
    )
    assert created.header() == "a.py · created · 2 lines · new file"
    assert deleted.header() == "b.py · deleted · 1 line"
    assert same.header() == "c.py · changed · no line differs"
    assert binary.header() == (
        "d.png · changed · binary, not shown · 1,200 bytes → 1,300 bytes"
    )


def test_the_text_form_says_a_diff_s_lines_and_what_matters_at_the_end_of_each() -> (
    None
):
    diff = Diff(
        id="a",
        path="a.py",
        before=FileText(text="a\nb\n"),
        after=FileText(text="a\nc\n"),
        marks=[
            Mark(taken="flagged", said="public API: adds `c`", first=2),
            Mark(taken="held", said="removes `b`", side="before", first=2),
        ],
    )
    folded = diff.model_copy(update={"open": False})
    code = Code(
        id="c",
        path="c.py",
        text="x = 1\ny = 2\n",
        marks=[Mark(taken="told", said="regex: a pattern", first=2, last=2)],
    )
    assert Blocks(blocks=[diff, folded, code]).text().splitlines() == [
        f"▾ {diff.header()}",
        "    a",
        "  - b  ◂ held: removes `b`",
        "  + c  ◂ flagged: public API: adds `c`",
        f"▸ {diff.header()}",
        "▾ c.py · 2 lines",
        "    x = 1",
        "    y = 2  ◂ told: regex: a pattern",
    ]


def test_a_span_names_an_item_ticks_and_measures_and_reads_back() -> None:
    since = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
    line = Line(
        id="1",
        spans=[
            Span(text="flagged "),
            Span(text="@64", item=64),
            Span(
                text="waiting 5m",
                ticking=Ticking(since=since, said="waiting {}", first="just in"),
            ),
            Span(text="◔ 112k/1M", gauge=Gauge(used=112_000, of=1_000_000)),
        ],
    )
    assert Line.model_validate_json(line.model_dump_json()) == line
    assert Blocks(blocks=[line]).text() == "flagged @64waiting 5m◔ 112k/1M"


def test_the_shell_s_fold_kinds_each_take_a_letter_of_their_own() -> None:
    letters = [kind.letter for kind in SHELL_FOLDS]
    assert len(set(letters)) == len(letters)
    [item] = [kind for kind in SHELL_FOLDS if kind.name == "item"]
    assert item.whole
    assert not item.chord
