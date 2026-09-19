"""Canonical declaration for the handoff skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.handoff",
    name="handoff",
    description="Hand a body of work to another session, with what it takes to resume it",
    tools=["Bash(uv run lup-devtools:*)", "Read", "Grep"],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "delegate_skill": models.SkillInvocation(
                        plugin="lup", skill="delegate"
                    )
                },
            ),
        ],
    ),
)
