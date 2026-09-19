"""Canonical declaration for the upstream skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.upstream",
    name="upstream",
    description="Fix a defect in lup itself, in a worktree of lup, and pin it until it lands",
    arguments=[
        models.Argument(
            name="arguments",
            description="What is wrong in lup, and what it cost here",
            required=False,
        ),
    ],
    tools=[
        "Bash(git:*, uv run lup-devtools:*, uv run --directory:*, uv sync:*, uv lock:*)",
        "Read",
        "Grep",
        "Glob",
        "Edit",
        "Write",
        "AskUserQuestion",
        "Skill(lup:commit)",
    ],
    argument_hint="<what is wrong upstream>",
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
                },
            ),
        ],
    ),
)
