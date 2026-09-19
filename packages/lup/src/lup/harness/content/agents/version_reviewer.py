"""Canonical declaration for the version-reviewer agent."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def agent(layout: ApplicationLayout) -> models.Agent:
    """Review one version against the prompt this project actually ships."""
    return models.Agent(
        id="agent.version-reviewer",
        name="version-reviewer",
        description="Independently review a proposed version change",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "agent_prompts_py": models.plain(
                            layout.path("agent", "prompts.py")
                        )
                    },
                ),
            ],
        ),
        tools=["Read", "Grep", "Glob", "Bash"],
        model="strongest",
        color="yellow",
    )
