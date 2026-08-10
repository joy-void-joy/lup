"""Canonical declaration for the resolve-reviewer skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.resolve-reviewer",
    name="resolve-reviewer",
    description="Review one resolver concern against its acceptance criteria",
    prompt=models.PromptDocument(
        parts=[
            models.TextPart(
                text="Independently review the supplied concern commit against every persisted acceptance criterion. Inspect the complete diff, reject omissions and scope leaks, and return the typed review report without editing. Where a criterion asks for a `# lup: solved: <text>` claim, the claim standing in the diff is that criterion met — the orchestrator strips a concern's open feedback before the worker starts, so the marker is a record of the answer and not feedback re-opened."
            ),
        ]
    ),
)
