"""Canonical declaration, native rendering, and reconciliation tests."""

from pathlib import Path

import pytest
import sh

from lup.adapters.claude.harness import ClaudeSkillInvocationRenderer
from lup.adapters.codex.harness import CodexPromptRenderer, CodexSkillInvocationRenderer
from lup.adapters.codex.harness_runtime import (
    PluginCacheConfig,
    directory_digest,
    plugin_cache_evidence,
)
from lup.adapters.harness import compile_claude, compile_codex
from lup.harness.materialization import AtomicMaterializer, MaterializationConflictError
from lup.harness.models import (
    Artifact,
    ArtifactTree,
    CurrentArtifact,
    CurrentTree,
    Harness,
    InvocationArgument,
    PromptDocument,
    SkillInvocation,
    TextPart,
)
from lup.harness.ownership import build_manifest, save_manifest
from lup.harness.proposals import ReconciliationProposalWriter
from lup.harness.reconciliation import (
    DeterministicReconciler,
    FilesystemCurrentTreeReader,
    content_digest,
    source_patch_base_digest,
)
from lup_template.devtools.harness.catalog import (
    CLAUDE_BASELINE_PATHS,
    claude_parity_tree,
    portable_harness,
)
from lup_template.devtools.harness.generate import (
    GenerationRecipe,
    claude_generation_recipe,
    codex_generation_recipe,
    current_reader,
    generate,
    inspect_generation,
)
from lup_template.devtools.harness.importer import (
    OVERRIDES_PATH,
    ClaudeCommandFrontmatterImporter,
    render_overrides,
)


def test_catalog_has_one_portable_skill_per_baseline_command() -> None:
    harness = portable_harness()
    plugin = harness.plugins[0]

    assert len(plugin.skills) == 30
    assert len(plugin.agents) == 5
    assert {skill.name for skill in plugin.skills} >= {
        "resolve",
        "implementer",
        "resolve-reviewer",
        "merge",
    }
    encoded = harness.model_dump_json()
    assert "/lup:" not in encoded
    assert "$lup:" not in encoded


def test_locked_claude_parity_tree_preserves_all_tracked_baseline_artifacts() -> None:
    tree = claude_parity_tree(Path.cwd())

    assert len(tree.artifacts) == len(CLAUDE_BASELINE_PATHS) == 42
    assert sorted(artifact.path for artifact in tree.artifacts) == sorted(
        CLAUDE_BASELINE_PATHS
    )


def test_claude_recipe_overrides_legacy_hook_entry_with_hermetic_dispatcher() -> None:
    recipe = claude_generation_recipe(Path.cwd())
    artifacts = {artifact.path: artifact for artifact in recipe.desired.artifacts}

    hook_config = artifacts[Path(".claude/plugins/lup/hooks/hooks.json")].content
    assert "uv run" not in hook_config
    assert "hooks/scripts/policy.py" in hook_config
    assert Path(".claude/plugins/lup/hooks/runtime/kernel.py") in artifacts
    assert Path(".claude/plugins/lup/hooks/runtime/policy_data.py") in artifacts
    assert Path(".claude/plugins/lup/hooks/runtime/evidence.json") in artifacts


def test_generated_resolver_entries_only_launch_the_shared_python_core() -> None:
    claude = {
        artifact.path: artifact.content
        for artifact in claude_generation_recipe(Path.cwd()).desired.artifacts
    }
    codex = {
        artifact.path: artifact.content
        for artifact in codex_generation_recipe(Path.cwd()).desired.artifacts
    }
    command = claude[Path(".claude/plugins/lup/commands/resolve.md")]
    workflow = claude[Path(".claude/workflows/commands/resolve.js")]
    skill = codex[Path(".codex/plugins/lup/skills/resolve/SKILL.md")]

    workflow_call = 'Workflow(scriptPath=".claude/workflows/commands/resolve.js", args={})'  # lup: ignore[empty-collection]
    assert workflow_call in command
    assert "Triage into concerns" not in command
    assert "'harness',\n  'resolve',\n  '--adapter',\n  'claude'" in workflow
    assert "input.inventory" not in workflow
    assert "requires run_id" not in workflow
    assert "uv run lup-devtools harness resolve --adapter codex" in skill
    assert "scheduling" not in skill


def test_invocation_renderers_own_complete_spelling_and_escaping() -> None:
    invocation = SkillInvocation(
        plugin="lup",
        skill="merge",
        arguments=[InvocationArgument(name="target", value="feature with spaces")],
    )

    assert ClaudeSkillInvocationRenderer().render(invocation) == (
        "/lup:merge target='feature with spaces'"
    )
    assert CodexSkillInvocationRenderer().render(invocation) == (
        "$lup:merge target='feature with spaces'"
    )


