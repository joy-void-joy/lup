"""How a roster of skills and agents is written down, wherever one is composed.

There is no roster here. A skill or an agent belongs to the subject it serves,
so each is declared by the module owning that subject and reaches a project
only because the project took the module — which is what a second list beside
those modules would quietly undo, by naming a declaration nobody adopted and
so making it look adopted. Whether every declaration on disk is claimed by
exactly one module is :mod:`lup.harness.coverage`'s question, asked against the
filesystem rather than against a list somebody has to remember to extend.

What is left is the two formatters. Both take the roster they render instead of
reading one, because a document describing "every skill this plugin ships" has
to see both halves and only the composing project has them.
"""

import lup.harness.models as models
from lup.formats.markdown import ProseCode


def skill_roster_parts(
    skills: list[models.Skill], plugin: models.NativeName
) -> list[models.PromptPart]:
    """Format a skill roster as portable bullet-list document parts.

    The invocation is issued rather than spelled, so the same roster renders
    in whichever sigil the reading runtime uses.
    """
    return [
        part
        for skill in sorted(skills, key=lambda skill: skill.name)
        for part in (
            models.TextPart(text="- "),
            models.SkillInvocation(plugin=plugin, skill=skill.name),
            models.TextPart(text=" — "),
            models.plain(skill.description),
            models.TextPart(text="\n"),
        )
    ]


def agent_roster_bullets(agents: list[models.Agent]) -> models.BulletList:
    """Format an agent roster as one derived list of bullets.

    A list rather than joined text, for the reason every roster here is one:
    the names and descriptions come from declarations, and a description
    carrying a newline would otherwise end the bullet it was written into.
    """
    return models.BulletList(
        items=[
            models.BulletItem(lead=ProseCode(text=agent.name), text=agent.description)
            for agent in sorted(agents, key=lambda agent: agent.name)
        ]
    )
