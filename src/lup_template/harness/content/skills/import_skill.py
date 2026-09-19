"""Canonical declaration for the import skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.import",
    name="import",
    description="Import a feature or pattern from a tracked project or local Git source",
    arguments=[
        models.Argument(
            name="arguments",
            description="Source selector, optional revision range, and import scope",
            required=False,
        ),
    ],
    tools=[
        "Bash(git:*, uv run lup-devtools:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="<project|path|ref> [BASE..SOURCE] <scope description>",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "update_skill": models.SkillInvocation(
                        plugin="lup", skill="update"
                    ),
                    "arguments": models.ArgumentsRef(),
                    "import_skill": models.SkillInvocation(
                        plugin="lup", skill="import"
                    ),
                    "ask": models.AskUser(
                        question="what feature or scope to import from that source"
                    ),
                    "commit_skill": models.SkillInvocation(
                        plugin="lup", skill="commit"
                    ),
                    "approval": models.RequestApproval(
                        action="making any change to this repository",
                        reason="the pattern comes from another project and has to be adapted, not copied",
                    ),
                    "watch": models.WatchOutput(
                        command="uv run lup-devtools dev check"
                    ),
                },
            ),
        ],
    ),
)
