"""Canonical declaration, native rendering, and reconciliation tests."""

import json
from pathlib import Path
from typing import Literal

import pytest
import sh
import typer
from pydantic import BaseModel, ConfigDict, Field

from lup.adapters.claude.harness import (
    ClaudePromptRenderer,
    ClaudeSkillInvocationRenderer,
)
from lup.adapters.codex.harness import CodexPromptRenderer, CodexSkillInvocationRenderer
from lup.adapters.codex.harness_runtime import (
    PluginCacheConfig,
    directory_digest,
    plugin_cache_evidence,
)
from lup.adapters.harness import compile_claude, compile_codex
from lup.harness.materialization import AtomicMaterializer, MaterializationConflictError
from lup.harness.models import (
    GUIDANCE_CHARACTER_BUDGET,
    Argument,
    Artifact,
    ArgumentsRef,
    ArtifactTree,
    Harness,
    InvocationArgument,
    PromptDocument,
    PromptPart,
    Skill,
    SkillInvocation,
    TextPart,
    document_text_size,
)
from lup.harness.ownership import (
    OwnershipManifestError,
    build_manifest,
    content_digest,
    load_manifest,
    save_manifest,
)
from lup.harness.proposals import ReconciliationProposalWriter
from lup.harness.reconciliation import (
    CurrentArtifact,
    CurrentTree,
    DeterministicReconciler,
    FilesystemCurrentTreeReader,
    source_patch_base_digest,
)
from lup.policy.bundle import policy_kernel_modules
from lup.types import EnvVars
from lup_template.devtools.harness.catalog import portable_harness
from lup_template.devtools.harness.content.guidance import DOCUMENT as GUIDANCE
from lup_template.devtools.harness.content.settings import project_settings
from lup_template.devtools.harness import launch
from lup_template.devtools.harness.launch import codex_sandbox_arguments
from lup_template.devtools.harness.content.template_claude import (
    DOCUMENT as TEMPLATE_CLAUDE,
)
from lup_template.devtools.harness.content.template_codex import (
    DOCUMENT as TEMPLATE_CODEX,
)
from lup_template.devtools.harness.generate import (
    GenerationRecipe,
    claude_generation_recipe,
    codex_generation_recipe,
    current_reader,
    generate,
    inspect_generation,
)


class ClaudeHookDecision(BaseModel):
    """Validated decision emitted by the generated Claude dispatcher."""

    model_config = ConfigDict(frozen=True)

    hook_event_name: Literal["PreToolUse"] = Field(alias="hookEventName")
    permission_decision: Literal["allow", "ask", "deny"] = Field(
        alias="permissionDecision"
    )
    permission_decision_reason: str = Field(alias="permissionDecisionReason")


class ClaudeHookOutput(BaseModel):
    """Generated Claude hook output envelope."""

    model_config = ConfigDict(frozen=True)

    hook_specific_output: ClaudeHookDecision = Field(alias="hookSpecificOutput")


class CodexPermissionDecision(BaseModel):
    """Validated permission decision emitted by the Codex dispatcher."""

    model_config = ConfigDict(frozen=True)

    behavior: Literal["allow", "deny"]


class CodexPermissionHookOutput(BaseModel):
    """Codex PermissionRequest hook-specific output."""

    model_config = ConfigDict(frozen=True)

    hook_event_name: Literal["PermissionRequest"] = Field(alias="hookEventName")
    decision: CodexPermissionDecision


class CodexPermissionOutput(BaseModel):
    """Generated Codex permission hook output envelope."""

    model_config = ConfigDict(frozen=True)

    hook_specific_output: CodexPermissionHookOutput = Field(alias="hookSpecificOutput")


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


def test_claude_tree_renders_every_typed_support_document() -> None:
    paths = {
        artifact.path
        for artifact in claude_generation_recipe(Path.cwd()).desired.artifacts
    }

    assert Path(".claude/PATTERNS.md") in paths
    assert Path(".claude/plugins/lup/TEMPLATE_CLAUDE.md") in paths
    assert Path(".claude/plugins/lup/scripts/file_suggest.sh") in paths
    assert Path(".claude/settings.json") in paths
    assert Path("docs/self-improvement.md") in paths
    assert Path("docs/permissions.md") in paths


