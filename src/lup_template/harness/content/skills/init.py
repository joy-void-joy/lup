"""Canonical declaration for the init skill."""

import lup.harness.models as models
import lup_template.harness.content.provenance as provenance

SPELLING = provenance.Provenance(
    library_git="git",
    project_devtools="uv run lup-devtools",
    library_checkout="<lup-checkout>",
)
"""One checkout, unqualified: this skill turns the library's clone into the project."""

SKILL = models.Skill(
    id="skill.init",
    name="init",
    description="Initialize the self-improvement loop for a specific domain",
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv sync:*, uv run pyright:*, uv run ruff:*, uv run pytest:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
    ],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(module=__name__),
            *provenance.branch_probes(SPELLING),
            models.Passage(
                module=__name__,
                name="init-2",
                values={
                    "brainstorm_skill": models.SkillInvocation(
                        plugin="lup", skill="brainstorm"
                    ),
                    "ask": models.AskUser(
                        question="each identity answer that decides what gets generated, with the reading you would pick offered first"
                    ),
                    "ask_2": models.AskUser(
                        question="which modules this domain takes and which it declines, one option per module the roster offers"
                    ),
                    "marketplace_path": models.NativePath(
                        location="marketplace", scope="every_tree"
                    ),
                    "skill_pattern": models.SkillPattern(plugin="lup", placeholder="*"),
                },
            ),
            *provenance.acquisition(SPELLING),
            models.Passage(
                module=__name__,
                name="init-3",
                values={
                    "guidance_file_path": models.NativePath(
                        location="guidance_file", scope="every_tree"
                    ),
                    "guidance_template_path": models.PluginPath(
                        plugin="lup", location="guidance_template", scope="every_tree"
                    ),
                },
            ),
            *provenance.sync_baseline(SPELLING),
            models.Passage(
                module=__name__,
                name="init-4",
                values={
                    "ask": models.AskUser(
                        question="which rule families this domain keeps, with retiring the anti-pattern family altogether as one answer"
                    ),
                    "ask_2": models.AskUser(
                        question="which files the human author owns, starting from whether README.md stays locked"
                    ),
                    "ask_3": models.AskUser(
                        question="whether any root this domain adds needs a path role, and which"
                    ),
                    "ask_4": models.AskUser(
                        question="whether this domain declares an acceptance guard over its test roots"
                    ),
                    "guidance_file_path": models.NativePath(
                        location="guidance_file", scope="every_tree"
                    ),
                    "ask_5": models.AskUser(
                        question="which external services the agent uses, and for each whether it authenticates by OAuth flow, API key, or a credentials file"
                    ),
                    "watch": models.WatchOutput(
                        command="uv run lup-devtools dev check"
                    ),
                    "feedback_loop_skill": models.SkillInvocation(
                        plugin="lup", skill="feedback-loop"
                    ),
                },
            ),
        ],
    ),
)
