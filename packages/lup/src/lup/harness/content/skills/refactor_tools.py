"""Canonical declaration for the refactor-tools skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Audit this project's own tool surface, wherever its package sits."""
    return models.Skill(
        id="skill.refactor-tools",
        name="refactor-tools",
        description="Audit SDK agent tools and subagents \u2014 find gaps, overlaps, and refactoring opportunities",
        tools=[
            "Read",
            "Grep",
            "Glob",
            "Bash(ls:*, uv run lup-devtools:*)",
            "Agent",
            "WebSearch",
            "AskUserQuestion",
        ],
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "agent_toolsets_py": models.code(
                            layout.path("agent", "toolsets.py")
                        ),
                        "agent_core_py": models.code(layout.path("agent", "core.py")),
                        "agent_tool_policy_py": models.code(
                            layout.path("agent", "tool_policy.py")
                        ),
                        "agent_subagents_py": models.code(
                            layout.path("agent", "subagents.py")
                        ),
                        "agent_tools_nested_py": models.code(
                            layout.path("agent", "tools", "nested.py")
                        ),
                        "agent_tools_directory": models.code(
                            layout.directory("agent", "tools")
                        ),
                        "agent_config_py": models.code(
                            layout.path("agent", "config.py")
                        ),
                    },
                ),
            ],
        ),
    )
