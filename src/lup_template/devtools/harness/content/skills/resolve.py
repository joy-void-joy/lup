"""Canonical declaration for the resolve skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.resolve",
    name="resolve",
    description="Resolve inline feedback through isolated work",
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text="""Deferred notes — `# lup: defer[<wake condition>]: <text>` — are parked work, not open feedback, and the resolver entry excludes them from its inventory, so an editor can never be assigned one. Triage them before launching the resolver: read each note's wake condition against the current state of the repository, and when one reads as met, propose waking it to the user. Waking is an explicit edit that removes the `defer[...]` head so the note re-enters open feedback on the next run; an unmet condition carries forward untouched, never re-litigated.

"""
            ),
            models.ResolverEntry(),
        ]
    ),
)
