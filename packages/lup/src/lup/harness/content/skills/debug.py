"""Canonical declaration for the debug skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Trace an error to its root cause, naming this project's own sources."""
    return models.Skill(
        id="skill.debug",
        name="debug",
        description="Trace an error through logs to find root cause",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=[
            "Read",
            "Grep",
            "Glob",
            "Bash(ls:*, wc:*, sort:*, tail:*, stat:*, uv run lup-devtools:*)",
        ],
        argument_hint="[error message or fragment]",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "agent_core_py": models.plain(layout.path("agent", "core.py")),
                    },
                ),
            ],
        ),
    )
