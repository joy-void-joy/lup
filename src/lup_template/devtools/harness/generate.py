"""Ownership-safe generation engine beneath the harness CLI.

Each frozen ``GenerationRecipe`` compiles the canonical catalog through an
adapter, validates the rendered tree, reconciles it against recorded
ownership, materializes a conflict-free proposal, and saves the manifest.
Inspection exposes the same pipeline without writes. Console-facing command
bodies live in ``drift`` and ``reconcile``; ``composition`` maps target names
to concrete recipes.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.adapters.harness import compile_claude, compile_codex
from lup.adapters.claude.harness import (
    ClaudePromptRenderer,
    ClaudeSkillInvocationRenderer,
)
from lup.adapters.codex.harness import (
    CodexPromptRenderer,
    CodexSkillInvocationRenderer,
)
from lup.harness.materialization import AtomicMaterializer
from lup.harness.models import Artifact, ArtifactTree, Harness
from lup.harness.ownership import (
    OwnershipManifest,
    build_manifest,
    load_manifest,
    save_manifest,
)
from lup.harness.reconciliation import (
    DeterministicReconciler,
    FilesystemCurrentTreeReader,
    ReconciliationConflict,
    ReconciliationProposal,
)
from lup.harness.contracts import CurrentTreeReader, Reconciler
from lup_template.devtools.harness.catalog import portable_harness
from lup_template.devtools.harness.content.patterns import DOCUMENT as PATTERNS
from lup_template.devtools.harness.content.settings import project_settings
from lup_template.devtools.harness.content.template_claude import (
    DOCUMENT as TEMPLATE_CLAUDE,
)
from lup_template.devtools.harness.content.template_codex import (
    DOCUMENT as TEMPLATE_CODEX,
)


class GenerationRecipe(BaseModel):
    """Injected data and capabilities needed by neutral generation orchestration."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    label: str
    root: Path
    source: Harness
    desired: ArtifactTree
    manifest_path: Path
    prior: OwnershipManifest | None
    reader: CurrentTreeReader
    reconciler: Reconciler = DeterministicReconciler()
    target_requirements: list[str]


class HarnessGenerationConflict(RuntimeError):
    """Generated output collides with local or unproven content."""

    def __init__(self, conflicts: list[ReconciliationConflict]) -> None:
        detail = ", ".join(conflict.path.as_posix() for conflict in conflicts)
        super().__init__(f"harness generation has unresolved conflicts: {detail}")
        self.conflicts = conflicts


class GenerationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str
    changed: list[Path]
    removed: list[Path]
    source_digest: str


class DriftReport(BaseModel):
    """Read-only desired-tree comparison for pre-commit and CI."""

    model_config = ConfigDict(frozen=True)

    target: str
    ownership_present: bool
    proposal: ReconciliationProposal

    @property
    def clean(self) -> bool:
        return (
            self.ownership_present
            and not self.proposal.writes
            and not self.proposal.deletes
            and not self.proposal.conflicts
        )


def managed_paths(desired: ArtifactTree, prior: OwnershipManifest | None) -> list[Path]:
    """Combine desired and formerly owned paths for deletion detection."""
    paths = [artifact.path for artifact in desired.artifacts]
    if prior is not None:
        paths.extend(item.path for item in prior.files)
    return list(dict.fromkeys(paths))


def current_reader(
    prior: OwnershipManifest | None,
    desired: ArtifactTree,
    *,
    sensitive_local_only: list[Path],
) -> FilesystemCurrentTreeReader:
    """Build the ordinary ownership reader used by concrete native recipes."""
    return FilesystemCurrentTreeReader(
        prior,
        sensitive_local_only=sensitive_local_only,
        managed_paths=managed_paths(desired, prior),
    )


