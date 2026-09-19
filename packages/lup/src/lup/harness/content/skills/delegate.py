"""Canonical declaration for the delegate skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.delegate",
    name="delegate",
    description="Hand one piece of work to another session, or park it for whoever picks it up",
    tools=["Bash(uv run lup-devtools:*)", "Read", "Grep"],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(module=__name__),
        ],
    ),
)
