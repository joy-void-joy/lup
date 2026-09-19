"""Canonical declaration for the update skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.update",
    name="update",
    description="Move every carrier of lup to one upstream commit, and resolve what it leaves",
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv sync:*, uv lock:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="[commit]",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "commit_skill": models.SkillInvocation(
                        plugin="lup", skill="commit"
                    ),
                    "merge_skill": models.SkillInvocation(plugin="lup", skill="merge"),
                    "watch": models.WatchOutput(
                        command="uv run lup-devtools dev check"
                    ),
                    "import_skill": models.SkillInvocation(
                        plugin="lup", skill="import"
                    ),
                    "upstream_skill": models.SkillInvocation(
                        plugin="lup", skill="upstream"
                    ),
                },
            ),
        ],
    ),
)
