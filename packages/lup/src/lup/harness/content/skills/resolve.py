"""Canonical declaration for the resolve skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.resolve",
    name="resolve",
    description="Resolve inline feedback through isolated work",
    arguments=[
        models.Argument(
            name="concerns",
            description="What to resolve, in the human's own words",
            required=False,
        ),
    ],
    argument_hint="[what needs resolving, in your own words]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "arguments": models.ArgumentsRef(),
                    "resolver": models.ResolverEntry(),
                    "watch": models.WatchOutput(
                        command="uv run lup-devtools resolve status --run-id <id> --watch"
                    ),
                },
            ),
        ],
    ),
)
