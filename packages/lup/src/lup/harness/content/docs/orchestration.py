"""Canonical agent-orchestration patterns guidance."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def document(layout: ApplicationLayout) -> models.PromptDocument:
    """The delegation catalog, pointing at this project's own worked examples."""
    return models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "agent_tools_realtime_py": models.code(
                        layout.path("agent", "tools", "realtime.py")
                    ),
                    "agent_tools_nested_py": models.code(
                        layout.path("agent", "tools", "nested.py")
                    ),
                    "agent_tools_example_py": models.code(
                        layout.path("agent", "tools", "example.py")
                    ),
                },
            ),
        ],
    )
