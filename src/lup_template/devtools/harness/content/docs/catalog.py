"""The roster of every document the repository publishes under ``docs/``.

One entry per document, each naming the path it renders to, the semantic id
ownership records it under, and the typed module it renders from. Generation
turns the roster into artifacts, so a document that is not declared here does
not exist and a file under ``docs/`` that is not produced from here is deleted
as unowned. Nothing beneath ``docs/`` is hand-written.

Explicit imports rather than a dynamic scan: a misspelled or missing module is
a type-checking error, and the reading order below is the order the index
teaches.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.harness.models import PromptDocument
from lup_template.devtools.harness.content.docs import (
    architecture,
    contributing,
    decisions,
    harness,
    index,
    library,
    native_capabilities,
    orchestration,
    patterns,
    permissions,
    platform_differentiation,
    quality_pipeline,
    resolver,
    self_improvement,
    supervisor,
    template,
)

CONTENT_ROOT = "src/lup_template/devtools/harness/content"
"""Directory every canonical content module lives beneath."""

DOCS_ROOT = f"{CONTENT_ROOT}/docs"
"""Directory every published document's canonical module lives in."""

GENERATED_GUIDE = "docs/harness.md"
"""Document that explains what generated output is and how to change it."""


class Document(BaseModel):
    """One generated repository document and where it renders."""

    model_config = ConfigDict(frozen=True)

    path: Path
    semantic_id: str
    source: str
    document: PromptDocument


def published(module: str, filename: str, document: PromptDocument) -> Document:
    """Declare one document rendered from its like-named content module."""
    return Document(
        path=Path("docs") / filename,
        semantic_id=f"docs.{Path(filename).stem}",
        source=f"{DOCS_ROOT}/{module}.py",
        document=document,
    )


DOCUMENTS = [
    published("index", "README.md", index.DOCUMENT),
    published("library", "library.md", library.DOCUMENT),
    published("template", "template.md", template.DOCUMENT),
    published("harness", "harness.md", harness.DOCUMENT),
    published("architecture", "architecture.md", architecture.DOCUMENT),
    published("permissions", "permissions.md", permissions.DOCUMENT),
    published("resolver", "resolver.md", resolver.DOCUMENT),
    published("supervisor", "supervisor.md", supervisor.DOCUMENT),
    published(
        "platform_differentiation",
        "platform-differentiation.md",
        platform_differentiation.DOCUMENT,
    ),
    published(
        "native_capabilities", "native-capabilities.md", native_capabilities.DOCUMENT
    ),
    published("self_improvement", "self-improvement.md", self_improvement.DOCUMENT),
    published("contributing", "contributing.md", contributing.DOCUMENT),
    published("quality_pipeline", "quality-pipeline.md", quality_pipeline.DOCUMENT),
    published("decisions", "dev-tooling-decisions.md", decisions.DOCUMENT),
    published("orchestration", "orchestration.md", orchestration.DOCUMENT),
    published("patterns", "patterns.md", patterns.DOCUMENT),
]
"""Every document under ``docs/``, in the order the index teaches them."""
