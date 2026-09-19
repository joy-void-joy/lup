"""Canonical declaration for the fb-reflect skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Reflect on the loop itself, naming the prompt this project actually has."""
    return models.Skill(
        id="skill.fb-reflect",
        name="fb-reflect",
        description="Meta and meta-meta reflection on the feedback loop process itself",
        tools=[
            "Bash(uv run lup-devtools:*)",
            "Read",
            "Grep",
            "Glob",
            "Edit",
            "Write",
            "AskUserQuestion",
        ],
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "agent_prompts_py": models.code(
                            layout.path("agent", "prompts.py")
                        ),
                        "devtools_directory": models.code(layout.directory("devtools")),
                    },
                ),
            ],
        ),
    )
