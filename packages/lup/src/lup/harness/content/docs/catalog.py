"""How one page under ``docs/`` is declared, wherever its module declares it.

There is no roster here. A page belongs to the subject it describes, so each
is declared by the module owning that subject and reaches a project only
because the project took the module — which is what lets a declined subject
stop publishing its page rather than leave one describing machinery nobody
has. What is left is the shape every such declaration shares: where a page
renders, the identity ownership records it under, and the module it renders
from.
"""

from pathlib import Path

import lup.harness.models as models

LIBRARY_DOCS_ROOT = "packages/lup/src/lup/harness/content/docs"
"""Where a checkout of this repository holds the library's own page modules.

A default rather than a constant: the path is only ever read as provenance in
a generated banner, and an adopter vendoring lup somewhere else wants the
banner to point at where the module actually is for them.
"""


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
