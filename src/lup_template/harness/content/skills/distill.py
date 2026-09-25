"""Canonical declaration for the distill skill."""

import lup.harness.models as models
from lup_template.harness.content.skills.deciding import deciding_parts
from lup_template.harness.content.skills.discovery import discovery_parts

SKILL = models.Skill(
    id="skill.distill",
    name="distill",
    description="Restart from an explored repo — distill its direction into a fresh design",
    arguments=[
        models.Argument(
            name="arguments",
            description="Old repository path(s) and the narrative of the direction found",
            required=False,
        ),
    ],
    tools=[
        "Bash(git:*, ls:*, find:*, uv run lup-devtools:*)",
        "Read",
        "Grep",
        "Glob",
        "Write",
        "Edit",
        "Agent",
        "AskUserQuestion",
        "Skill(lup:import)",
    ],
    argument_hint="<old-repo-path> [more-paths] <narrative of the direction found>",
    prompt=models.PromptDocument(
        source=__name__,
        parts=[
            models.Passage(
                module=__name__,
                values={
                    "brainstorm_skill": models.SkillInvocation(
                        plugin="lup", skill="brainstorm"
                    ),
                    "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
                    # How a carry is made, where upstream is taken to make it:
                    # the stance that nothing is copied holds either way.
                    **{
                        value: models.WhereShipped(
                            parts=[
                                models.Passage(
                                    module=__name__,
                                    name=name,
                                    values={
                                        "import_skill": models.SkillInvocation(
                                            plugin="lup", skill="import"
                                        )
                                    },
                                )
                            ]
                        )
                        for value, name in (
                            ("import_route", "import-route"),
                            ("import_later", "import-later"),
                        )
                    },
                    "arguments": models.ArgumentsRef(),
                    "ask": models.AskUser(
                        question="which repository this restart distills from, and their narrative of the direction it found"
                    ),
                },
            ),
            *discovery_parts(),
            *deciding_parts(),
            models.Passage(
                module=__name__,
                name="archaeology",
                values={
                    "ask": models.AskUser(
                        question="which of the old project's concepts survive into the restart and which die with it, with the reason for each — and whether this restart is the only successor or one of several splitting the exploration"
                    ),
                    "brainstorm_skill": models.SkillInvocation(
                        plugin="lup", skill="brainstorm"
                    ),
                    "init_skill": models.SkillInvocation(plugin="lup", skill="init"),
                },
            ),
        ],
    ),
)
