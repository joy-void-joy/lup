"""Rendering Markdown structures that are generated rather than authored.

Prose written by a human is Markdown all the way down and needs nothing here.
What needs a renderer is a table *derived* from declarations: a pipe or a
newline in a value silently breaks the row it lands in, and the layout is the
same every time it is written by hand.

Escaping belongs at the leaf where data enters the document, not at the table:
a cell is built from :func:`cell`, :func:`code` or :func:`link` — each of
which escapes what it is given — and the table lays the finished cells out
without looking inside them. That is what lets one cell hold formatting the
author meant while the value inside it stays literal.
"""

import html

from pydantic import BaseModel, ConfigDict


def cell(value: str) -> str:
    """Escape generated text so it survives as the content of one cell."""
    return html.escape(value).translate(str.maketrans({"|": "&#124;", "\n": " "}))


def code(value: str) -> str:
    """One cell's worth of text, escaped and marked as code."""
    return f"`{cell(value)}`"


def link(text: str, target: str) -> str:
    """An inline link, for a cell naming a page rather than describing one."""
    return f"[{cell(text)}]({target})"


# lup: The markdown utils seem wrong. This should instead be a `TextPart`
# subclass (or whatever the more general of that class is) that takes the table
# to render as a param in list-of-list form, and then renders it — so a
# generated table is a document part like any other rather than a string a
# caller has to remember to escape into and splice by hand.
class MarkdownTable(BaseModel):
    """A header row and the finished cells beneath it.

    Rows hold cells that are already rendered, so a caller composes each one
    out of the pieces above and this only decides the layout.
    """

    # lup: Add an anti-pattern on `model_config =` and instruct the agent to use
    # the modern `class A(BaseModel, frozen=True, ...)` notation instead, then
    # convert the ones we already have — this line is one of them.
    model_config = ConfigDict(frozen=True)

    headers: list[str]
    rows: list[list[str]]

    def render(self) -> str:
        """The table as Markdown, one line per row, newline-terminated."""
        lines = [
            self.headers,
            ["---"] * len(self.headers),
            *self.rows,
        ]
        return "".join(f"| {' | '.join(line)} |\n" for line in lines)