def test_guidance_reaches_sections_by_name_not_by_anchor() -> None:
    """Guidance carried links to sections that live only in the adopter template.

    A same-document anchor resolves right up until the text it names moves to
    another document, and then fails silently. Naming the section, or the file
    that holds it, survives the move that broke the anchor.
    """
    rendered = ClaudePromptRenderer(ClaudeSkillInvocationRenderer()).render(GUIDANCE)

    assert "](#" not in rendered


def test_guidance_stays_within_its_always_loaded_budget() -> None:
    used = document_text_size(GUIDANCE)

    assert used <= GUIDANCE_CHARACTER_BUDGET, (
        f"guidance is {used} characters, over budget by "
        f"{used - GUIDANCE_CHARACTER_BUDGET}"
    )


def test_codex_tree_renders_the_agents_flavored_template() -> None:
    paths = {
        artifact.path
        for artifact in codex_generation_recipe(Path.cwd()).desired.artifacts
    }

    assert Path(".codex/plugins/lup/TEMPLATE_AGENTS.md") in paths


def test_template_flavors_share_sections_and_differ_natively() -> None:
    claude_render = ClaudePromptRenderer(ClaudeSkillInvocationRenderer()).render(
        TEMPLATE_CLAUDE
    )
    codex_render = CodexPromptRenderer(CodexSkillInvocationRenderer()).render(
        TEMPLATE_CODEX
    )

    def sections(render: str) -> list[str]:
        return [
            line for line in render.splitlines() if line.startswith("<!-- section: ")
        ]

    assert sections(claude_render)[0] == "<!-- section: CLAUDE.md -->"
    assert sections(codex_render)[0] == "<!-- section: AGENTS.md -->"
    assert sections(claude_render)[1:] == sections(codex_render)[1:]
    assert "/lup:init" in claude_render and "$lup:" not in claude_render
    assert "$lup:init" in codex_render and "/lup:" not in codex_render
    assert "AskUserQuestion" in claude_render
    assert "AskUserQuestion" not in codex_render
    # Session relocation is a Claude tool; Codex can only be told to start
    # a session in the worktree, never to call one it does not have.
    assert "EnterWorktree" in claude_render and "ExitWorktree" in claude_render
    assert "EnterWorktree" not in codex_render
    assert "ExitWorktree" not in codex_render


def test_claude_recipe_overrides_legacy_hook_entry_with_hermetic_dispatcher() -> None:
    recipe = claude_generation_recipe(Path.cwd())
    artifacts = {artifact.path: artifact for artifact in recipe.desired.artifacts}

    hook_config = artifacts[Path(".claude/plugins/lup/hooks/hooks.json")].content
    assert "uv run" not in hook_config
    assert "hooks/scripts/policy.py" in hook_config
    assert Path(".claude/plugins/lup/hooks/runtime/kernel/shell.py") in artifacts
    assert Path(".claude/plugins/lup/hooks/runtime/policy_data.py") in artifacts
    assert Path(".claude/plugins/lup/hooks/runtime/evidence.json") in artifacts


def test_codex_recipe_registers_semantic_permission_approval() -> None:
    recipe = codex_generation_recipe(Path.cwd())
    artifacts = {artifact.path: artifact for artifact in recipe.desired.artifacts}

    hook_config = artifacts[Path(".codex/plugins/lup/hooks/hooks.json")].content
    assert '"PermissionRequest"' in hook_config
    assert "hooks/scripts/policy.py" in hook_config


def test_generated_resolver_entries_only_launch_the_shared_python_core() -> None:
    harness = portable_harness()
    claude = {
        artifact.path: artifact.content
        for artifact in compile_claude(harness).artifacts
    }
    codex = {
        artifact.path: artifact.content for artifact in compile_codex(harness).artifacts
    }
    command = claude[Path(".claude/plugins/lup/commands/resolve.md")]
    skill = codex[Path(".codex/plugins/lup/skills/resolve/SKILL.md")]

    assert "uv run lup-devtools harness resolve --adapter claude" in command
    assert "--run-id" in command and "--accept" in command and "--answer" in command
    assert "Triage into concerns" not in command
    assert "Workflow(" not in command
    assert "uv run lup-devtools harness resolve --adapter codex" in skill
    assert "--run-id" in skill and "--accept" in skill and "--answer" in skill
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


