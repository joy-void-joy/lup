"""Canonical declaration for the add-command skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Author a skill into whichever half of this project owns its subject."""
    return models.Skill(
        id="skill.add-command",
        name="add-command",
        description="Create a new slash command in the lup plugin",
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
        ],
        argument_hint="[name] [description]",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "add_command_skill": models.SkillInvocation(
                            plugin="lup", skill="add-command"
                        ),
                        "skills_path": models.PluginPath(
                            plugin="lup",
                            location="skills",
                            member="<name>",
                            scope="every_tree",
                        ),
                        "watch": models.WatchOutput(
                            command="uv run lup-devtools dev check"
                        ),
                        "skill_pattern": models.SkillPattern(
                            plugin="lup", placeholder="<command-name>"
                        ),
                        "harness_content_skills_directory": models.code(
                            layout.directory("harness", "content", "skills")
                        ),
                    },
                ),
            ],
        ),
    )
