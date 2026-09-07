"""Every document this repository publishes under ``docs/``.

There is no roster of pages here, because a page belongs to the subject it
describes and every subject is a module. What this root does instead is supply
what a page may need and its own module cannot know — the reading project's
layout, the checkout being described, the composed roster three pages audit,
and what each runtime's hook decodes — and then compose whatever the adopted
modules published.

The index is added last and separately, because its subject is the result: it
is the one page no module can declare, since no module can see what the others
contributed. Generation turns the composed list into artifacts, so a page no
adopted module declares does not exist and a file under ``docs/`` produced from
nowhere is deleted as unowned. Nothing beneath ``docs/`` is hand-written.
"""

from pathlib import Path

import lup.harness.models as models
from lup.harness.content.docs.catalog import published
from lup.harness.modules import DocumentContext, composed_documents
from lup.providers.claude.harness import CLAUDE_DISPATCHER
from lup.providers.codex.harness import CODEX_DISPATCHER
from lup_template.devtools.dev.library import LibraryMode, read_mode
from lup_template.harness.content.catalog import (
    AGENTS,
    LAYOUT,
    MODULES,
    PLUGIN_NAME,
    SKILLS,
)
from lup_template.harness.content.docs import index

DOCS_ROOT = LAYOUT.path("harness", "content", "docs")
"""Directory this repository's own page modules live in, for their banners."""


def context(root: Path) -> DocumentContext:
    """What the adopted modules' pages render against, for one checkout.

    Built against a checkout rather than declared, because two of the pages
    read one: the template page draws the application's layout by walking it,
    and the capability page resolves its fixture citations against lup's own
    suite. Importing this module therefore reads no filesystem and building a
    page does — which is what lets the CLI be imported from a directory that is
    not this repository at all.

    Whether lup's suite is in this tree is what the library mode declares, so
    the mode is what decides it. ``local`` wires ``packages/lup`` in as a
    workspace member and is refused unless the package is there; the other
    three resolve lup as a distribution, which ships the code those fixtures
    pin and none of the fixtures themselves. The citation names where the
    evidence lives in *lup's* repository, which is true read from anywhere —
    only its existence is checked, and only against the one mode whose tree is
    required to hold it. Asking the mode rather than testing for the directory
    is what keeps a copy left behind by ``--keep-vendored`` from voting on a
    page describing the lup actually being resolved.
    """
    return DocumentContext(
        layout=LAYOUT,
        root=root,
        skills=SKILLS,
        agents=AGENTS,
        plugin=PLUGIN_NAME,
        claude_decodes=CLAUDE_DISPATCHER.routed_tools,
        codex_decodes=CODEX_DISPATCHER.routed_tools,
        library_checkout=root if read_mode(root) is LibraryMode.LOCAL else None,
    )


def documents(root: Path) -> list[models.Document]:
    """Every document under ``docs/``, the index first because it teaches the rest."""
    pages = composed_documents(MODULES, context(root))
    return [published("index", "README.md", index.document(pages), DOCS_ROOT), *pages]
