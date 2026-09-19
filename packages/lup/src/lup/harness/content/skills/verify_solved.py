"""Canonical declaration for the verify-solved skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.verify-solved",
    name="verify-solved",
    description="Check every claimed-resolved note and stale open issue against what it actually asked",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(module=__name__),
        ],
    ),
)
