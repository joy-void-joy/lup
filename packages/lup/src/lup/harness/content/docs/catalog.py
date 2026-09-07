"""How one page under ``docs/`` is declared, wherever its module declares it.

There is no roster here. A page belongs to the subject it describes, so each
is declared by the module owning that subject and reaches a project only
because the project took the module — which is what lets a declined subject
stop publishing its page rather than leave one describing machinery nobody
has. What is left is the shape every such declaration shares: where a page
renders, the identity ownership records it under, and the module it renders
from.
"""

from collections.abc import Callable
from pathlib import Path

import lup.harness.models as models
from lup.harness.content.application import DocsRoot
from lup.harness.modules import DocumentContext, DocumentEntry

LIBRARY_DOCS = DocsRoot(
    path="packages/lup/src/lup/harness/content/docs",
    package=__package__ or "lup.harness.content.docs",
)
"""Where a checkout of this repository holds the library's own page modules.

A default rather than a constant: the path is only ever read as provenance in
a generated banner, and an adopter vendoring lup somewhere else wants the
banner to point at where the module actually is for them. The package is read
off this module's own position rather than written down, so a vendoring that
moves the tree cannot leave it naming an import root that is gone.
"""

LIBRARY_DOCS_ROOT = LIBRARY_DOCS.path
"""The library's page directory alone, for prose that only names the path."""


def published(
    module: str,
    filename: str,
    document: models.PromptDocument,
    root: str = LIBRARY_DOCS_ROOT,
) -> models.Document:
    """Declare one document rendered from its like-named content module.

    The root defaults to the library's own, because most pages are the
    library's and a module naming it at every call is a module repeating the
    one fact its location already states. A project's own page passes where
    its modules live, which is the only thing this cannot know.
    """
    return models.Document(
        path=Path("docs") / filename,
        semantic_id=f"docs.{Path(filename).stem}",
        source=f"{root}/{module}.py",
        document=document,
    )


def page(
    module: str,
    filename: str,
    prose: Callable[[DocumentContext], models.PromptDocument],
    docs: DocsRoot = LIBRARY_DOCS,
) -> DocumentEntry:
    """Declare one page a module publishes: where it lives, and how it renders.

    The identity and the declaring module are derived from the same two strings
    the rendering derives them from, so a module cannot record a page under one
    id and publish it under another — a divergence nothing else would catch,
    since the id is what a project retires a page by and the rendered document
    is what the index links to.
    """
    return DocumentEntry(
        semantic_id=f"docs.{Path(filename).stem}",
        source=f"{docs.package}.{module}",
        build=lambda context: published(module, filename, prose(context), docs.path),
    )
