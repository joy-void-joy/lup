"""The nodes a generated Markdown document is laid out from.

Rendering Markdown that is generated rather than authored, escaping at the
leaf where data enters the document. Only `devtools` renders such documents
today, but nothing in it is about development tooling.

Prose written by a human is Markdown all the way down and needs nothing here,
and :class:`Prose` is the block where it passes through saying exactly that.
What needs a renderer is the value *derived* from a declaration: a pipe or a
newline breaks the table row it lands in, a newline ends the heading it was
interpolated into, and a backtick closes the fence it sits inside early. One
rule, at every place a derived value enters — which is why the leaves below
are inline nodes and not table cells.

An inline node holds the literal value it stands for and escapes that value as
it renders, so there is no way to put text in a document that does not survive
being there. What the kinds differ on is the formatting the author meant
around the value — plain, code, a link — never whether the value inside stays
literal. The table that lays them out in rows is
:class:`lup.harness.models.MarkdownTable`, a prompt part like any other, which
composes them without looking inside them.
"""

import html
from abc import ABC, abstractmethod
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator

from lup.formats.yaml import YamlDocument


def contained(value: str) -> str:
    r"""Neutralize every character that would end a cell or a row early.

    The pipe is spelled ``\|`` rather than as an entity because GFM's table
    extension unescapes it while splitting the row, before anything parses
    what is inside a cell. So it survives in prose, inside a code span, and
    inside a raw HTML element alike, where ``&#124;`` survives only the two
    that decode an entity — inside a code span a reader is shown the entity
    itself. One spelling that reaches everywhere is what lets this be asked
    once rather than chosen per destination.

    Both line endings count: a lone carriage return ends a line for a Markdown
    reader exactly as a newline does, so leaving it would break the row one
    character short of the case anyone tests for.
    """
    return value.translate(str.maketrans({"|": r"\|", "\n": " ", "\r": " "}))


def escaped(value: str) -> str:
    """Generated text made safe to be the content of one cell.

    For a destination that decodes an escape. A Markdown code span does not:
    ``&lt;`` is shown there as written, while a bare ``<`` needs no help
    because nothing in a code span is read as markup — so a code span takes
    :func:`contained` alone and this would corrupt it.
    """
    return contained(html.escape(value))


def inlined(value: str) -> str:
    """Generated text made safe to stand inside a line of prose.

    The line is the container here, and a newline is the whole of what ends
    one: a value carrying it turns the rest of a sentence into a new block,
    or a heading into a heading and a paragraph after it. Nothing else is
    neutralized, because outside a table nothing else has to be — a pipe is a
    pipe, and a reader of the file should be shown the characters the value
    holds rather than the entities a cell would have needed.
    """
    return value.translate(str.maketrans({"\n": " ", "\r": " "}))


class InlineNode(BaseModel, ABC, frozen=True):
    """One derived value inside a generated document, as it is displayed.

    Every kind answers :meth:`render`, and every answer runs the value it
    holds through :func:`contained` — directly where the kind's destination
    reads a value verbatim, through :func:`escaped` where it decodes one — so
    a new kind of formatting is one class and cannot be the one that forgot.

    A table cell is where these started and is not what they are: the same
    node is what a heading compiled from a catalog holds, and what stands
    inside a sentence built from a declaration.
    """

    text: str

    @abstractmethod
    def render(self) -> str:
        """This node's Markdown, with the value it holds escaped."""


class PlainCell(InlineNode, frozen=True):
    """A value shown as it reads."""

    type: Literal["plain"] = "plain"

    def render(self) -> str:
        return escaped(self.text)


class CodeCell(InlineNode, frozen=True):
    """A value marked as code by the fence Markdown spells with backticks."""

    type: Literal["code"] = "code"

    def render(self) -> str:
        return f"`{contained(self.text)}`"


