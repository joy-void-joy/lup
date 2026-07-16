"""Canonical declaration for the resolve skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.resolve",
    name="resolve",
    description="Resolve inline feedback through isolated work",
    prompt=models.PromptDocument(
        parts=[
            models.ResolverEntry(),
        ]
    ),
)
