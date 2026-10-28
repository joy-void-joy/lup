"""An item of lup's inbox cited by its number, `@1505` or a part's `@1505.3`, in text read where lup isn't: found where Markdown reads text.

`docs/inbox.md`, *Parties and items*. Sessions cite an item to the operator by
its number; on GitHub, `@1505` mentions a user, and the number means nothing to
a reader there. Each is read by an inline rule of markdown-it, as a citation of
the operator's words is (`inbox/citations.py`), so none is read in code, a span
or a block, nor after a backslash; nor where its `@` follows a letter, a digit,
an `@` or a `_`, as an address's does (`name@1505.example`); nor where the
number runs on into a word (`@2x`) or a version (`@1.2.3`). A mention
(`@name`) and a decorator (`@dataclass`) have no number.
"""

from bisect import bisect_right
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

from lup.types import Model
from lup_dev.inbox.citations import Said, opens, placed, scanned
from lup_dev.inbox.parts import Lines

if TYPE_CHECKING:
    from markdown_it.rules_inline import StateInline


class Number(Model):
    """An item's number a text writes outside code, and where: its line and column, each counted from 1, and that line whole."""

    said: str
    """The citation as it's written: `@1505`, or `@1505.3`."""
    line: int
    column: int
    text: str
    """Its line, whole, as the text writes it."""


def runs_on(src: str, at: int) -> bool:
    """Say whether what follows a number ending at `at` of `src` makes it part of something else: a letter, a digit or `_`, or a dot and a digit, as a version's next part does.

    >>> runs_on("@2x", 2), runs_on("@1.2.3", 4), runs_on("@1505.", 5), runs_on("@1505", 5)
    (True, True, False, False)
    """
    if at >= len(src):
        return False
    if src[at].isalnum() or src[at] == "_":
        return True
    return src[at] == "." and at + 1 < len(src) and src[at + 1].isdigit()


# lup: ignore("FBT001", why="markdown-it calls each inline rule as `rule(state, silent)`, its flag positional")
def numbering(state: StateInline, silent: bool) -> bool:
    """Read an item's number at the inline position `state` is at, as markdown-it's inline rules do: `@`, the item's number, and a part's after a dot.

    The token it leaves says what it read, and how many times the same is
    written before it in the inline text (`Said`), so it's placed in the text
    whole; where `silent`, markdown-it only asks whether one is there, and none
    is left.
    """
    src, start = state.src, state.pos
    if not opens(src, start):
        return False
    item = scanned(src, start + 1, str.isdigit)
    if not item.text:
        return False
    part = ""
    at = item.at
    if at + 1 < len(src) and src[at] == "." and src[at + 1].isdigit():
        read = scanned(src, at + 1, str.isdigit)
        part, at = f".{read.text}", read.at
    if runs_on(src, at):
        return False
    if not silent:
        said = f"@{item.text}{part}"
        token = state.push("item_number", "", 0)
        token.content = said
        token.meta = Said(said=said, before=src.count(said, 0, start)).model_dump()
    state.pos = at
    return True


def reader() -> MarkdownIt:
    """Return the Markdown reader items' numbers are read with: as citations are read (`inbox/citations.py`), with the inline rule reading an item's number (`numbering`)."""
    made = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    made.inline.ruler.push("item_number", numbering)
    return made


NUMBERING = reader()
"""Reads a text's items' numbers, where Markdown reads its text."""


def numbered(text: str) -> list[Number]:
    r"""Return each item's number `text` writes outside code, in order, where it's written.

    >>> [(each.said, each.line, each.column) for each in numbered("Fixes @1505.\n\nSee @1505.3 and `@7`, not a@8.")]
    [('@1505', 1, 7), ('@1505.3', 3, 5)]
    """
    lines = Lines.of(text)

    def located(said: Said) -> Number:
        index = bisect_right(lines.starts, said.start) - 1
        return Number(
            said=said.said,
            line=index + 1,
            column=said.start - lines.starts[index] + 1,
            text=lines.lines[index],
        )

    return [located(each) for each in placed(text, NUMBERING, "item_number", Said)]
