"""Canonical declaration for the bump skill."""

import lup.harness.models as models
from lup.harness.content.skills.committing import with_commit_skill

SKILL = models.Skill(
    id="skill.bump",
    name="bump",
    description="Review changes since last bump and bump agent version",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(uv run lup-devtools:*)",
        "Read",
        "Grep",
        "Glob",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="[patch|minor|major]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "arguments": models.ArgumentsRef(),
                    "commit_with": with_commit_skill(),
                    "guidance_file_path": models.NativePath(location="guidance_file"),
                    "ask": models.AskUser(question="which bump level to apply"),
                },
            ),
        ],
    ),
)
