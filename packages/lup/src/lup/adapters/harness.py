"""Named native harness composition roots over canonical declarations."""

from lup.adapters.claude.harness import (
    ClaudeAgentRenderer,
    ClaudeGuidanceRenderer,
    ClaudeHookRenderer,
    ClaudeNativePathSpelling,
    ClaudePluginManifestRenderer,
    ClaudePromptRenderer,
    ClaudeSkillInvocationRenderer,
    ClaudeSkillRenderer,
)
from lup.adapters.codex.harness import (
    CodexAgentRenderer,
    CodexGuidanceRenderer,
    CodexHookRenderer,
    CodexNativePathSpelling,
    CodexPluginManifestRenderer,
    CodexPromptRenderer,
    CodexSkillInvocationRenderer,
    CodexSkillRenderer,
)
from lup.harness.contracts import NativePathSpelling
from lup.harness.generation import ArtifactValidationError, NativePaths
from lup.harness.models import Artifact, ArtifactTree, Harness, TextPart
from lup.harness.validation import DeterministicTreeValidator


def validated_tree(artifacts: list[Artifact]) -> ArtifactTree:
    """Sort a complete output tree and reject any deterministic issue."""
    tree = ArtifactTree(
        artifacts=sorted(artifacts, key=lambda item: item.path.as_posix())
    )
    result = DeterministicTreeValidator().validate(tree)
    if not result.valid:
        raise ArtifactValidationError(
            "; ".join(
                f"{issue.semantic_id}: {issue.message}" for issue in result.issues
            )
        )
    return tree


def native_paths(own: NativePathSpelling) -> NativePaths:
    """Order every runtime's spellings around the one that is rendering.

    Prose that teaches every tree names them in this order, so the ordering is
    one composition decision rather than a claim any single adapter makes.
    """
    return NativePaths(
        own=own, every=[ClaudeNativePathSpelling(), CodexNativePathSpelling()]
    )


def claude_prompt_renderer() -> ClaudePromptRenderer:
    """Compose the Claude prompt renderer with the spellings it must reach."""
    return ClaudePromptRenderer(
        ClaudeSkillInvocationRenderer(), native_paths(ClaudeNativePathSpelling())
    )


def codex_prompt_renderer() -> CodexPromptRenderer:
    """Compose the Codex prompt renderer with the spellings it must reach."""
    return CodexPromptRenderer(
        CodexSkillInvocationRenderer(), native_paths(CodexNativePathSpelling())
    )


def reject_rendered_invocations(source: Harness, sigil: str) -> None:
    """Keep native invocation spelling inside typed adapter rendering only."""
    prefixes = tuple(
        f"{sigil}{plugin.name}:" for plugin in source.plugins
    )  # lup: tuple() is an antipattern, please run a full antipattern sweep
    prompts = [
        source.guidance,
        *[
            declaration.prompt
            for plugin in source.plugins
            for declaration in [*plugin.skills, *plugin.agents]
        ],
    ]
    if any(
        prefix in part.text
        for prompt in prompts
        for part in prompt.parts
        if isinstance(part, TextPart)
        for prefix in prefixes
    ):
        raise ValueError(  # lup: I feel like this is failing the "parse, don't validate" principle
            "provider invocation syntax must be represented by SkillInvocation"
        )


def compile_claude(source: Harness) -> ArtifactTree:
    """Compile canonical declarations directly to Claude-owned artifacts."""
    reject_rendered_invocations(source, "/")
    prompts = claude_prompt_renderer()
    manifest_renderer = ClaudePluginManifestRenderer()
    guidance_renderer = ClaudeGuidanceRenderer(prompts)
    artifacts: list[Artifact] = []  # lup: ignore[empty-collection]
    for plugin in source.plugins:
        skill_renderer = ClaudeSkillRenderer(prompts, plugin.name)
        agent_renderer = ClaudeAgentRenderer(prompts, plugin.name)
        for declaration in plugin.skills:
            artifacts.extend(skill_renderer.render(declaration).artifacts)
        for declaration in plugin.agents:
            artifacts.extend(agent_renderer.render(declaration).artifacts)
        artifacts.extend(manifest_renderer.render(plugin).artifacts)
        if plugin.hooks is not None:
            artifacts.extend(
                ClaudeHookRenderer(plugin.name).render(plugin.hooks).artifacts
            )
    artifacts.extend(guidance_renderer.render(source).artifacts)
    return validated_tree(artifacts)


def compile_codex(source: Harness) -> ArtifactTree:
    """Compile canonical declarations directly to Codex-owned artifacts."""
    reject_rendered_invocations(source, "$")
    prompts = codex_prompt_renderer()
    manifest_renderer = CodexPluginManifestRenderer()
    guidance_renderer = CodexGuidanceRenderer(prompts)
    artifacts: list[Artifact] = []  # lup: ignore[empty-collection]
    for plugin in source.plugins:
        skill_renderer = CodexSkillRenderer(prompts, plugin.name)
        agent_renderer = CodexAgentRenderer(prompts)
        for declaration in plugin.skills:
            artifacts.extend(skill_renderer.render(declaration).artifacts)
        for declaration in plugin.agents:
            artifacts.extend(agent_renderer.render(declaration).artifacts)
        artifacts.extend(manifest_renderer.render(plugin).artifacts)
        if plugin.hooks is not None:
            artifacts.extend(
                CodexHookRenderer(plugin.name).render(plugin.hooks).artifacts
            )
    artifacts.extend(guidance_renderer.render(source).artifacts)
    return validated_tree(artifacts)
