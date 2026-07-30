"""Named native harness composition roots over canonical declarations."""

from lup.adapters.claude.harness import (
    ClaudeAgentRenderer,
    ClaudeGuidanceRenderer,
    ClaudeHookRenderer,
    ClaudePluginManifestRenderer,
    ClaudeSkillRenderer,
    ClaudeSpellings,
)
from lup.adapters.codex.harness import (
    CodexAgentRenderer,
    CodexGuidanceRenderer,
    CodexHookRenderer,
    CodexPluginManifestRenderer,
    CodexSkillRenderer,
    CodexSpellings,
)
from lup.codescan.portable import prose_breaches
from lup.harness.contracts import NativeSpellings
from lup.harness.generation import ArtifactValidationError
from lup.harness.prompts import SpelledPromptRenderer
from lup.harness.models import (
    GUIDANCE_CHARACTER_BUDGET,
    Artifact,
    ArtifactTree,
    Harness,
    document_prose,
)
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


def prompt_renderer(own: NativeSpellings) -> SpelledPromptRenderer:
    """Compose the one renderer around the vocabulary of one runtime.

    Prose that teaches every tree names the runtimes in this order, so the
    ordering is a single composition decision rather than a claim any one
    adapter makes about the others.
    """
    return SpelledPromptRenderer(own=own, every=[ClaudeSpellings(), CodexSpellings()])


def claude_prompt_renderer() -> SpelledPromptRenderer:
    """Render prompts in Claude's vocabulary."""
    return prompt_renderer(ClaudeSpellings())


def codex_prompt_renderer() -> SpelledPromptRenderer:
    """Render prompts in Codex's vocabulary."""
    return prompt_renderer(CodexSpellings())


def reject_oversized_guidance(tree: ArtifactTree) -> None:
    """Hold the always-loaded document to its budget as a session sees it.

    The declaration-time lower bound in ``Harness`` cannot know what the parts
    render to, and the gap grows with every part that replaces literal prose.
    """
    for artifact in tree.artifacts:
        used = len(artifact.content)
        if artifact.semantic_id != "harness.guidance" or used <= (
            GUIDANCE_CHARACTER_BUDGET
        ):
            continue
        raise ValueError(
            f"rendered guidance {artifact.path.as_posix()} is {used} characters, "
            f"over the {GUIDANCE_CHARACTER_BUDGET} budget by "
            f"{used - GUIDANCE_CHARACTER_BUDGET}. Move a section to a generated "
            "document under docs/ and leave a file-path pointer, the way "
            "Self-Improvement Loop and Permission Hooks were split."
        )


def reject_native_prose(source: Harness) -> None:
    """Keep every native spelling inside the adapter that owns it.

    Composition is the only place that sees the assembled text, so a
    description built elsewhere and folded into a prompt is judged here too.
    """
    breaches = prose_breaches(source, [ClaudeSpellings(), CodexSpellings()])
    if breaches:
        named = ", ".join(
            f"{breach.declaration_id} names {breach.spelling!r}"
            for breach in breaches[:8]
        )
        raise ValueError(
            "prose every tree renders must name no platform; a typed part "
            f"spells these for each runtime instead: {named}"
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
        prefix in text
        for prompt in prompts
        for text in document_prose(prompt)
        for prefix in prefixes
    ):
        raise ValueError(  # lup: I feel like this is failing the "parse, don't validate" principle
            "provider invocation syntax must be represented by SkillInvocation"
        )


def compile_claude(source: Harness) -> ArtifactTree:
    """Compile canonical declarations directly to Claude-owned artifacts."""
    reject_rendered_invocations(source, "/")
    reject_native_prose(source)
    spellings = ClaudeSpellings()
    prompts = prompt_renderer(spellings)
    manifest_renderer = ClaudePluginManifestRenderer()
    guidance_renderer = ClaudeGuidanceRenderer(prompts)
    artifacts: list[Artifact] = []  # lup: ignore[empty-collection]
    for plugin in source.plugins:
        skill_renderer = ClaudeSkillRenderer(prompts, plugin.name)
        agent_renderer = ClaudeAgentRenderer(prompts, plugin.name, spellings)
        for declaration in plugin.skills:
            artifacts.extend(skill_renderer.render(declaration).artifacts)
        for declaration in plugin.agents:
            artifacts.extend(agent_renderer.render(declaration).artifacts)
        artifacts.extend(manifest_renderer.render(plugin).artifacts)
        if plugin.hooks is not None:
            artifacts.extend(
                ClaudeHookRenderer(plugin.name, source.resolver.worker_identity)
                .render(plugin.hooks)
                .artifacts
            )
    guidance = guidance_renderer.render(source)
    reject_oversized_guidance(guidance)
    artifacts.extend(guidance.artifacts)
    return validated_tree(artifacts)


def compile_codex(source: Harness) -> ArtifactTree:
    """Compile canonical declarations directly to Codex-owned artifacts."""
    reject_rendered_invocations(source, "$")
    reject_native_prose(source)
    spellings = CodexSpellings()
    prompts = prompt_renderer(spellings)
    manifest_renderer = CodexPluginManifestRenderer()
    guidance_renderer = CodexGuidanceRenderer(prompts)
    artifacts: list[Artifact] = []  # lup: ignore[empty-collection]
    for plugin in source.plugins:
        skill_renderer = CodexSkillRenderer(prompts, plugin.name)
        agent_renderer = CodexAgentRenderer(prompts, spellings)
        for declaration in plugin.skills:
            artifacts.extend(skill_renderer.render(declaration).artifacts)
        for declaration in plugin.agents:
            artifacts.extend(agent_renderer.render(declaration).artifacts)
        artifacts.extend(manifest_renderer.render(plugin).artifacts)
        if plugin.hooks is not None:
            artifacts.extend(
                CodexHookRenderer(plugin.name, source.resolver.worker_identity)
                .render(plugin.hooks)
                .artifacts
            )
    guidance = guidance_renderer.render(source)
    reject_oversized_guidance(guidance)
    artifacts.extend(guidance.artifacts)
    return validated_tree(artifacts)
