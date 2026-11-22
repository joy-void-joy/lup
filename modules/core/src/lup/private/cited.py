"""An inbox item cited by its number, `@1505` or a part's `@1505.3`, found where Markdown reads prose.

On GitHub, `@1505` mentions a user and the number means nothing, so `Private`
withholds it from a commit's message and a post. Each is read by an inline rule
of markdown-it's, so none is read in code, a span or a block, nor after a
backslash; nor where its `@` follows a letter, a digit, an `@` or a `_`, as an
address's does (`name@1505.example`); nor where the number runs on into a word
(`@2x`) or a version (`@1.2.3`).
"""

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline

from lup.private.found import Found, Held
from lup.types import Model


class Placed(Model):
    """Where an item's number is in a block's inline text: its line there, from 0, and its column, from 1."""

    line: int
    column: int


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


def digits_from(src: str, at: int) -> int:
    """Return where the run of digits starting at `at` of `src` ends.

    >>> digits_from("@1505.3", 1), digits_from("@x", 1)
    (5, 1)
    """
    end = at
    while end < len(src) and src[end].isdigit():
        end += 1
    return end


# lup: ignore("FBT001", why="markdown-it calls an inline rule with its state and whether it's silent, positionally")
def numbering(state: StateInline, silent: bool) -> bool:
    """Read an item's number at the inline position `state` is at, as markdown-it's inline rules do: `@`, the item's number, and a part's after a dot, leaving a token saying what it read, its line and its column in the inline text."""
    src, start = state.src, state.pos
    if src[start] != "@":
        return False
    before = src[start - 1] if start > 0 else ""
    if before.isalnum() or before in ["@", "_"]:
        return False
    end = digits_from(src, start + 1)
    if end == start + 1:
        return False
    if end + 1 < len(src) and src[end] == "." and src[end + 1].isdigit():
        end = digits_from(src, end + 1)
    if runs_on(src, end):
        return False
    if not silent:
        token = state.push("item_number", "", 0)
        # lup: ignore("string-slice", why="markdown-it's inline rules read their text by position, as its own rules do: the number is what lies between its `@` and where its digits end")
        token.content = src[start:end]
        opened = src.rfind("\n", 0, start) + 1
        token.meta = Placed(
            line=src.count("\n", 0, start), column=start - opened + 1
        ).model_dump()
    state.pos = end
    return True


def numbered(text: str) -> list[Found]:
    r"""Return each inbox item's number `text` cites where Markdown reads prose, with its line and column, in the order they come.

    >>> [(each.held.text, each.line, each.column) for each in numbered("saw @1505\nnot `@7`, nor \\@8, nor me@9.x")]
    [('@1505', 1, 5)]
    """
    reader = MarkdownIt("commonmark")
    reader.inline.ruler.before("text", "item_number", numbering)
    found: list[Found] = []
    for block in reader.parse(text):
        if block.type != "inline" or block.map is None or block.children is None:
            continue
        first = block.map[0] + 1
        found = [
            *found,
            *(
                Found(
                    held=Held(kind="item-number", text=each.content),
                    line=first + placed.line,
                    column=placed.column,
                    end=placed.column + len(each.content),
                )
                for each in block.children
                if each.type == "item_number"
                for placed in [Placed.model_validate(each.meta)]
            ),
        ]
    return found
