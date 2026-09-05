# lup: ignore[constant-declaration]
# Every constant here is this repository's own composition — which documents it
# publishes and where their sources live. A composition root is where a
# judgement is finally made rather than passed on, so there is no caller above
# it to take these from.
"""Every document this repository publishes under ``docs/``.

The pages about lup's own machinery come from the library; declared here are
the two whose subject is this repository — what the template half is, and the
decisions behind its development tooling — plus the index that lists both.
Generation turns the roster into artifacts, so a document that is not
declared here does not exist and a file under ``docs/`` that is not produced
from here is deleted as unowned. Nothing beneath ``docs/`` is hand-written.
"""

from pathlib import Path

import lup.harness.models as models
from lup.providers.claude.harness import CLAUDE_DISPATCHER
from lup.providers.codex.harness import CODEX_DISPATCHER
from lup.devtools.harness.content.docs.catalog import library_documents, published
from lup_template.devtools.harness.content.catalog import (
    AGENTS,
    LAYOUT,
    PLUGIN_NAME,
    SKILLS,
)
from lup_template.devtools.harness.content.docs import decisions, index, template

CONTENT_ROOT = LAYOUT.path("devtools", "harness", "content")
"""Directory every content module this repository authors lives beneath."""

DOCS_ROOT = f"{CONTENT_ROOT}/docs"
"""Directory every project-owned document's canonical module lives in."""

GENERATED_GUIDE = "docs/harness.md"
"""Document that explains what generated output is and how to change it."""


def reference_pages(root: Path) -> list[models.Document]:
    """The pages lup publishes about the machinery this repository is built on.

    The parity audit reads what each runtime decodes from the runtime itself,
    so composing them is what this root is for: the pages stay portable while
    the table they publish cannot claim a decoded set that stopped being true.

    Takes the checkout because *this* repository is the tree holding lup's own
    suite, which the capability page resolves its fixture citations against —
    the same reason :func:`project_pages` takes one, and the same reason
    neither is a module-level constant.

    It hands that checkout on only when the suite is actually in it, and that
    condition is the whole point rather than defensiveness. A project built
    from this scaffold resolves lup as a distribution: the fixtures the page
    cites ship with lup's repository and not with its wheel, so the citation
    stays true — it names where the evidence lives — while the path is simply
    not present to check. Passing the checkout unconditionally made every
    adopter's first `harness generate all` fail with `'packages/lup/tests/
    unit/test_adapter_runtime.py' is cited as evidence but does not exist`,
    which reads as a broken generator rather than as a tree that never had it.
    """
    return library_documents(
        SKILLS,
        AGENTS,
        PLUGIN_NAME,
        CLAUDE_DISPATCHER.routed_tools,
        CODEX_DISPATCHER.routed_tools,
        LAYOUT,
        root if (root / "packages" / "lup" / "tests").is_dir() else None,
    )


def project_pages(root: Path) -> list[models.Document]:
    """The pages only this repository has, because only it has their subject.

    Built against a checkout rather than declared, because one of them draws
    the application's layout by walking it. Importing this module therefore
    reads no filesystem — which is what lets the CLI be imported from a
    directory that is not this repository at all.
    """
    return [
        published("template", "template.md", template.document(root), DOCS_ROOT),
        published(
            "decisions", "dev-tooling-decisions.md", decisions.DOCUMENT, DOCS_ROOT
        ),
    ]


def documents(root: Path) -> list[models.Document]:
    """Every document under ``docs/``, the index first because it teaches the rest."""
    reference = reference_pages(root)
    project = project_pages(root)
    return [
        published("index", "README.md", index.document(reference, project), DOCS_ROOT),
        *reference,
        *project,
    ]
