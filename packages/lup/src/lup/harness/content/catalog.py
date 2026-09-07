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
            models.TextPart(text=f" — {skill.description}\n"),
        )
    ]


def agent_roster_text(agents: list[models.Agent]) -> str:
    """Format an agent roster as Markdown bullet lines."""
    return "".join(
        f"- `{agent.name}` — {agent.description}\n"
        for agent in sorted(agents, key=lambda agent: agent.name)
    )