def test_argument_reference_has_one_semantic_part_and_native_renderings() -> None:
    prompt = PromptDocument(parts=[ArgumentsRef()])

    assert ClaudePromptRenderer(ClaudeSkillInvocationRenderer()).render(prompt) == (
        "$ARGUMENTS\n"
    )
    assert CodexPromptRenderer(CodexSkillInvocationRenderer()).render(prompt) == (
        "the arguments supplied with this skill invocation\n"
    )


@pytest.mark.parametrize(
    ("arguments", "parts"),
    [
        ([Argument(name="target", description="Target")], [TextPart(text="body")]),
        ([], [ArgumentsRef()]),
    ],
)
def test_skill_argument_declarations_require_a_matching_reference(
    arguments: list[Argument], parts: list[PromptPart]
) -> None:
    with pytest.raises(ValueError, match="argument declarations and ArgumentsRef"):
        Skill(
            id="skill.invalid",
            name="invalid",
            description="Invalid argument declaration",
            arguments=arguments,
            prompt=PromptDocument(parts=parts),
        )


def test_typed_content_package_has_expected_module_inventory() -> None:
    content = Path("src/lup_template/devtools/harness/content")
    sources = list(content.rglob("*.py"))

    assert len(sources) == 48


def test_source_tree_contains_no_embedded_base64() -> None:
    sources = list(Path("src").rglob("*.py"))

    assert sources
    assert all("base64" not in path.read_text(encoding="utf-8") for path in sources)


def test_retired_native_catalog_paths_stay_deleted() -> None:
    harness = Path("src/lup_template/devtools/harness")

    assert not (harness / "native_catalog.py").exists()
    assert not (harness / "native_overrides.py").exists()
    assert not (harness / "importer.py").exists()


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

    def shipped_kernel(artifacts: list[Artifact]) -> list[str]:
        """Render every shipped kernel module as one comparable block."""
        return sorted(
            f"{item.path.name}\n{item.content}"
            for item in artifacts
            if "hooks/runtime/kernel/" in item.path.as_posix()
        )

    canonical = sorted(
        f"{module.name}\n{module.source}" for module in policy_kernel_modules()
    )
    assert shipped_kernel(claude.artifacts) == shipped_kernel(codex.artifacts)
    assert shipped_kernel(claude.artifacts) == canonical


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
    # codex caches an installed plugin under its manifest version segment.
    installed = home / "plugins" / "cache" / "lup-template-repository" / "lup" / "9.9.9"
    source.mkdir()
    installed.mkdir(parents=True)
    for root in (source, installed):
        manifest_dir = root / ".codex-plugin"
        manifest_dir.mkdir()
        (manifest_dir / "plugin.json").write_text(
            '{"name": "lup", "version": "9.9.9"}\n', encoding="utf-8"
        )
        (root / "plugin.txt").write_text("same\n", encoding="utf-8")
    config = PluginCacheConfig(codex_home=home, marketplace="lup-template-repository")

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


