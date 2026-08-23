"""What each section of the always-loaded document costs, section by section.

The budget rows in ``dev check`` report one number for a document assembled
from twenty sections across two packages, which says a cut is needed and
nothing about where. Answering that meant rendering the tree and running an
awk one-liner over the headings, which is the shape of a command that does not
exist yet — so this is it.

Bytes are attributed to the heading they follow, because that is the unit
somebody condensing works in: a section is what you can delete, shorten, or
move to ``docs/`` as a whole, and its heading is what the pointer left behind
would name.
"""

import typer
from markdown_it import MarkdownIt
from pydantic import BaseModel

from lup.adapters.harness import guidance_artifacts
from lup.harness.models import (
    GUIDANCE_BYTE_BUDGET,
    TEMPLATE_GUIDANCE_HEADROOM,
    document_byte_size,
)
from lup.devtools.harness.generate import NativeHarnessComposition

parser = MarkdownIt()


class GuidanceSection(BaseModel, frozen=True):
    """One heading of the rendered document, and what it costs a session."""

    heading: str
    level: int
    used: int

    def describe(self, widest: int) -> str:
        """This section as one aligned row, indented by how deep it sits."""
        indent = "  " * (self.level - 1)
        return f"{self.used:{widest}d}  {indent}{self.heading}"


def guidance_sections(document: str) -> list[GuidanceSection]:
    """Split a rendered document into its headings, with the bytes under each.

    Parsed rather than scanned for lines starting with ``#``: a fenced code
    block full of shell comments spells the same shape, and this document
    carries several. Whatever precedes the first heading — the generated
    banner — is reported under its own name, because it is real weight nobody
    can edit away.
    """
    lines = document.splitlines(keepends=True)
    tokens = parser.parse(document)
    starts = [
        (token.map[0], token.tag, tokens[index + 1].content)
        for index, token in enumerate(tokens)
        if token.type == "heading_open" and token.map is not None
    ]
    bounds = [start for start, _, _ in starts] + [len(lines)]
    preamble = GuidanceSection(
        heading="(banner)",
        level=1,
        used=document_byte_size("".join(lines[: bounds[0]])),
    )
    sections = [
        GuidanceSection(
            heading=content,
            level=int(tag.removeprefix("h")),
            used=document_byte_size("".join(lines[start : bounds[index + 1]])),
        )
        for index, (start, tag, content) in enumerate(starts)
    ]
    return [preamble, *sections] if preamble.used else sections


def report(
    compositions: list[NativeHarnessComposition],
    scaffold: bool,
    by_size: bool,
    headroom: int = TEMPLATE_GUIDANCE_HEADROOM,
) -> None:
    """Print every guidance artifact's sections against the budget it answers to.

    Both trees rather than the heaviest one, because the two runtimes spell
    typed parts differently and a section can be the largest in one and not
    the other — which is exactly the section worth reading twice.
    """
    ceiling = GUIDANCE_BYTE_BUDGET - headroom if scaffold else GUIDANCE_BYTE_BUDGET
    for composition in compositions:
        for artifact in guidance_artifacts(composition.recipe.desired):
            sections = guidance_sections(artifact.content)
            used = document_byte_size(artifact.content)
            widest = len(str(max(section.used for section in sections)))
            ordered = (
                sorted(sections, key=lambda section: -section.used)
                if by_size
                else sections
            )
            typer.echo(f"\n{artifact.path.as_posix()}")
            for section in ordered:
                typer.echo(f"  {section.describe(widest)}")
            over = used - ceiling
            verdict = f"{-over} free" if over <= 0 else f"OVER BY {over}"
            typer.echo(f"  {'-' * (widest + 2)}")
            typer.echo(f"  {used:{widest}d}  total — {verdict} of {ceiling}")
    if scaffold:
        typer.echo(
            f"\nCeiling is the scaffold's: {GUIDANCE_BYTE_BUDGET} runtime budget "
            f"less {headroom} reserved for the domain that adopts this template."
        )
