"""Canonical declaration for the land skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.land",
    name="land",
    description="Land every branch that has not reached the integration branch, and clear the ones that have",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(uv run lup-devtools:*, git:*, findmnt:*, grep:*)",
        "AskUserQuestion",
        "EnterWorktree",
        "Skill(lup:commit)",
        "Skill(lup:rebase)",
        "Skill(lup:merge)",
    ],
    argument_hint="[branch-name ...]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "arguments": models.ArgumentsRef(),
                    "commit_skill": models.SkillInvocation(
                        plugin="lup", skill="commit"
                    ),
                    "approval": models.RequestApproval(
                        action="carrying out the actions those dispositions imply",
                        reason="the branches may hold work the user has not looked at",
                    ),
                    "relocate": models.RelocateSession(
                        path="the survey's worktree field"
                    ),
                    "rebase_skill": models.SkillInvocation(
                        plugin="lup", skill="rebase"
                    ),
                    "merge_skill": models.SkillInvocation(plugin="lup", skill="merge"),
                    "approval_2": models.RequestApproval(
                        action="deleting a branch, merging a PR, or pushing to a remote",
                        reason="a LAND branch carries no PR expressing intent, and the order open PRs merge in is the user's to settle, so the intent has to come from them",
                    ),
                },
            ),
        ],
    ),
)