def test_generated_codex_permission_request_allows_safe_resolver() -> None:
    script = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    body = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "UV_CACHE_DIR=/tmp/lup-uv-cache uv run lup-devtools "
                "harness resolve --adapter codex"
            )
        },
    }
    result = sh.Command(str(script))(
        _in=json.dumps(body),
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    assert isinstance(result, sh.RunningCommand)
    output = CodexPermissionOutput.model_validate_json(result.stdout)
    assert result.exit_code == 0
    assert output.hook_specific_output.decision.behavior == "allow"


def test_generated_codex_permission_request_preserves_human_approval() -> None:
    script = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    body = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "# lup: escalate: required diagnostic\npython -c 1"},
    }
    result = sh.Command(str(script))(
        _in=json.dumps(body),
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    assert isinstance(result, sh.RunningCommand)
    assert result.exit_code == 0
    assert result.stdout == b""


def test_generated_codex_permission_request_denies_unapproved_code() -> None:
    script = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    body = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {"command": "python -c 1"},
    }
    result = sh.Command(str(script))(
        _in=json.dumps(body),
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    assert isinstance(result, sh.RunningCommand)
    assert result.exit_code == 2
    assert b"interpreters" in result.stderr


def test_generated_codex_hook_allows_managed_skill_scripts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    script = Path(".codex/plugins/lup/hooks/scripts/policy.py").resolve()
    helper = codex_home / "skills/.system/openai-docs/scripts/fetch-codex-manual.mjs"
    body = {"tool_name": "Bash", "tool_input": {"command": f"node {helper}"}}
    allowed = sh.Command(str(script))(
        _in=json.dumps(body),
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    assert isinstance(allowed, sh.RunningCommand)
    assert allowed.exit_code == 0

    body["tool_input"]["command"] = "node /tmp/untrusted-script.mjs"
    denied = sh.Command(str(script))(
        _in=json.dumps(body),
        _ok_code=[0, 2],
        _return_cmd=True,
    )
    assert isinstance(denied, sh.RunningCommand)
    assert denied.exit_code == 2


def test_generated_claude_hook_allows_managed_skill_scripts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "claude-profile"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    script = Path(".claude/plugins/lup/hooks/scripts/policy.py").resolve()

    def decision(command: str) -> str:
        body = {"tool_name": "Bash", "tool_input": {"command": command}}
        result = sh.Command(str(script))(_in=json.dumps(body), _return_cmd=True)
        assert isinstance(result, sh.RunningCommand)
        output = ClaudeHookOutput.model_validate_json(result.stdout)
        return output.hook_specific_output.permission_decision

    helper = config_dir / "plugins/cache/official/tool/scripts/validate.mjs"
    assert decision(f"node {helper}") == "allow"
    assert decision(f"node {config_dir}/skills/tool/scripts/report.mjs") == "allow"
    assert decision("node /tmp/untrusted-script.mjs") == "deny"
    workspace_script = Path(".claude/plugins/lup/scripts/file_suggest.sh").resolve()
    assert decision(f"sh {workspace_script}") == "deny"


def test_generated_claude_hook_executes_the_canonical_kernel() -> None:
    script = Path(".claude/plugins/lup/hooks/scripts/policy.py").resolve()
    result = sh.Command(str(script))(
        _in='{"tool_name":"Bash","tool_input":{"command":"python -c 1"}}',
        _return_cmd=True,
    )
    assert isinstance(result, sh.RunningCommand)
    output = ClaudeHookOutput.model_validate_json(result.stdout)
    assert output.hook_specific_output.permission_decision == "deny"
    assert "interpreters" in output.hook_specific_output.permission_decision_reason


def test_generated_claude_hook_maps_agent_type_to_editor_autonomy() -> None:
    script = Path(".claude/plugins/lup/hooks/scripts/policy.py").resolve()
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "packages/lup/src/lup/generated_probe.py",
            "content": "".join(f"VALUE_{index} = {index}\n" for index in range(8)),
        },
    }

    def decision(agent_type: str | None) -> str:
        body = (
            dict(payload)
            if agent_type is None
            else {**payload, "agent_type": agent_type}
        )
        result = sh.Command(str(script))(_in=json.dumps(body), _return_cmd=True)
        assert isinstance(result, sh.RunningCommand)
        output = ClaudeHookOutput.model_validate_json(result.stdout)
        return output.hook_specific_output.permission_decision

    assert decision(None) == "ask"
    assert decision("implementer") == "ask"
    assert decision("resolve-editor") == "allow"
    assert decision("lup:resolve-editor") == "allow"


