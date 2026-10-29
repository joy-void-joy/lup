"""What an agent's words name with `@`, outside code: a thread or an agent by its name (`@dashboard-lag`), or a node by its number (`@2601`).

`docs/inbox.md`, *Threads*. Names are one set per repository, a thread's and an
agent's alike, and a name holds a letter, so `@` takes a name or a number and
never mistakes one for the other (`lup_ledger.records.named`). Where what an
item lands in a thread names another thread, lup draws a reference to it
(`Refers`), so the item shows there as one line (`inbox/concerns.py`).

Each is read by an inline rule of markdown-it, as an item's number is
(`inbox/numbers.py`), so none is read in code, nor after a backslash, nor
where its `@` follows a letter, a digit, an `@` or a `_`, as an address's
does. A citation of the operator's words (`@820.9[…]`, `@820.9`) names a part,
not a node, and isn't one; a subagent's path (`@dev/explore-auth`) names an
agent. A `.` or a `/` belongs to the name only where a letter or a digit
follows it, so a sentence's last `.` isn't read as part of one.
"""

import itertools
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

from lup_dev.inbox.citations import Said, opens, placed, ruled

if TYPE_CHECKING:
    from markdown_it.rules_inline import StateInline

    from lup_dev.inbox.citations import Asked


def named_up_to(src: str, at: int) -> int:
    """Return where a name starting at `at` of `src` ends: after each letter, digit, `-` and `_`, and each `.` or `/` a letter or a digit follows.

    >>> named_up_to("@lag. Then", 1), named_up_to("@dev/explore-auth", 1), named_up_to("@v1.2", 1)
    (4, 17, 5)
    """
    end = at
    while end < len(src):
        char = src[end]
        joined = char in "./" and end + 1 < len(src) and src[end + 1].isalnum()
        if not (char.isalnum() or char in "-_" or joined):
            return end
        end += 1
    return end


def mentioning(state: StateInline, asked: Asked) -> bool:
    """Read what `@` names at the inline position `state` is at, as markdown-it's inline rules do: a name or a number, not a citation's opening bracket after it.

    The token it leaves says what it read, and how many times the same is
    written before it in the inline text (`Said`), so it's placed in the text
    whole; where it's `seen`, markdown-it only asks whether one is there, and none
    is left.
    """
    src, start = state.src, state.pos
    if not opens(src, start):
        return False
    end = named_up_to(src, start + 1)
    if end == start + 1 or (end < len(src) and src[end] == "["):
        return False
    if asked == "read":
        said = "".join(itertools.islice(src, start, end))
        token = state.push("mention", "", 0)
        token.content = said
        token.meta = Said(said=said, before=src.count(said, 0, start)).model_dump()
    state.pos = end
    return True


def reader() -> MarkdownIt:
    """Return the Markdown reader what `@` names is read with: as citations are read (`inbox/citations.py`), with the inline rule reading one (`mentioning`)."""
    made = MarkdownIt("commonmark").enable(["table", "strikethrough"])
    made.inline.ruler.push("mention", ruled(mentioning))
    return made


MENTIONING = reader()
"""Reads what a text names with `@`, where Markdown reads its text."""


def mentioned(text: str) -> list[str]:
    r"""Return what `text` names with `@` outside code, each once, in the order first written, without its `@`: a name, a subagent's path, or a number.

    >>> mentioned("See @dashboard-lag and @2601, as @dev/explore-auth said; not `@x`, @820.9[why], a@b or @lag.")
    ['dashboard-lag', '2601', 'dev/explore-auth', 'lag']
    """
    said = [each.said for each in placed(text, MENTIONING, "mention", Said)]
    return list(dict.fromkeys(each.removeprefix("@") for each in said))
