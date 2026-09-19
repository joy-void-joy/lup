"""Canonical declaration for the modify-command skill."""

import lup.harness.models as models
from lup.harness.content.application import ApplicationLayout


def skill(layout: ApplicationLayout) -> models.Skill:
    """Modify a declaration, in whichever half of this project owns it."""
    return models.Skill(
        id="skill.modify-command",
        name="modify-command",
        description="Modify an existing slash command based on a description or delta",
        arguments=[
            models.Argument(
                name="arguments",
                description="Optional arguments supplied with the skill invocation",
                required=False,
            ),
        ],
        tools=["Read", "Edit", "Write", "Glob", "Grep", "AskUserQuestion"],
        argument_hint="[command-name] [delta or description] [--args hint1 hint2]",
        prompt=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=__name__,
                    values={
                        "arguments": models.ArgumentsRef(),
                        "modify_command_skill": models.SkillInvocation(
                            plugin="lup", skill="modify-command"
                        ),
                        "ask": models.AskUser(
                            question="which command to modify, and what changes to make to it"
                        ),
                        "skills_path": models.PluginPath(
                            plugin="lup", location="skills", scope="every_tree"
                        ),
                        "approval": models.RequestApproval(
                            action="writing the changed declaration",
                            reason="the change reaches every tree the declaration renders into",
                        ),
                        "harness_content_skills_directory": models.plain(
                            layout.directory("harness", "content", "skills")
                        ),
                    },
                ),
            ],
        ),
    )
