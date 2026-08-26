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
from lup.devtools.dev.workflow import write_workflow
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
from lup.providers.profiles import ProfileDirectory
from lup.workspace.paths import project_root
from lup_template.devtools.harness.catalog import (
    WORKFLOW,
    declared_hook_set,
    portable_harness,
)
from lup_template.devtools.harness.content.docs.catalog import documents
import lup_template.devtools.harness.content.settings as settings_module
from lup_template.devtools.harness.content.settings import project_settings
from lup_template.devtools.harness.content.template_claude import (
    DOCUMENT as TEMPLATE_CLAUDE,
)
from lup_template.devtools.harness.content.template_codex import (
    DOCUMENT as TEMPLATE_CODEX,
)

CONTENT_ROOT = Path(__file__).parent / "content"


def project_content(root: Path, rules: RuleSelection | None = None) -> ProjectContent:
    """Everything this repository publishes beside its compiled plugin tree.

    ``rules`` is a launch overruling what this repository holds itself to for
    one session, and nothing else reads it: what the repository actually
    settled stays the declaration in its catalog, which is what a review sees
    and what `dev seams` writes.
    """
    harness = portable_harness(root=root)
    if rules is not None:
        harness = harness.holding(rules)
    return ProjectContent(
        harness=harness,
        documents=documents(root),
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


def claude_target(
    root: Path, rules: RuleSelection | None = None
) -> NativeHarnessComposition:
    """This project's content, compiled through the Claude adapter."""
    return ClaudeComposer().compose(root, project_content(root, rules), TEMPLATE_CLAUDE)


def codex_target(
    root: Path, rules: RuleSelection | None = None
) -> NativeHarnessComposition:
    """This project's content, compiled through the Codex adapter."""
    return CodexComposer().compose(root, project_content(root, rules), TEMPLATE_CODEX)


TARGETS = NativeTargets(builders={"claude": claude_target, "codex": codex_target})
"""Every native runtime this project generates a tree for, by CLI selector."""


# lup: ignore[constant-declaration] — which files outside a runtime tree this
# project generates, decided here because nothing sits above it to be asked
REPOSITORY_WIDE: list[RepositoryWriter] = [
    partial(write_rule_reference, selection=declared_hook_set().rules),
    partial(write_workflow, WORKFLOW),
    partial(write_generated_paths, TARGETS),
]
"""Every project-owned generated file outside a native runtime tree."""
