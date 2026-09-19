"""Canonical declaration for the meta skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout
from lup_template.harness.content.skills.deciding import deciding_parts


def skill(layout: ApplicationLayout) -> models.Skill:
    """Review the generated trees against the sources this project keeps them in."""
    return models.Skill(
        id="skill.meta",
        name="meta",
        description="Review and modify the generated harness trees, brainstorm improvements interactively",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=[
            "Bash(ls:*, uv run lup-devtools:*)",
            "Read",
            "Grep",
            "Glob",
            "Edit",
            "Write",
            "Agent",
            "AskUserQuestion",
        ],
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "guidance_file_path": models.NativePath(
                            location="guidance_file", scope="every_tree"
                        ),
                        "skills_path": models.PluginPath(
                            plugin="lup", location="skills", scope="every_tree"
                        ),
                        "agents_path": models.PluginPath(
                            plugin="lup", location="agents", scope="every_tree"
                        ),
                        "hooks_path": models.PluginPath(
                            plugin="lup", location="hooks", scope="every_tree"
                        ),
                        "project_settings_path": models.NativePath(
                            location="project_settings", scope="every_tree"
                        ),
                        "guidance_template_path": models.PluginPath(
                            plugin="lup",
                            location="guidance_template",
                            scope="every_tree",
                        ),
                        "ownership_manifest_path": models.NativePath(
                            location="ownership_manifest"
                        ),
                        "approval": models.RequestApproval(
                            action="editing any source the table names",
                            reason="one edit re-renders into every tree at once",
                        ),
                        "skill_pattern": models.SkillPattern(
                            plugin="lup", placeholder="command-name"
                        ),
                        "project_directory": models.code(layout.directory()),
                        "devtools_directory": models.code(layout.directory("devtools")),
                    },
                ),
                *deciding_parts(),
                models.Passage(module=__name__, name="meta-2"),
            ],
        ),
    )