def test_generated_claude_hook_asks_for_human_owned_readme_edits() -> None:
    script = Path(".claude/plugins/lup/hooks/scripts/policy.py").resolve()
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(Path("README.md").resolve()),
            "content": "# Rewritten by an agent\n",
        },
    }

    def decision(agent_type: str | None) -> ClaudeHookDecision:
        body = (
            dict(payload)
            if agent_type is None
            else {**payload, "agent_type": agent_type}
        )
        result = sh.Command(str(script))(_in=json.dumps(body), _return_cmd=True)
        assert isinstance(result, sh.RunningCommand)
        return ClaudeHookOutput.model_validate_json(result.stdout).hook_specific_output

    assert decision(None).permission_decision == "ask"
    autonomous = decision("resolve-editor")
    assert autonomous.permission_decision == "ask"
    assert "human-authored" in autonomous.permission_decision_reason


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


def test_reconciliation_proposal_persists_reviewable_patch_and_metadata(
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

    record = ReconciliationProposalWriter().write(tmp_path, patch)
    directory = tmp_path / ".lup" / "reconcile" / record.proposal_id

    assert (directory / "source.patch").read_text(encoding="utf-8") == patch
    assert (directory / "metadata.json").read_text(encoding="utf-8").endswith("\n")


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


def test_annotated_ownership_manifest_raises_a_typed_recovery_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".lup-ownership.json"
    assert load_manifest(path) is None
    manifest = build_manifest(
        portable_harness(),
        ArtifactTree(artifacts=[]),
        generator_version="test",
        target_requirements=[],
    )
    save_manifest(path, manifest)
    assert load_manifest(path) == manifest

    with path.open("a", encoding="utf-8") as handle:
        handle.write("# a trailing annotation\n")

    with pytest.raises(OwnershipManifestError, match="repair or remove"):
        load_manifest(path)


def test_proven_obsolete_deletion_is_proposed_and_executed(tmp_path: Path) -> None:
    obsolete = tmp_path / "obsolete.txt"
    obsolete.write_text("stale output\n", encoding="utf-8")
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("obsolete.txt"),
                content="stale output\n",
                category="generated",
                sha256=content_digest("stale output\n"),
            )
        ],
    )

    proposal = DeterministicReconciler().propose(current, ArtifactTree(artifacts=[]))
    result = AtomicMaterializer().apply(proposal)

    assert [delete.path for delete in proposal.deletes] == [Path("obsolete.txt")]
    assert result.removed == [Path("obsolete.txt")]
    assert not obsolete.exists()


def test_deletion_prunes_the_directories_it_empties(tmp_path: Path) -> None:
    gone = tmp_path / "skills" / "gone" / "SKILL.md"
    gone.parent.mkdir(parents=True)
    gone.write_text("stale skill\n", encoding="utf-8")
    kept = tmp_path / "skills" / "kept" / "SKILL.md"
    kept.parent.mkdir(parents=True)
    kept.write_text("live skill\n", encoding="utf-8")
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("skills/gone/SKILL.md"),
                content="stale skill\n",
                category="generated",
                sha256=content_digest("stale skill\n"),
            )
        ],
    )

    AtomicMaterializer().apply(
        DeterministicReconciler().propose(current, ArtifactTree(artifacts=[]))
    )

    assert not gone.parent.exists()
    assert kept.exists()
    assert tmp_path.exists()


def test_deletion_with_changed_ownership_proof_is_refused(tmp_path: Path) -> None:
    obsolete = tmp_path / "obsolete.txt"
    obsolete.write_text("stale output\n", encoding="utf-8")
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("obsolete.txt"),
                content="stale output\n",
                category="generated",
                sha256=content_digest("stale output\n"),
            )
        ],
    )
    proposal = DeterministicReconciler().propose(current, ArtifactTree(artifacts=[]))
    obsolete.write_text("user edited after the proposal\n", encoding="utf-8")

    with pytest.raises(MaterializationConflictError, match="ownership proof changed"):
        AtomicMaterializer().apply(proposal)
    assert obsolete.exists()