def claude_generation_recipe(root: Path) -> GenerationRecipe:
    """Compose the complete Claude tree from canonical typed declarations."""
    source = portable_harness(root=root)
    compiled = compile_claude(source)
    prompts = ClaudePromptRenderer(ClaudeSkillInvocationRenderer())
    content_root = Path(__file__).parent / "content"
    support_artifacts = [
        Artifact(
            path=Path(".claude/PATTERNS.md"),
            content=prompts.render(PATTERNS),
            semantic_id="harness.patterns",
        ),
        Artifact(
            path=Path(".claude/plugins/lup/TEMPLATE_CLAUDE.md"),
            content=prompts.render(TEMPLATE_CLAUDE),
            semantic_id="harness.template-guidance",
        ),
        Artifact(
            path=Path(".claude/plugins/lup/scripts/file_suggest.sh"),
            content=(content_root / "assets" / "file_suggest.sh").read_text(
                encoding="utf-8"
            ),
            semantic_id="harness.file-suggestion",
            executable=True,
        ),
        Artifact(
            path=Path(".claude/settings.json"),
            content=json.dumps(
                project_settings(source.plugins[0].hooks), indent=2, sort_keys=True
            ),
            semantic_id="harness.project-settings",
        ),
    ]
    desired = ArtifactTree(
        artifacts=sorted(
            [*compiled.artifacts, *support_artifacts],
            key=lambda artifact: artifact.path.as_posix(),
        )
    )
    manifest_path = root / ".claude" / ".lup-ownership.json"
    prior = load_manifest(manifest_path)
    reader = current_reader(
        prior,
        desired,
        sensitive_local_only=[Path(".claude/settings.local.json")],
    )
    return GenerationRecipe(
        label="claude",
        root=root,
        source=source,
        desired=desired,
        manifest_path=manifest_path,
        prior=prior,
        reader=reader,
        reconciler=DeterministicReconciler(),
        target_requirements=["claude-code"],
    )


def codex_generation_recipe(root: Path) -> GenerationRecipe:
    """Compose the Codex renderers, reader, and ownership location."""
    source = portable_harness(root=root)
    prompts = CodexPromptRenderer(CodexSkillInvocationRenderer())
    support_artifacts = [
        Artifact(
            path=Path(".codex/plugins/lup/TEMPLATE_AGENTS.md"),
            content=prompts.render(TEMPLATE_CODEX),
            semantic_id="harness.template-guidance",
        ),
    ]
    compiled = compile_codex(source)
    desired = ArtifactTree(
        artifacts=sorted(
            [*compiled.artifacts, *support_artifacts],
            key=lambda artifact: artifact.path.as_posix(),
        )
    )
    manifest_path = root / ".codex" / ".lup-ownership.json"
    prior = load_manifest(manifest_path)
    return GenerationRecipe(
        label="codex",
        root=root,
        source=source,
        desired=desired,
        manifest_path=manifest_path,
        prior=prior,
        reader=current_reader(
            prior,
            desired,
            sensitive_local_only=[Path(".codex/config.local.toml")],
        ),
        reconciler=DeterministicReconciler(),
        target_requirements=["codex-cli>=0.144"],
    )


def inspect_generation(recipe: GenerationRecipe) -> DriftReport:
    """Compute ownership-aware drift without changing the working tree."""
    current = recipe.reader.read(recipe.root)
    return DriftReport(
        target=recipe.label,
        ownership_present=recipe.prior is not None,
        proposal=recipe.reconciler.propose(current, recipe.desired),
    )


def generate(recipe: GenerationRecipe) -> GenerationReport:
    """Compile, reconcile, materialize, then update proof—never source prompts."""
    drift = inspect_generation(recipe)
    proposal = drift.proposal
    if proposal.conflicts:
        raise HarnessGenerationConflict(proposal.conflicts)
    result = AtomicMaterializer().apply(proposal)
    manifest = build_manifest(
        recipe.source,
        recipe.desired,
        generator_version=recipe.source.generator_version,
        target_requirements=recipe.target_requirements,
    )
    save_manifest(recipe.manifest_path, manifest)
    return GenerationReport(
        target=recipe.label,
        changed=result.changed,
        removed=result.removed,
        source_digest=manifest.source_digest,
    )