class HtmlCodeCell(InlineNode, frozen=True):
    """A value marked as code by the HTML element rather than the fence.

    For a value that may itself hold a backtick — a rule's matching shape, a
    snippet quoting one — which no fence of a fixed length survives.
    """

    type: Literal["html_code"] = "html_code"

    def render(self) -> str:
        return f"<code>{escaped(self.text)}</code>"


class LinkCell(InlineNode, frozen=True):
    """A cell naming a page rather than describing one.

    The destination is held to the row's structure but not otherwise escaped:
    the characters Markdown reserves inside a destination are the ones a real
    path uses, so quoting them would break the link this cell exists to make.
    """

    type: Literal["link"] = "link"
    target: str

    def render(self) -> str:
        return f"[{escaped(self.text)}]({contained(self.target)})"


class ProseCell(InlineNode, frozen=True):
    """A value standing in a line of prose, shown as it reads.

    The prose counterpart of :class:`PlainCell`, and the difference is the
    container rather than the formatting: a cell's destination decodes an
    entity and a paragraph's reader does not, so escaping an apostrophe here
    would put `&#x27;` in front of whoever reads the file.
    """

    type: Literal["prose"] = "prose"

    def render(self) -> str:
        return inlined(self.text)


class ProseCode(InlineNode, frozen=True):
    """A value shown as code inside a line of prose.

    A path, a command, a module name — the everyday derived value, and the
    reason :class:`CodeCell` is not it: a cell escapes a pipe for the row it
    sits in, which inside a code span is shown to the reader as the backslash
    it is.
    """

    type: Literal["prose_code"] = "prose_code"

    def render(self) -> str:
        return f"`{inlined(self.text)}`"


class ProseStrong(InlineNode, frozen=True):
    """A value a line of prose leads with, shown strong."""

    type: Literal["prose_strong"] = "prose_strong"

    def render(self) -> str:
        return f"**{inlined(self.text)}**"


type TableCell = Annotated[
    PlainCell
    | CodeCell
    | HtmlCodeCell
    | LinkCell
    | ProseCell
    | ProseCode
    | ProseStrong,
    Discriminator("type"),
]
"""Any inline node a generated document holds, parseable back from its render."""


class MarkdownBlock(BaseModel, ABC, frozen=True):
    """One block of a generated Markdown document."""

    @abstractmethod
    def render(self) -> str:
        """This block's Markdown, ending in the newline that closes it."""


class Prose(MarkdownBlock, frozen=True):
    """Markdown authored as Markdown, carried through as it was written.

    The hole this model keeps, and keeps on purpose. A skill's prose is
    written to be read by a model and by a person: it is not derived from a
    declaration, nothing escapes into it, and putting three hundred lines of
    it through constructors would buy a guarantee about text that was never
    at risk. What goes through the nodes is what a declaration produced.
    """

    type: Literal["prose"] = "prose"
    text: str

    def render(self) -> str:
        return self.text if self.text.endswith("\n") else f"{self.text}\n"


type MarkdownAny = Annotated[Prose, Discriminator("type")]
"""Any block a generated Markdown document holds."""


class MarkdownDocument(BaseModel, frozen=True):
    """A whole Markdown file: what a reader sees, and what a runtime reads.

    Frontmatter is the half this exists for. It is YAML inside a Markdown
    file — two containers, one of them fenced by the other — and it is where
    a description, a tool list or an argument name derived from a declaration
    enters a document that a runtime parses before it ever shows it to
    anyone. Held as a :class:`lup.formats.yaml.YamlDocument`, it is emitted
    and parsed back before this file is composed at all.
    """

    frontmatter: YamlDocument | None = None
    blocks: list[MarkdownAny]

    def text(self) -> str:
        """This document as Markdown, frontmatter fenced above the blocks."""
        opened = (
            "" if self.frontmatter is None else f"---\n{self.frontmatter.text()}---\n\n"
        )
        return opened + "".join(block.render() for block in self.blocks)