def test_materialization_rejects_stale_executable_mode(tmp_path: Path) -> None:
    path = tmp_path / "hook.py"
    path.write_text("pass\n", encoding="utf-8")
    path.chmod(0o644)
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("hook.py"),
                content="pass\n",
                category="generated",
                sha256=content_digest("pass\n"),
                executable=False,
            )
        ],
    )
    desired = ArtifactTree(
        artifacts=[
            Artifact(path=Path("hook.py"), content="updated\n", semantic_id="hook")
        ]
    )
    proposal = DeterministicReconciler().propose(current, desired)
    path.chmod(0o755)  # mode drift between proposal and apply

    with pytest.raises(MaterializationConflictError, match="stale executable mode"):
        AtomicMaterializer().apply(proposal)
    assert path.read_text(encoding="utf-8") == "pass\n"


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        (
            "diff --git a/x.py b/x.py\ndiff --git a/y.py b/y.py\n--- a/y.py\n",
            "missing its old-file header",
        ),
        ("diff --git a/x.py\n--- a/x.py\n", "malformed git source-patch header"),
        ("diff --git x/a.py y/a.py\n--- x/a.py\n", "repository-relative"),
        ("diff --git a/x.py b/x.py\n--- a/other.py\n", "does not match its diff"),
        ("diff --git a/x.py b/x.py\n", "missing its old-file header"),
        ("just prose\n", "no git file entries"),
    ],
    ids=[
        "header-without-old-file",
        "truncated-header",
        "foreign-prefixes",
        "mismatched-old-file",
        "trailing-header",
        "no-entries",
    ],
)
def test_malformed_source_patches_are_rejected(
    tmp_path: Path, patch: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        source_patch_base_digest(tmp_path, patch)


def test_source_digest_rejects_symlinked_preimage_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "file.py").write_text("secret\n", encoding="utf-8")
    (root / "link").symlink_to(outside, target_is_directory=True)
    patch = (
        "diff --git a/link/file.py b/link/file.py\n"
        "--- a/link/file.py\n"
        "+++ b/link/file.py\n"
    )

    with pytest.raises(ValueError, match="escapes the repository"):
        source_patch_base_digest(root, patch)


def test_declared_sensitive_paths_are_classified_without_content(
    tmp_path: Path,
) -> None:
    path = Path("secrets.env")
    (tmp_path / path).write_text("API_KEY=hunter2\n", encoding="utf-8")

    tree = FilesystemCurrentTreeReader(None, sensitive_local_only=[path]).read(tmp_path)

    assert [(item.category, item.content) for item in tree.artifacts] == [
        ("sensitive_local_only", "")
    ]
    assert tree.artifacts[0].sha256  # identity still proven for reconciliation


def test_missing_root_reads_as_an_empty_tree(tmp_path: Path) -> None:
    tree = FilesystemCurrentTreeReader(None).read(tmp_path / "ghost")

    assert tree.artifacts == []


