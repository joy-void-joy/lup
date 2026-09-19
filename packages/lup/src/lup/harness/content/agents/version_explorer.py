"""Canonical declaration for the version-explorer agent."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def agent(layout: ApplicationLayout) -> models.Agent:
    """Inventory version evidence across this project's own agent sources."""
    return models.Agent(
        id="agent.version-explorer",
        name="version-explorer",
        description="Inventory version-impact evidence across the repository",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "agent_prompts_py": models.code(
                            layout.path("agent", "prompts.py")
                        ),
                        "agent_core_py": models.code(layout.path("agent", "core.py")),
                        "agent_tool_policy_py": models.code(
                            layout.path("agent", "tool_policy.py")
                        ),
                        "agent_models_py": models.code(
                            layout.path("agent", "models.py")
                        ),
                        "agent_subagents_py": models.code(
                            layout.path("agent", "subagents.py")
                        ),
                        "agent_config_py": models.code(
                            layout.path("agent", "config.py")
                        ),
                        "agent_tools_directory": models.plain(
                            layout.directory("agent", "tools")
                        ),
                        "agent_directory": models.plain(layout.directory("agent")),
                        "project_directory": models.plain(layout.directory()),
                        "agent_prompts_py_2": models.plain(
                            layout.path("agent", "prompts.py")
                        ),
                        "agent_core_py_2": models.plain(
                            layout.path("agent", "core.py")
                        ),
                        "agent_tool_policy_py_2": models.plain(
                            layout.path("agent", "tool_policy.py")
                        ),
                    },
                ),
            ],
        ),
        tools=["Read", "Grep", "Glob", "Bash"],
        model="strongest",
        color="green",
    )
