"""Canonical declaration for the implementer skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.implementer",
    name="implementer",
    description="Implement one resolver concern inside its leased worktree",
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text="Implement exactly the supplied resolver assignment inside its leased worktree. Do not create branches or commits. Report every changed path, any work beyond the declared starting points, verification performed, and material questions through the resolver's typed report."
            ),
        ]
    ),
)
