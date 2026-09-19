"""Canonical declaration for the release skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.release",
    name="release",
    description="Cut a release: settle the level, close the changelog, tag it",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(uv run lup-devtools:*, git:*, gh:*)",
        "Read",
        "Edit",
        "AskUserQuestion",
    ],
    argument_hint="[patch|minor|major]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "arguments": models.ArgumentsRef(),
                    "ask": models.AskUser(question="which level this release is"),
                },
            ),
        ],
    ),
)
