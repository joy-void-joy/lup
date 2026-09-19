"""Canonical declaration for the close skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.close",
    name="close",
    description="Check PR review status, merge if approved, and clean up branches",
    tools=["Bash(uv run lup-devtools:*)", "AskUserQuestion", "Skill(lup:commit)"],
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "commit_skill": models.SkillInvocation(
                        plugin="lup", skill="commit"
                    ),
                    "rebase_skill": models.SkillInvocation(
                        plugin="lup", skill="rebase"
                    ),
                    "approval": models.RequestApproval(
                        action="merging the pull request",
                        reason="the merge is irreversible and closes the review it opened",
                    ),
                },
            ),
        ],
    ),
)
