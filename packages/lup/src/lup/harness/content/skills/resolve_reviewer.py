"""Canonical declaration for the resolve-reviewer skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.resolve-reviewer",
    name="resolve-reviewer",
    description="Review one resolver concern against its acceptance criteria",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(module=__name__),
        ],
    ),
)
