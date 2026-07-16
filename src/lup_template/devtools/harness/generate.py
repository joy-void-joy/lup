"""Ownership-safe generation shared by explicit native CLI entry points."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.adapters.harness import compile_claude, compile_codex
from lup.adapters.claude.harness import ClaudeHookRenderer
from lup.harness.materialization import AtomicMaterializer
from lup.harness.models import (
    Artifact,
    ArtifactTree,
    Harness,
    OwnershipManifest,
    ReconciliationConflict,
    ReconciliationProposal,
)
from lup.harness.ownership import build_manifest, load_manifest, save_manifest
from lup.harness.reconciliation import (
    DeterministicReconciler,
    FilesystemCurrentTreeReader,
)
from lup.harness.contracts import CurrentTreeReader, Reconciler
from lup_template.devtools.harness.catalog import (
    ClaudeParityCurrentTreeReader,
    CLAUDE_RESOLVER_ENTRY,
    claude_parity_tree,
    portable_harness,
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
    """Compose the Claude parity renderer, reader, and ownership location."""
    source = portable_harness(root=root)
    baseline = claude_parity_tree(root)
    compiled = compile_claude(source)
    hook_artifacts = [
        artifact
        for plugin in source.plugins
        if plugin.hooks is not None
        for artifact in ClaudeHookRenderer(plugin.name).render(plugin.hooks).artifacts
    ]
    support_paths = {
        Path(".claude/plugins/lup/commands/implementer.md"),
        Path(".claude/plugins/lup/commands/resolve-reviewer.md"),
    }
    support_artifacts = [
        artifact for artifact in compiled.artifacts if artifact.path in support_paths
    ]
    resolver_entry = Artifact(
        path=Path(".claude/workflows/commands/resolve.js"),
        content=CLAUDE_RESOLVER_ENTRY,
        semantic_id="resolver.lup.entry",
    )
    overrides = {
        artifact.path: artifact
        for artifact in [*hook_artifacts, *support_artifacts, resolver_entry]
    }
    desired = ArtifactTree(
        artifacts=sorted(
            [
                *[
                    artifact
                    for artifact in baseline.artifacts
                    if artifact.path not in overrides
                ],
                *overrides.values(),
            ],
            key=lambda artifact: artifact.path.as_posix(),
        )
    )
    manifest_path = root / ".claude" / ".lup-ownership.json"
    prior = load_manifest(manifest_path)
    reader = ClaudeParityCurrentTreeReader(
        current_reader(
            prior,
            desired,
            sensitive_local_only=[Path(".claude/settings.local.json")],
        ),
        desired,
        bootstrap=prior is None,
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
    desired = compile_codex(source)
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
