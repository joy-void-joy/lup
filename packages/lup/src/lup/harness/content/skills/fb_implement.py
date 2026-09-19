"""Canonical declaration for the fb-implement skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.fb-implement",
    name="fb-implement",
    description="Implement prioritized changes from feedback loop analysis",
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv run lup:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "WebSearch",
        "WebFetch",
    ],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "approval": models.RequestApproval(
                        action="implementing any of the changes",
                        reason="the list decides what the next session's work will be",
                    ),
                    "ask": models.AskUser(question="which approach to build, if any"),
                    "bump_skill": models.SkillInvocation(plugin="lup", skill="bump"),
                },
            ),
        ],
    ),
)
