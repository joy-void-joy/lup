"""Canonical declaration for the implementer skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.implementer",
    name="implementer",
    description="Implement one resolver concern inside its leased worktree",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(module=__name__),
        ],
    ),
)
