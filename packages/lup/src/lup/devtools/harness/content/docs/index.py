"""How a documentation index is rendered from the pages actually declared.

The index is the one page whose subject is the other pages, so it is the one
page that goes stale silently: a document renamed or added on either side of
the library boundary leaves a row pointing nowhere, and nothing fails. Rows
are therefore built from the declarations — a link is the path a `Document`
already renders to, never a filename written down a second time.

What a page *answers* is index copy rather than a property of the page, so it
stays with the group that lists it. The preamble and epilogue are a project's
own words about its own repository, and pass through untouched.
"""

from pydantic import BaseModel, ConfigDict

import lup.harness.models as models
from lup.markdown import MarkdownTable, cell, link


class IndexEntry(BaseModel):
    """One row of the index: a page, and the question it answers."""

    model_config = ConfigDict(frozen=True)

    link: str
    answers: str


class IndexGroup(BaseModel):
    """One heading of the index, and the pages listed beneath it."""

    model_config = ConfigDict(frozen=True)

    title: str
    entries: list[IndexEntry]
    blurb: str = ""
    """Prose between the heading and the table, for a group that needs it."""


def entry(document: models.Document, answers: str) -> IndexEntry:
    """An index row for a declared document, linked by where it renders.

    Taking the link off the declaration is what keeps the index from
    outliving a rename: a page that moved moves its own row.
    """
    return IndexEntry(link=document.path.name, answers=answers)


def group_text(group: IndexGroup) -> str:
    """One heading, its blurb, and its rows as a Markdown table."""
    table = MarkdownTable(
        headers=["Page", "Answers"],
        rows=[
            [link(item.link, item.link), cell(item.answers)] for item in group.entries
        ],
    )
    blurb = f"{group.blurb}\n\n" if group.blurb else ""
    return f"## {group.title}\n\n{blurb}{table.render()}\n"


def document_index(
    preamble: list[models.PromptPart],
    groups: list[IndexGroup],
    epilogue: list[models.PromptPart],
) -> models.PromptDocument:
    """Compose an index from a project's own words and the pages it declares."""
    return models.PromptDocument(
        source=__name__,
        parts=[
            *preamble,
            models.TextPart(text="".join(group_text(group) for group in groups)),
            *epilogue,
        ],
    )
