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

from pydantic import BaseModel

import lup.harness.models as models
from lup.formats.markdown import LinkCell, PlainCell


class IndexEntry(BaseModel, frozen=True):
    """One row of the index: a page, and the question it answers."""

    link: str
    answers: str


class IndexGroup(BaseModel, frozen=True):
    """One heading of the index, and the pages listed beneath it."""

    title: str
    entries: list[IndexEntry]
    blurb: str = ""
    """Prose between the heading and the table, for a group that needs it."""

    def parts(self) -> list[models.PromptPart]:
        """This heading, its blurb, and its rows as a table part."""
        blurb = f"{self.blurb}\n\n" if self.blurb else ""
        return [
            models.TextPart(text=f"## {self.title}\n\n{blurb}"),
            models.MarkdownTable(
                headers=["Page", "Answers"],
                rows=[
                    [
                        LinkCell(text=item.link, target=item.link),
                        PlainCell(text=item.answers),
                    ]
                    for item in self.entries
                ],
            ),
            models.TextPart(text="\n"),
        ]


def entry(document: models.Document, answers: str) -> IndexEntry:
    """An index row for a declared document, linked by where it renders.

    Taking the link off the declaration is what keeps the index from
    outliving a rename: a page that moved moves its own row.
    """
    return IndexEntry(link=document.path.name, answers=answers)


class PageIndex(BaseModel, frozen=True):
    """The pages a composition actually published, reachable by semantic id.

    An index lists pages the reading project may not have. Modules decide
    which documents exist, so a row naming one whose module was declined is
    not a dead link somebody forgot to delete — it is a subject this project
    does not have, and the index says less. A lookup therefore yields rows
    rather than a page: none where the module is gone, one where it is there,
    and the group that listed it renders either way.
    """

    pages: dict[str, models.Document]

    def rows(self, semantic_id: str, answers: str) -> list[IndexEntry]:
        """The row for one page, or no row at all where nothing published it."""
        page = self.pages.get(semantic_id)
        return [] if page is None else [entry(page, answers)]


def page_index(documents: list[models.Document]) -> PageIndex:
    """What an index may link to, keyed by the identity ownership records."""
    return PageIndex(pages={page.semantic_id: page for page in documents})


def document_index(
    preamble: list[models.PromptPart],
    groups: list[IndexGroup],
    epilogue: list[models.PromptPart],
) -> models.PromptDocument:
    """Compose an index from a project's own words and the pages it declares.

    A group with nothing left in it renders as nothing. Its heading and blurb
    describe pages, so a project that declined every module behind one is owed
    silence rather than an empty table under a promise.
    """
    return models.PromptDocument(
        source=__name__,
        parts=[
            *preamble,
            *[part for group in groups if group.entries for part in group.parts()],
            *epilogue,
        ],
    )
