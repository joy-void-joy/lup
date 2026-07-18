"""Canonical declaration for the resolve skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.resolve",
    name="resolve",
    description="Resolve inline feedback through isolated work",
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text="""Deferred notes — `# lup: defer[<wake condition>]: <text>` — are parked work, not open feedback. Triage them instead of re-litigating them: read each note's wake condition against the current state of the repository. When a condition reads as met, plan a dedicated concern that proposes waking the note and leave the wake decision to the user; otherwise carry the note forward untouched. An editor strips a deferred note only when its assigned concern explicitly wakes it.

"""
            ),
            models.ResolverEntry(),
        ]
    ),
)
