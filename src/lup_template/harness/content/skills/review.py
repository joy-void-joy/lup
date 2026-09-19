"""The review skill as this repository reviews a session: against its agent.

The library's review reads a trace against the harness, which is what every
project has. This repository's sessions run an agent of their own, so the
same walk reads more — the system prompt, the toolset registry, the tool
policy, the factory wiring — and the step that names them has to name this
repository's layout. Declared under the library's id so it replaces the
harness-only version in place, through the feedback-loop adoption.
"""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Review a trace against the agent sources this project actually has."""
    return models.Skill(
        id="skill.review",
        name="review",
        description="Review a session trace for workflow quality, tool usage, and improvement opportunities",
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
            "Agent",
        ],
        argument_hint="[session ID, file path, or pasted trace]",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "agent_prompts_py": models.code(
                            layout.path("agent", "prompts.py")
                        ),
                        "agent_toolsets_py": models.code(
                            layout.path("agent", "toolsets.py")
                        ),
                        "agent_tool_policy_py": models.code(
                            layout.path("agent", "tool_policy.py")
                        ),
                        "agent_tools_directory": models.code(
                            layout.directory("agent", "tools")
                        ),
                        "agent_core_py": models.code(layout.path("agent", "core.py")),
                        "harness_content_guidance_py": models.code(
                            layout.path("harness", "content", "guidance.py")
                        ),
                        "harness_catalog_py": models.code(
                            layout.path("harness", "catalog.py")
                        ),
                        "agent_directory": models.plain(layout.directory("agent")),
                    },
                ),
            ],
        ),
    )