def test_prompt_renderer_preserves_ordinary_trailing_whitespace() -> None:
    prompt = PromptDocument(parts=[TextPart(text="keep these spaces  ")])

    assert CodexPromptRenderer(CodexSkillInvocationRenderer()).render(prompt) == (
        "keep these spaces  \n"
    )


def test_canonical_text_rejects_provider_invocation_spelling() -> None:
    harness = portable_harness()
    payload = harness.model_dump(mode="python")
    payload["guidance"] = PromptDocument(parts=[TextPart(text="Run $lup:merge")])

    source = Harness.model_validate(payload)

    with pytest.raises(ValueError, match="provider invocation syntax"):
        compile_codex(source)


def test_artifact_paths_reject_backslash_traversal() -> None:
    with pytest.raises(ValueError, match="beneath its root"):
        Artifact(path=Path("..\\secret"), content="x", semantic_id="unsafe")


def test_both_native_trees_compile_deterministically() -> None:
    harness = portable_harness()
    claude = compile_claude(harness)
    codex = compile_codex(harness)

    assert claude == compile_claude(harness)
    assert codex == compile_codex(harness)
    assert (
        len([item for item in claude.artifacts if "/commands/" in item.path.as_posix()])
        == 30
    )
    assert len([item for item in codex.artifacts if item.path.name == "SKILL.md"]) == 30
    assert Path(".codex/plugins/lup/.codex-plugin/plugin.json") in {
        item.path for item in codex.artifacts
    }
    assert Path("AGENTS.md") in {item.path for item in codex.artifacts}
    claude_runtime = next(
        item.content
        for item in claude.artifacts
        if item.path.as_posix().endswith("hooks/runtime/kernel.py")
    )
    codex_runtime = next(
        item.content
        for item in codex.artifacts
        if item.path.as_posix().endswith("hooks/runtime/kernel.py")
    )
    assert claude_runtime == codex_runtime


def test_repository_generated_harness_is_drift_clean() -> None:
    reports = [
        inspect_generation(claude_generation_recipe(Path.cwd())),
        inspect_generation(codex_generation_recipe(Path.cwd())),
    ]

    assert all(report.clean for report in reports)


def test_generic_generation_accepts_an_injected_third_recipe(tmp_path: Path) -> None:
    desired = ArtifactTree(
        artifacts=[
            Artifact(
                path=Path(".third/plugin.txt"),
                content="third-provider\n",
                semantic_id="third.plugin",
            )
        ]
    )
    recipe = GenerationRecipe(
        label="third-provider",
        root=tmp_path,
        source=portable_harness(),
        desired=desired,
        manifest_path=tmp_path / ".third" / ".lup-ownership.json",
        prior=None,
        reader=current_reader(None, desired, sensitive_local_only=[]),
        target_requirements=["third-cli>=1"],
    )

    report = inspect_generation(recipe)

    assert report.target == "third-provider"
    assert [write.artifact.path for write in report.proposal.writes] == [
        Path(".third/plugin.txt")
    ]
    generated = generate(recipe)
    assert generated.target == "third-provider"
    assert (tmp_path / ".third" / "plugin.txt").read_text(encoding="utf-8") == (
        "third-provider\n"
    )
    assert recipe.manifest_path.is_file()


def test_reconciliation_preserves_local_and_sensitive_collisions(
    tmp_path: Path,
) -> None:
    local_content = "local\n"
    secret_content = "credential\n"
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("local.txt"),
                content=local_content,
                category="local_only",
                sha256=content_digest(local_content),
            ),
            CurrentArtifact(
                path=Path("secret.txt"),
                content="",
                category="sensitive_local_only",
                sha256=content_digest(secret_content),
            ),
        ],
    )
    desired = ArtifactTree(
        artifacts=[
            Artifact(path=Path("local.txt"), content="generated", semantic_id="local"),
            Artifact(
                path=Path("secret.txt"), content="generated", semantic_id="secret"
            ),
        ]
    )

    proposal = DeterministicReconciler().propose(current, desired)

    assert len(proposal.conflicts) == 2
    assert proposal.conflicts[1].sensitive
    with pytest.raises(MaterializationConflictError):
        AtomicMaterializer().apply(proposal)


def test_materialization_rejects_stale_base(tmp_path: Path) -> None:
    path = tmp_path / "owned.txt"
    path.write_text("old\n", encoding="utf-8")
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("owned.txt"),
                content="old\n",
                category="generated",
                sha256=content_digest("old\n"),
            )
        ],
    )
    desired = ArtifactTree(
        artifacts=[Artifact(path=Path("owned.txt"), content="new", semantic_id="owned")]
    )
    proposal = DeterministicReconciler().propose(current, desired)
    path.write_text("changed locally\n", encoding="utf-8")

    with pytest.raises(MaterializationConflictError, match="stale base"):
        AtomicMaterializer().apply(proposal)


