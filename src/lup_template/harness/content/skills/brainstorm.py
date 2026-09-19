"""Canonical declaration for the brainstorm skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout
from lup_template.harness.content.skills.deciding import deciding_parts
from lup_template.harness.content.skills.discovery import discovery_parts


def skill(layout: ApplicationLayout) -> models.Skill:
    """Explore a design against the agent sources this project actually has."""
    return models.Skill(
        id="skill.brainstorm",
        name="brainstorm",
        description="Design exploration — a new agent before init or a feature inside a project, every decision walked with the user",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=[
            "Bash(find:*, ls:*, uv run lup-devtools:*)",
            "Read",
            "Grep",
            "Glob",
            "Write",
            "Edit",
            "Agent",
            "WebFetch",
            "WebSearch",
            "AskUserQuestion",
        ],
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "init_skill": models.SkillInvocation(
                            plugin="lup", skill="init"
                        ),
                        "arguments": models.ArgumentsRef(),
                    },
                ),
                *discovery_parts(),
                *deciding_parts(),
                models.Passage(
                    module=__name__,
                    name="what-you-know",
                    values={
                        "runtime_docs": models.RuntimeDocs(),
                        "ask": models.AskUser(
                            question="which of the approaches just described to design around"
                        ),
                        "init_skill": models.SkillInvocation(
                            plugin="lup", skill="init"
                        ),
                        "agent_core_py": models.code(layout.path("agent", "core.py")),
                        "agent_toolsets_py": models.code(
                            layout.path("agent", "toolsets.py")
                        ),
                        "agent_tools_example_py": models.code(
                            layout.path("agent", "tools", "example.py")
                        ),
                        "agent_tools_nested_py": models.code(
                            layout.path("agent", "tools", "nested.py")
                        ),
                        "agent_tools_realtime_py": models.code(
                            layout.path("agent", "tools", "realtime.py")
                        ),
                        "agent_tools_reflect_py": models.code(
                            layout.path("agent", "tools", "reflect.py")
                        ),
                        "agent_models_py": models.code(
                            layout.path("agent", "models.py")
                        ),
                        "agent_subagents_py": models.code(
                            layout.path("agent", "subagents.py")
                        ),
                        "agent_tool_policy_py": models.code(
                            layout.path("agent", "tool_policy.py")
                        ),
                        "agent_prompts_py": models.code(
                            layout.path("agent", "prompts.py")
                        ),
                    },
                ),
            ],
        ),
    )
