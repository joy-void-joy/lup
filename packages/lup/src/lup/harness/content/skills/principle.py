"""Canonical declaration for the principle skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Sweep a principle across this project's own halves, wherever they sit."""
    return models.Skill(
        id="skill.principle",
        name="principle",
        description="Propagate a general principle across the entire repo",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=[
            "Bash(uv run lup-devtools:*)",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "AskUserQuestion",
            "Agent",
        ],
        argument_hint="<principle description>",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "ask": models.AskUser(
                            question="whether that formulation is the right one"
                        ),
                        "guidance_file_path": models.NativePath(
                            location="guidance_file", scope="every_tree"
                        ),
                        "guidance_template_path": models.PluginPath(
                            plugin="lup",
                            location="guidance_template",
                            scope="every_tree",
                        ),
                        "skills_path": models.PluginPath(
                            plugin="lup",
                            location="skills",
                            member="*",
                            scope="every_tree",
                        ),
                        "hooks_path": models.PluginPath(
                            plugin="lup", location="hooks", scope="every_tree"
                        ),
                        "approval": models.RequestApproval(
                            action="applying that layer's edits",
                            reason="a principle sweep touches every layer and is hard to unpick once several have landed",
                        ),
                        "harness_content_guidance_py": models.code(
                            layout.path("harness", "content", "guidance.py")
                        ),
                        "harness_content_template_sections_py": models.code(
                            layout.path("harness", "content", "template_sections.py")
                        ),
                        "harness_content_skills_directory": models.plain(
                            layout.directory("harness", "content", "skills")
                        ),
                        "harness_catalog_py": models.code(
                            layout.path("harness", "catalog.py")
                        ),
                        "agent_directory": models.code(layout.directory("agent")),
                        "environment_directory": models.code(
                            layout.directory("environment")
                        ),
                        "devtools_directory": models.code(layout.directory("devtools")),
                    },
                ),
            ],
        ),
    )