def test_materialization_rejects_symlink_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    current = CurrentTree(root=root, artifacts=[])
    desired = ArtifactTree(
        artifacts=[
            Artifact(
                path=Path("link/escaped.txt"),
                content="unsafe",
                semantic_id="escape",
            )
        ]
    )
    proposal = DeterministicReconciler().propose(current, desired)

    with pytest.raises(MaterializationConflictError, match="symlink"):
        AtomicMaterializer().apply(proposal)
    assert not (outside / "escaped.txt").exists()


def test_exact_generated_content_can_acquire_first_ownership(tmp_path: Path) -> None:
    content = "generated\n"
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("new.txt"),
                content=content,
                category="unknown_conflict",
                sha256=content_digest(content),
            )
        ],
    )
    desired = ArtifactTree(
        artifacts=[Artifact(path=Path("new.txt"), content=content, semantic_id="new")]
    )

    proposal = DeterministicReconciler().propose(current, desired)

    assert proposal.conflicts == []
    assert proposal.writes == []


def test_interrupted_exact_write_can_reacquire_prior_ownership(tmp_path: Path) -> None:
    content = "new generated content\n"
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("owned.txt"),
                content=content,
                category="backpropagation_candidate",
                sha256=content_digest(content),
            )
        ],
    )
    desired = ArtifactTree(
        artifacts=[
            Artifact(path=Path("owned.txt"), content=content, semantic_id="owned")
        ]
    )

    proposal = DeterministicReconciler().propose(current, desired)

    assert proposal.conflicts == []
    assert proposal.writes == []


def test_native_override_does_not_silently_reown_backpropagation(
    tmp_path: Path,
) -> None:
    content = "locally changed native override\n"
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("owned.txt"),
                content=content,
                category="backpropagation_candidate",
                sha256=content_digest(content),
            )
        ],
    )
    desired = ArtifactTree(
        artifacts=[
            Artifact(path=Path("owned.txt"), content=content, semantic_id="owned")
        ]
    )

    proposal = DeterministicReconciler(adopt_exact_backpropagation=False).propose(
        current, desired
    )

    assert [conflict.category for conflict in proposal.conflicts] == [
        "backpropagation_candidate"
    ]


def test_codex_cache_digest_requires_an_exact_separate_copy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    home = tmp_path / "home"
    installed = home / "plugins" / "cache" / "lup-repository" / "lup" / "local"
    source.mkdir()
    installed.mkdir(parents=True)
    (source / "plugin.txt").write_text("same\n", encoding="utf-8")
    (installed / "plugin.txt").write_text("same\n", encoding="utf-8")
    config = PluginCacheConfig(codex_home=home)

    assert plugin_cache_evidence(source, config).ready
    (installed / "plugin.txt").write_text("stale\n", encoding="utf-8")
    assert not plugin_cache_evidence(source, config).ready


