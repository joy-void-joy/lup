"""Canonical declaration for the merge skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.merge",
    name="merge",
    description="Merge a branch or resolve existing merge conflicts",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(git:*, uv run lup-devtools:*, .venv/bin/lup-devtools:*, lup-devtools:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="[target]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "merge_skill": models.SkillInvocation(plugin="lup", skill="merge"),
                    "arguments": models.ArgumentsRef(),
                    "commit_skill": models.SkillInvocation(
                        plugin="lup", skill="commit"
                    ),
                    "ask": models.AskUser(
                        question="whether to run a standard merge and resolve in place, or apply the source branch manually file by file"
                    ),
                    "land_skill": models.SkillInvocation(plugin="lup", skill="land"),
                },
            ),
        ],
    ),
)
