"""Canonical declaration for analyzing a retained AI conversation."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.analyze",
    name="analyze",
    description="Retain a ChatGPT or Claude conversation and answer from its files",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(uv run lup-devtools:*, git log:*, git show:*)",
        "Read",
        "Glob",
        "Grep",
        "AskUserQuestion",
    ],
    argument_hint="<conversation-url> [-- <question>]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "arguments": models.ArgumentsRef(),
                    "ask": models.AskUser(
                        question="which ChatGPT or Claude conversation URL to analyze"
                    ),
                },
            ),
        ],
    ),
)
