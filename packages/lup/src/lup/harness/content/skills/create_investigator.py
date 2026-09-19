"""Canonical declaration for the create-investigator skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Author an investigator into whichever half of this project owns it."""
    return models.Skill(
        id="skill.create-investigator",
        name="create-investigator",
        description="Create a new diagnostic command that traces pasted output to a root cause, like the debug skill",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=["Write", "Read", "Glob", "Grep", "AskUserQuestion"],
        argument_hint="[command-name] [brief description of what it investigates]",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "add_command_skill": models.SkillInvocation(
                            plugin="lup", skill="add-command"
                        ),
                        "arguments": models.ArgumentsRef(),
                        "ask": models.AskUser(
                            question="what the command should be called and what it investigates"
                        ),
                        "skills_path": models.PluginPath(
                            plugin="lup", location="skills", scope="every_tree"
                        ),
                        "ask_2": models.AskUser(
                            question="what needs adjusting, if anything"
                        ),
                        "harness_directory": models.code(layout.directory("harness")),
                    },
                ),
            ],
        ),
    )
