"""Canonical declaration for the refactor skill."""

import lup.harness.models as models

SKILL = models.Skill(
    id="skill.refactor",
    name="refactor",
    description="Rewrite a file or folder from scratch while respecting coding conventions",
    arguments=[
        models.Argument(
            name="arguments",
            description="Optional arguments supplied with the skill invocation",
            required=False,
        ),
    ],
    tools=[
        "Bash(git:*, uv run lup-devtools:*)",
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "AskUserQuestion",
    ],
    argument_hint="<path>",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "arguments": models.ArgumentsRef(),
                    "ask": models.AskUser(question="which file or folder to refactor"),
                    "guidance_file_path": models.NativePath(location="guidance_file"),
                    "watch": models.WatchOutput(
                        command="uv run lup-devtools dev check"
                    ),
                },
            ),
        ],
    ),
)