def test_codex_cache_digest_ignores_python_bytecode(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    (root / "__pycache__").mkdir(parents=True)
    (root / "policy.py").write_text("pass\n", encoding="utf-8")
    before = directory_digest(root)

    (root / "__pycache__" / "policy.cpython-314.pyc").write_bytes(b"cache")

    assert directory_digest(root) == before


def test_binary_managed_file_becomes_typed_unknown_conflict(tmp_path: Path) -> None:
    path = Path("managed.md")
    (tmp_path / path).write_bytes(b"\xff\xfe")

    tree = FilesystemCurrentTreeReader(None, managed_paths=[path]).read(tmp_path)

    assert tree.artifacts[0].category == "unknown_conflict"
    assert tree.artifacts[0].content == ""


def test_executable_mode_drift_is_not_treated_as_generated(tmp_path: Path) -> None:
    path = Path("hook.py")
    target = tmp_path / path
    target.write_text("pass\n", encoding="utf-8")
    target.chmod(0o644)
    source = portable_harness()
    manifest = build_manifest(
        source,
        ArtifactTree(
            artifacts=[
                Artifact(
                    path=path,
                    content="pass\n",
                    semantic_id="hook",
                    executable=True,
                )
            ]
        ),
        generator_version="test",
        target_requirements=[],
    )

    tree = FilesystemCurrentTreeReader(manifest, managed_paths=[path]).read(tmp_path)

    assert tree.artifacts[0].category == "generated"
    proposal = DeterministicReconciler().propose(
        tree,
        ArtifactTree(
            artifacts=[
                Artifact(
                    path=path,
                    content="pass\n",
                    semantic_id="hook",
                    executable=True,
                )
            ]
        ),
    )
    assert proposal.writes[0].artifact.executable


def test_generated_codex_hook_fails_closed_for_inline_code() -> None:
    script = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    result = sh.Command(str(script))(
        _in='{"tool_name":"Bash","tool_input":{"command":"python -c 1"}}',
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    assert isinstance(result, sh.RunningCommand)
    assert result.exit_code == 2
    assert b"interpreters" in result.stderr


def test_generated_codex_hook_fails_closed_for_unknown_tools() -> None:
    script = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    result = sh.Command(str(script))(
        _in='{"tool_name":"custom_tool","tool_input":{}}',
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    assert isinstance(result, sh.RunningCommand)
    assert result.exit_code == 2
    assert b"unknown tool" in result.stderr


def test_reconciliation_source_digest_rejects_a_stale_preimage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("old\n", encoding="utf-8")
    patch = """diff --git a/source.py b/source.py
--- a/source.py
+++ b/source.py
@@ -1 +1 @@
-old
+new
"""

    before = source_patch_base_digest(tmp_path, patch)
    source.write_text("changed after proposal\n", encoding="utf-8")

    assert source_patch_base_digest(tmp_path, patch) != before


def test_reconciliation_source_digest_tracks_new_file_absence(tmp_path: Path) -> None:
    patch = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+new
"""

    before = source_patch_base_digest(tmp_path, patch)
    (tmp_path / "new.py").write_text("occupied\n", encoding="utf-8")

    assert source_patch_base_digest(tmp_path, patch) != before


def test_source_patch_parser_does_not_treat_hunk_content_as_file_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.py"
    source.write_text("-- /dev/null\n", encoding="utf-8")
    patch = """diff --git a/source.py b/source.py
--- a/source.py
+++ b/source.py
@@ -1 +1 @@
--- /dev/null
+value
"""

    assert source_patch_base_digest(tmp_path, patch)


def test_reconciliation_source_digest_rejects_escaping_paths(tmp_path: Path) -> None:
    patch = """diff --git a/../secret b/../secret
--- a/../secret
+++ b/../secret
"""

    with pytest.raises(ValueError, match="escapes"):
        source_patch_base_digest(tmp_path, patch)


def test_typed_frontmatter_importer_writes_patch_only_for_description(
    tmp_path: Path,
) -> None:
    source = tmp_path / OVERRIDES_PATH
    source.parent.mkdir(parents=True)
    source.write_text(render_overrides({}), encoding="utf-8")
    path = Path(".claude/plugins/lup/commands/review.md")
    expected = "---\ndescription: Before\nallowed-tools: Read\n---\n\nBody\n"
    changed = "---\ndescription: After\nallowed-tools: Read\n---\n\nBody\n"
    current = [
        CurrentArtifact(
            path=path,
            content=changed,
            category="backpropagation_candidate",
            sha256=content_digest(changed),
        )
    ]

    result = ClaudeCommandFrontmatterImporter().import_changes(
        tmp_path, current, {path: expected}
    )

    assert result.imported_paths == [path]
    assert result.conflicts == []
    assert result.source_patch is not None
    assert 'description="After"' in result.source_patch
    record = ReconciliationProposalWriter().write(tmp_path, result.source_patch)
    directory = tmp_path / ".lup" / "reconcile" / record.proposal_id
    assert (directory / "source.patch").is_file()
    assert (directory / "metadata.json").is_file()


def test_typed_frontmatter_importer_rejects_prompt_body_changes(tmp_path: Path) -> None:
    source = tmp_path / OVERRIDES_PATH
    source.parent.mkdir(parents=True)
    source.write_text(render_overrides({}), encoding="utf-8")
    path = Path(".claude/plugins/lup/commands/review.md")
    expected = "---\ndescription: Same\n---\n\nBefore\n"
    changed = "---\ndescription: Same\n---\n\nAfter\n"

    result = ClaudeCommandFrontmatterImporter().import_changes(
        tmp_path,
        [
            CurrentArtifact(
                path=path,
                content=changed,
                category="backpropagation_candidate",
                sha256=content_digest(changed),
            )
        ],
        {path: expected},
    )

    assert result.source_patch is None
    assert result.imported_paths == []
    assert [conflict.path for conflict in result.conflicts] == [path]


def test_unchanged_ownership_manifest_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / ".native" / ".lup-ownership.json"
    manifest = build_manifest(
        portable_harness(),
        ArtifactTree(artifacts=[]),
        generator_version="test",
        target_requirements=[],
    )
    save_manifest(path, manifest)
    inode = path.stat().st_ino

    save_manifest(path, manifest)

    assert path.stat().st_ino == inode
