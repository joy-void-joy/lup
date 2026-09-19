"""Canonical declaration for the trace-explorer agent."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def agent(layout: ApplicationLayout) -> models.Agent:
    """Read traces in bulk, naming this project's own prompt when it cites one."""
    return models.Agent(
        id="agent.trace-explorer",
        name="trace-explorer",
        description="Investigate trace evidence without changing production files",
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
        color="cyan",
    )
