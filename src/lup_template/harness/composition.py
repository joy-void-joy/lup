"""What this project publishes through each native target, and what writes it.

The builders and the selector are the library's; named here is only what is
this project's own — the content its harness compiles beside, the per-runtime
guidance each tree carries, and the generated files that belong to no native
tree at all.
"""

from functools import partial
from pathlib import Path

from lup.providers.claude.login import CLAUDE_LOGIN
from lup.harness.codescan.common import RuleSelection
from lup.devtools.dev.rules import write_rule_reference
from lup.devtools.dev.workflow import write_publish, write_workflow
from lup.devtools.harness.composition import (
    ClaudeComposer,
    CodexComposer,
    NativeTargets,
    local_profile_directory,
)
from lup.devtools.harness.drift import RepositoryWriter
from lup.devtools.harness.generate import (
    NativeHarnessComposition,
    ProjectContent,
)
from lup.devtools.harness.generated_paths import write_generated_paths
from lup.devtools.surfaces import LIBRARY_SURFACES
from lup.web.build import write_web_bundles
from lup.web.schema import write_view_schema
from lup.providers.profiles import ProfileDirectory
from lup.workspace.paths import project_root
from lup_template.harness.catalog import (
    LIBRARY_BUNDLES,
    LIBRARY_WEB,
    declared_hook_set,
    portable_harness,
    publish,
    vendoring,
    workflow,
)
from lup.harness.models import PromptDocument
from lup_template.harness.content.catalog import COMPOSED, Composed
from lup_template.harness.content.docs.catalog import documents
from lup_template.harness.content.modules.specs import TEMPLATE_INIT
import lup_template.harness.content.settings as settings_module
from lup_template.harness.content.settings import project_settings
from lup_template.harness.content.template_claude import (
    DOCUMENT as TEMPLATE_CLAUDE,
)
from lup_template.harness.content.template_codex import (
    DOCUMENT as TEMPLATE_CODEX,
)

CONTENT_ROOT = Path(__file__).parent / "content"


def project_content(
    root: Path, rules: RuleSelection | None = None, composed: Composed = COMPOSED
) -> ProjectContent:
    """Everything this repository publishes beside its compiled plugin tree.

    ``rules`` is a launch overruling what this repository holds itself to for
    one session, and nothing else reads it: what the repository actually
    settled stays the declaration in its catalog, which is what a review sees
    and what `dev seams` writes. ``composed`` is its module answer, for the
    same reason :func:`portable_harness` takes one.
    """
    harness = portable_harness(root=root, composed=composed)
    if rules is not None:
        harness = harness.holding(rules)
    return ProjectContent(
        harness=harness,
        documents=documents(root, composed),
        assets=[CONTENT_ROOT / "assets" / "file_suggest.sh"],
        settings=project_settings(harness.plugins[0]),
        settings_source=settings_module.__name__,
    )


def profile_directory() -> ProfileDirectory:
    """The Claude accounts this checkout keeps, under ``.lup/profiles``.

    Named once and reached by both the launcher and the setup wizard, so a
    name means the same account whichever tree the caller curates it through
    — which is the whole reason to keep the profiles here rather than let
    each entry point fall back to the operator's personal registry.
    """
    return local_profile_directory(project_root(), CLAUDE_LOGIN)


def template_guidance(
    document: PromptDocument, composed: Composed
) -> PromptDocument | None:
    """The guidance an installer merges into a target, where there is an installer.

    It is what `/lup:init` and `/lup:install` merge, so it belongs to the
    module shipping them: a project that declined standing projects up has
    nobody to hand it to, and publishes none rather than a document teaching
    two skills its plugin lacks.
    """
    return document if composed.selection.takes(TEMPLATE_INIT) else None


def claude_target(
    root: Path, rules: RuleSelection | None = None, composed: Composed = COMPOSED
) -> NativeHarnessComposition:
    """This project's content, compiled through the Claude adapter."""
    return ClaudeComposer().compose(
        root,
        project_content(root, rules, composed),
        template_guidance(TEMPLATE_CLAUDE, composed),
    )


def codex_target(
    root: Path, rules: RuleSelection | None = None, composed: Composed = COMPOSED
) -> NativeHarnessComposition:
    """This project's content, compiled through the Codex adapter."""
    return CodexComposer().compose(
        root,
        project_content(root, rules, composed),
        template_guidance(TEMPLATE_CODEX, composed),
    )


TARGETS = NativeTargets(builders={"claude": claude_target, "codex": codex_target})
"""Every native runtime this project generates a tree for, by CLI selector."""


def repository_writers(vendored: bool | None = None) -> list[RepositoryWriter]:
    """Every project-owned generated file outside a native runtime tree.

    The frontend's schema and bundles are the vendored library's build
    products, written into its own tree, so a project resolving lup as a
    dependency writes neither — the wheel it installed already carries them.
    """
    library = [
        # The schema before the bundles, because the frontend build compiles
        # its types from it: written in this order, one generation leaves both
        # true. Both read the one surface list, so a page and its types cannot
        # disagree about which surfaces exist.
        partial(
            write_view_schema,
            Path(LIBRARY_WEB) / "schema" / "views.json",
            LIBRARY_SURFACES,
        ),
        partial(
            write_web_bundles,
            Path(LIBRARY_WEB),
            Path(LIBRARY_BUNDLES),
            LIBRARY_SURFACES,
        ),
    ]
    return [
        partial(write_rule_reference, selection=declared_hook_set().rules),
        partial(write_workflow, workflow(vendored)),
        partial(write_publish, publish(vendored)),
        partial(write_generated_paths, TARGETS),
        *(library if vendoring(vendored) else []),
    ]


REPOSITORY_WIDE = repository_writers()
"""This project's generated files outside a native tree, in its library mode."""
