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
import textwrap
from functools import cache
from itertools import dropwhile, pairwise
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

from lup.inbox.records import Item
from lup.shell.blocks import Anchor, Markdown, broken
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


class Stretch(Model):
    """A stretch of an item's words laid out as a block of its own: its text, or one thing it says beyond its text, a part alone."""

    item: Item
    text: str
    parts: list[TextPart]
    """Its parts, each at its line of the stretch."""
    alone: int | None = None
    """The place of the part it is, for one thing said beyond the text; none
    for the text."""
    of: int
    """How many parts its item has."""

    def block(self) -> Markdown:
        """Return it as Markdown, each of its parts anchored at its first line by what cites it: none where its item has one part, which its number names."""
        key = "text" if self.alone is None else f"part-{self.alone}"
        return Markdown(
            id=f"item-{self.item.number}-{key}",
            text=self.text,
            anchors=[
                Anchor(line=each.line, cited=f"@{self.item.number}.{each.place}")
                for each in self.parts
                if self.of > 1
            ],
        )


def stretches(item: Item) -> list[Stretch]:
    """Return the stretches of `item`'s words, in order: its text, where it isn't blank, then each thing it says beyond it, their parts numbered on."""
    own = parted(item.text)
    beyond = item.beyond()
    of = len(own) + len(beyond)
    return [
        *([Stretch(item=item, text=item.text, parts=own, of=of)] if own else []),
        *(
            Stretch(
                item=item,
                text=said,
                parts=[TextPart(place=place, line=0, lines=broken(said))],
                alone=place,
                of=of,
            )
            for place, said in enumerate(beyond, start=len(own) + 1)
        ),
    ]


def parts(item: Item) -> list[ItemPart]:
    """Return the parts of `item`, in order: its text's, then each thing it says beyond its text."""
    return [
        ItemPart(item=item, part=each)
        for stretch in stretches(item)
        for each in stretch.parts
    ]


class Quoted(Model):
    """Which parts of an item the lines a comment quotes are on: the first, and the last where they run over several."""

    part: int
    last: int | None = None


def quoted(item: Item, lines: list[str], line: int) -> Quoted | None:
    """Return which parts of `item`'s text `lines` are on, quoted from its line `line`, from 0, on, else from the one place they stand; none where they stand at none, or at several."""
    text = broken(item.text)
    found = [
        at
        for at in range(len(text) - len(lines) + 1)
        if lines and text[at : at + len(lines)] == lines
    ]
    at = line if line in found else found[0] if len(found) == 1 else None
    own = parted(item.text)
    if at is None or not own:
        return None

    def holding(line: int) -> int:
        """Return the place of the part holding the line `line`: the last starting at it or before it, else the first."""
        return max((each.place for each in own if each.line <= line), default=1)

    first, last = holding(at), holding(at + len(lines) - 1)
    return Quoted(part=first, last=last if last > first else None)


def whole(item: Item, quoted: Quoted, lines: list[str]) -> bool:
    """Say whether `lines`, quoted of the parts of `item` `quoted` says, are those parts whole, blank lines aside: where they say nothing, they pick nothing out of them."""
    said = filled("\n".join(lines))
    spanned = [
        line
        for each in parts(item)
        if quoted.part <= each.part.place <= (quoted.last or quoted.part)
        for line in filled(each.part.text())
    ]
    return not said or said == spanned


def filled(text: str) -> list[str]:
    r"""Return `text`'s lines that say something.

    >>> filled("a\n\nb\n")
    ['a', 'b']
    """
    return [line for line in broken(text) if line.strip()]


def opening(text: str, longest: int = 80) -> str:
    r"""Return how `text` begins, where a number says the rest: its first line that says something, cut to `longest` characters at a word's end where it's of several words, `…` at its end where more follows it.

    >>> opening("Twenty kinds of line.\nFour carry what was said.")
    'Twenty kinds of line.…'
    >>> opening("Twenty kinds of line, and only four of them.", longest=30)
    'Twenty kinds of line, and…'
    """
    first, *rest = filled(text) or [""]
    shortened = textwrap.shorten(first, width=longest, placeholder="…")
    cut = first if shortened == "…" else shortened
    return f"{cut}…" if rest and not cut.endswith("…") else cut
