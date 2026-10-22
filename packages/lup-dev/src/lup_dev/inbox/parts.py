"""An item's parts, each with an id the agent and the operator cite: the Markdown blocks of its text, numbered from 1 within the item.

`docs/inbox.md`, *Parts and ids*. A part's id is its item's number and its
place in the item, `414.3`, cited `@414.3` wherever lup names it (`PartId`), so
an anchor into an item is small and stays put: a review quotes a passage by the
part it starts in and the passage's first line, an agent replies to the
operator's comment by its id, and `inbox` reads one part alone.

The parts of a text are its Markdown blocks (`blocks`): a paragraph, a heading,
a code block, a quote, a rule, and each item of a list and each row of a table,
since a list or a table is usually the whole message and a reply is on one of
its lines. A list item holds what's nested in it. The text is read by
markdown-it, with the table and strikethrough extensions the dashboard's
parser reads too (`page/src/markdown.ts`), each block's lines known from the
tokens it leaves; the parts' offsets count in the text as written, so the
dashboard places a comment by them.
"""

import csv
from itertools import accumulate
from typing import TYPE_CHECKING, Literal, Self, get_args

from markdown_it import MarkdownIt
from pydantic import JsonValue, model_validator

from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Generator

    from markdown_it.token import Token


class PartId(Model):
    """What names one part of one item: the item's number, and the part's place in it, from 1."""

    item: int
    part: int

    @classmethod
    def parsed(cls, typed: str) -> Self:
        """Read a part's id as it's cited or typed: `414.3`, or `@414.3`.

        Raise `ValueError` naming what an id is where `typed` isn't one: two
        whole numbers around one dot, and nothing else.

        >>> PartId.parsed("@414.3")
        PartId(item=414, part=3)
        >>> PartId.parsed("414")
        Traceback (most recent call last):
        ...
        ValueError: `414` isn't a part's id: an item's number, a dot and the part's place in it, as `414.3`
        """
        [fields] = csv.reader([typed.removeprefix("@")], delimiter=".")
        match fields:
            case [item, part] if item.isdigit() and part.isdigit():
                return cls(item=int(item), part=int(part))
            case _:
                message = (
                    f"`{typed}` isn't a part's id: an item's number, a dot and the "
                    "part's place in it, as `414.3`"
                )
                raise ValueError(message)

    @model_validator(mode="before")
    @classmethod
    def typed(cls, given: JsonValue) -> JsonValue:
        """Take an id typed as text, `414.3`, where a model holds one, so a stored or a sent id reads either way."""
        return cls.parsed(given).model_dump() if isinstance(given, str) else given

    def said(self) -> str:
        """Say the id as an attribute carries it: `414.3`.

        >>> PartId(item=414, part=3).said()
        '414.3'
        """
        return f"{self.item}.{self.part}"

    def cited(self) -> str:
        """Name the part as a reader sees it named, `@414.3`, as an item is `@414`.

        >>> PartId(item=414, part=3).cited()
        '@414.3'
        """
        return f"@{self.said()}"


class Part(Model):
    """One part of an item's text: its id, its text, and where it is in the whole."""

    id: PartId
    text: str
    start: int
    """Where it starts in the text, counted in characters."""
    end: int
    """Where it ends, after its last character."""

    def holds(self, offset: int) -> bool:
        """Say whether `offset` falls in the part."""
        return self.start <= offset < self.end


class Spanned(Model):
    """The lines a block spans, as markdown-it maps them: from `first` to `until`, excluded."""

    first: int
    until: int


class Lines(Model):
    """A text as its lines, each known by where it starts in the text, as markdown-it numbers them."""

    text: str
    lines: list[str]
    """Each line without its end."""
    starts: list[int]
    """Where each line starts in the text, and, last, where the text ends."""

    @classmethod
    def of(cls, text: str) -> Self:
        """Read `text` into its lines, each with its start."""
        ends = (len(line) for line in text.splitlines(keepends=True))
        return cls(
            text=text,
            lines=text.splitlines(),
            starts=list(accumulate(ends, initial=0)),
        )

    def block(self, span: Spanned, number: int, place: int) -> Part | None:
        """Return the part of the lines `span` names, as part `place` of item `number`, its trailing blank lines left out; none where no line is left."""
        last = span.until
        while last > span.first and not self.lines[last - 1].strip():
            last -= 1
        if last == span.first:
            return None
        text = "\n".join(self.lines[span.first : last])
        return Part(
            id=PartId(item=number, part=place),
            text=text,
            start=self.starts[span.first],
            end=self.starts[span.first] + len(text),
        )


READER = MarkdownIt("commonmark").enable(["table", "strikethrough"])
"""Reads a text's blocks: CommonMark with GitHub's tables and strikethrough, as the dashboard reads it."""

type Container = Literal["bullet_list_open", "ordered_list_open", "table_open"]
"""The tokens opening a block whose children are the parts, rather than the
block whole: a list's items, a table's rows."""


def spanned(token: Token) -> Spanned | None:
    """Return the lines a part spans as `token` opens it: a top-level block's, an item's of a top-level list, or a row's of a top-level table; none for any other token.

    A list's item is one level in, a table's row two, under its head or body;
    what's nested deeper stays inside the part holding it.
    """
    if token.map is None:
        return None
    first, until = token.map
    match token.level, token.nesting, token.type:
        case 0, nesting, kind if nesting >= 0 and kind not in get_args(
            Container.__value__
        ):
            return Spanned(first=first, until=until)
        case (1, _, "list_item_open") | (2, _, "tr_open"):
            return Spanned(first=first, until=until)
        case _:
            return None


def blocks(text: str, number: int) -> list[Part]:
    r"""Return the parts of `text`, the text of item `number`: its Markdown blocks in order, each numbered from 1.

    A list's items and a table's rows are parts of their own, the list or
    the table itself none; a nested list stays inside the item holding it; a
    table's delimiter row belongs to no part.

    >>> [each.text for each in blocks("A line.\n\n- one\n- two\n", 7)]
    ['A line.', '- one', '- two']
    >>> blocks("A line.\n\n- one\n- two\n", 7)[2]
    Part(id=PartId(item=7, part=3), text='- two', start=15, end=20)
    """
    lines = Lines.of(text)

    def made() -> Generator[Part]:
        place = 1
        for token in READER.parse(text):
            span = spanned(token)
            part = None if span is None else lines.block(span, number, place)
            if part is not None:
                place += 1
                yield part

    return list(made())
