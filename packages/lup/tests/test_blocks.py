"""The building blocks a view is laid out from: what a view answers, read as the page and as text."""

import pytest
from pydantic import BaseModel, TypeAdapter

import lup
from lup.blocks import Block, BlockError, Blocks, Fold, Line, Load, Markdown, OfAgent, Span


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
            Fold(id="3", kind="calls", summary=[Span(text="called Bash")], content=[Line.of("4", "ls")]),
        ],
    )
    assert Blocks.model_validate_json(view.model_dump_json()) == view


def test_a_block_is_read_by_its_kind() -> None:
    read = TypeAdapter[Block](Block).validate_python({"block": "markdown", "id": "1", "text": "hi"})
    assert read == Markdown(id="1", text="hi")


def test_the_text_form_says_open_folds_whole_and_closed_ones_as_their_summary() -> None:
    view = Blocks(
        blocks=[
            Fold(id="1", kind="earlier", summary=[Span(text="you: first")], content=[Line.of("2", "old")]),
            Fold(id="3", kind="calls", open=True, summary=[Span(text="called Read")], content=[Line.of("4", "Read: a.py")]),
            Markdown(id="5", text="one\ntwo"),
        ]
    )
    assert view.text() == "▸ you: first\n▾ called Read\n  Read: a.py\none\ntwo"


def test_a_fold_loads_another_view_with_what_it_takes() -> None:
    load = Load.of(Viewing.call, Called(call="c1"))
    assert load == Load(view="call", argument={"call": "c1"})
    opened = Fold(id="c1", kind="call", open=True, summary=[Span(text="Bash: ls")], content=load)
    assert Blocks(blocks=[opened]).text() == "▾ Bash: ls"


def test_a_fold_loads_only_a_view_and_what_it_takes() -> None:
    with pytest.raises(BlockError, match="doesn't take"):
        Load.of(Viewing.call, OfAgent(runtime="claude", session="s"))
