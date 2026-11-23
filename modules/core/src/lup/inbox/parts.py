"""An item's parts: what a reader answers on its own, each cited by its place in the item, `@12.3`.

A text's parts are the blocks its Markdown is made of: a paragraph, a heading, a
block of code, a quote, a rule, each item of a list, what's nested in it
included, and each row of a table, since a list or a table is often the whole
message and an answer is on one of its lines. What an item says beyond its text
(`Item.beyond`), a question's decisions and an answer's rulings, are parts too,
numbered on from the text's. An item's words are never written over, so an id
names the same words for as long as the item is kept.

The blocks are read by markdown-it, CommonMark with GitHub's tables as the page
reads it, and its lines are broken where the page breaks them, so a line the
page counts is the same line here. Every line is in one part: what lies between
two blocks, a blank line or a link's definition, which leaves no block, goes
with the block before it, and what's before the first with the first.
"""

import csv
import io
from functools import cache
from itertools import dropwhile, pairwise
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

from lup.inbox.records import Item
from lup.types import Model

if TYPE_CHECKING:
    from markdown_it.token import Token


class TextPart(Model):
    """One part of a text: its place, the line it starts at, and its lines."""

    place: int
    """Its place among the parts, from 1."""
    line: int
    """The line it starts at, from 0, of the text it's a part of."""
    lines: list[str]
    """Its lines, without the blank ones around them."""

    def text(self) -> str:
        """Return its words."""
        return "\n".join(self.lines)


class ItemPart(Model):
    """One part of an item, as `@12.3` cites it: the item, and the part of it."""

    item: Item
    part: TextPart

    def cited(self) -> str:
        """Name it as it's cited: its item's number, and its place in it."""
        return f"@{self.item.number}.{self.part.place}"


class PartCited(Model):
    """What a citation of a part names: an item's number, and a place in it."""

    item: int
    place: int


def part_cited(cited: str) -> PartCited | None:
    """Return what `cited` names where it cites a part, `@` before it or not; none where it doesn't: no name reads so, a name's every segment holding a letter.

    >>> part_cited("@12.3"), part_cited("12"), part_cited("v1.2")
    (PartCited(item=12, place=3), None, None)
    """
    rows = csv.reader(
        cited.removeprefix("@").splitlines(), delimiter=".", quoting=csv.QUOTE_NONE
    )
    match list(rows):
        case [[item, place]] if item.isdecimal() and place.isdecimal():
            return PartCited(item=int(item), place=int(place))
        case _:
            return None


def broken(text: str) -> list[str]:
    r"""Return `text`'s lines, broken where markdown-it and the page break them: at `\r\n`, `\r` and `\n` alike, and nowhere else.

    >>> broken("a\r\nb\rc\x0cd\n")
    ['a', 'b', 'c\x0cd']
    """
    return [line.removesuffix("\n") for line in io.StringIO(text, newline=None)]


@cache
def reader() -> MarkdownIt:
    """Return what reads a text's blocks: CommonMark with GitHub's tables, and nothing read inside a block."""
    made = MarkdownIt("commonmark").enable("table")
    made.core.ruler.enableOnly(["normalize", "block"])
    return made


def starts(token: Token) -> bool:
    """Say whether `token` starts a part: a block at the top, but a list or a table, whose items and rows start one each; what's nested deeper stays in the part holding it."""
    match token.level, token.type:
        case 0, "bullet_list_open" | "ordered_list_open" | "table_open":
            return False
        case (0, _) | (1, "list_item_open") | (2, "tr_open"):
            return token.map is not None and token.nesting >= 0
        case _:
            return False


def parted(text: str) -> list[TextPart]:
    r"""Return the parts of `text`, in order, each numbered from 1: none of a blank one.

    >>> text = "Two ways:\n\n- shorter\n  - by far\n- safer\n\n| a |\n|---|\n| b |\n"
    >>> for each in parted(text):
    ...     print(each.place, each.line, each.lines)
    1 0 ['Two ways:']
    2 2 ['- shorter', '  - by far']
    3 4 ['- safer']
    4 6 ['| a |', '|---|']
    5 8 ['| b |']
    """
    lines = broken(text)
    opened = [
        token.map[0]
        for token in reader().parse(text)
        if starts(token) and token.map is not None
    ]
    bounds = [0, *opened[1:], len(lines)]

    def blank(line: str) -> bool:
        return not line.strip()

    def kept(first: int, until: int) -> TextPart:
        """Return the part of the lines from `first` to `until`, the blank ones around them left out, its place not said yet."""
        ahead = list(dropwhile(blank, lines[first:until]))
        behind = list(dropwhile(blank, reversed(ahead)))
        return TextPart(place=0, line=until - len(ahead), lines=behind[::-1])

    found = [kept(first, until) for first, until in pairwise(bounds)]
    return [
        each.model_copy(update={"place": place})
        for place, each in enumerate((each for each in found if each.lines), start=1)
    ]


def parts(item: Item) -> list[ItemPart]:
    """Return the parts of `item`, in order: its text's, then each thing it says beyond its text."""
    own = parted(item.text)
    beyond = [
        TextPart(place=place, line=0, lines=broken(said))
        for place, said in enumerate(item.beyond(), start=len(own) + 1)
    ]
    return [ItemPart(item=item, part=each) for each in [*own, *beyond]]
