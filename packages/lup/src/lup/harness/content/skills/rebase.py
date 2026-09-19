"""Canonical declaration for the rebase skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.rebase",
    name="rebase",
    description="Clean up commit history on the feature branch and open/update a PR",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(uv run lup-devtools:*, git:*)",
        "Read",
        "Glob",
        "Grep",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="[target-branch]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "ask": models.AskUser(question="which branch is the true base"),
                    "arguments": models.ArgumentsRef(),
                    "commit_skill": models.SkillInvocation(
                        plugin="lup", skill="commit"
                    ),
                    "merge_skill": models.SkillInvocation(plugin="lup", skill="merge"),
                    "ask_2": models.AskUser(
                        question="push the base, or rebuild this branch onto the remote base"
                    ),
                    "personal_settings_path": models.NativePath(
                        location="personal_settings"
                    ),
                    "project_settings_path": models.NativePath(
                        location="project_settings"
                    ),
                    "hooks_skill": models.SkillInvocation(plugin="lup", skill="hooks"),
                    "watch": models.WatchOutput(
                        command="uv run lup-devtools dev check"
                    ),
                },
            ),
        ],
    ),
)