def test_symlink_escaping_the_root_is_sensitive_and_unread(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("credential\n", encoding="utf-8")
    (root / "escape.txt").symlink_to(secret)

    tree = FilesystemCurrentTreeReader(None).read(root)

    assert [(item.category, item.content, item.sha256) for item in tree.artifacts] == [
        ("sensitive_local_only", "", "")
    ]


def test_binary_local_only_file_cannot_claim_local_preservation(
    tmp_path: Path,
) -> None:
    path = Path("local.bin")
    (tmp_path / path).write_bytes(b"\xff\xfe")

    tree = FilesystemCurrentTreeReader(None, local_only=[path]).read(tmp_path)

    assert tree.artifacts[0].category == "unknown_conflict"
    assert tree.artifacts[0].content == ""


def test_binary_owned_file_requires_explicit_reconciliation(tmp_path: Path) -> None:
    path = Path("owned.md")
    manifest = build_manifest(
        portable_harness(),
        ArtifactTree(
            artifacts=[Artifact(path=path, content="text\n", semantic_id="owned")]
        ),
        generator_version="test",
        target_requirements=[],
    )
    (tmp_path / path).write_bytes(b"\xff\xfe")

    tree = FilesystemCurrentTreeReader(manifest, managed_paths=[path]).read(tmp_path)

    assert tree.artifacts[0].category == "unknown_conflict"
    assert tree.artifacts[0].content == ""


def test_exact_content_adoption_still_corrects_executable_drift(
    tmp_path: Path,
) -> None:
    content = "#!/bin/sh\n"
    current = CurrentTree(
        root=tmp_path,
        artifacts=[
            CurrentArtifact(
                path=Path("hook.sh"),
                content=content,
                category="unknown_conflict",
                sha256=content_digest(content),
                executable=False,
            )
        ],
    )
    desired = ArtifactTree(
        artifacts=[
            Artifact(
                path=Path("hook.sh"),
                content=content,
                semantic_id="hook",
                executable=True,
            )
        ]
    )

    proposal = DeterministicReconciler().propose(current, desired)

    assert proposal.conflicts == []
    assert [
        (write.previous_sha256, write.previous_executable) for write in proposal.writes
    ] == [(content_digest(content), False)]
    assert proposal.writes[0].artifact.executable


def test_proposal_rewrite_is_idempotent_but_tampering_refuses(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("old\n", encoding="utf-8")
    patch = (
        "diff --git a/source.py b/source.py\n"
        "--- a/source.py\n"
        "+++ b/source.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new"  # no trailing newline: the writer must normalize it
    )

    writer = ReconciliationProposalWriter()
    record = writer.write(tmp_path, patch)
    assert writer.write(tmp_path, patch) == record  # identical re-write is a no-op

    patch_path = tmp_path / ".lup" / "reconcile" / record.proposal_id / "source.patch"
    assert patch_path.read_text(encoding="utf-8").endswith("\n")
    patch_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="collision"):
        writer.write(tmp_path, patch)


def test_project_settings_derive_sandbox_from_hook_declaration() -> None:
    hooks = portable_harness().plugins[0].hooks
    assert hooks is not None
    settings = project_settings(hooks)
    sandbox = settings["sandbox"]
    assert isinstance(sandbox, dict)
    filesystem = sandbox["filesystem"]
    network = sandbox["network"]
    assert isinstance(filesystem, dict) and isinstance(network, dict)
    assert filesystem["denyWrite"] == ["README.md"]
    domains = network["allowedDomains"]
    assert isinstance(domains, list)
    assert "code.claude.com" in domains
    assert "github.com" in domains
    assert "sandbox" not in project_settings(None)


def test_codex_sandbox_arguments_establish_the_envelope() -> None:
    environment: EnvVars = {}
    arguments = codex_sandbox_arguments(environment, ["--model", "gpt-5.2"])
    assert arguments[:2] == ["--sandbox", "workspace-write"]
    assert environment["LUP_SANDBOX_ACTIVE"] == "1"


def test_codex_sandbox_widens_the_root_to_sibling_worktrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex roots writes at the launch cwd; the prescribed worktree is outside."""
    monkeypatch.setattr(launch, "get_tree_dir", lambda: tmp_path)
    environment: EnvVars = {}
    arguments = codex_sandbox_arguments(environment, [])
    roots = arguments[arguments.index("-c") + 1]

    assert roots.startswith("sandbox_workspace_write.writable_roots=")
    assert str(tmp_path) in roots


def test_codex_sandbox_omits_the_root_outside_a_tree_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain clone has no tree/ to widen to, so the envelope stands alone."""

    def no_tree() -> Path:
        raise typer.Exit(1)

    monkeypatch.setattr(launch, "get_tree_dir", no_tree)
    environment: EnvVars = {}

    assert codex_sandbox_arguments(environment, []) == [
        "--sandbox",
        "workspace-write",
    ]


def test_codex_sandbox_arguments_defer_to_a_caller_envelope() -> None:
    environment: EnvVars = {}
    caller_forms = [
        ["--sandbox", "danger-full-access"],
        ["--sandbox=read-only"],
        ["-s", "read-only"],
        ["--yolo"],
        ["--full-auto"],
        ["--dangerously-bypass-approvals-and-sandbox"],
    ]
    for extra_args in caller_forms:
        assert codex_sandbox_arguments(environment, extra_args) == []
    assert "LUP_SANDBOX_ACTIVE" not in environment
