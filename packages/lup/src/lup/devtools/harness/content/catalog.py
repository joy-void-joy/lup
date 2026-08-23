"""The skills and agents lup ships, and how a roster is written down.

Aggregation is explicit imports rather than a scan of the directory: a
misspelled or missing module is a type-checking error rather than a skill
that silently stops being declared.

A project composes these with its own and passes the result to its harness,
so the formatters take the roster they render instead of reading one — a
document describing "every skill this plugin ships" has to see both halves.

The roster is built rather than written down because some of these
declarations name a path inside the reading project's own package, and only
that project knows what its package is called. Those modules export a builder
taking an :class:`~lup.devtools.harness.content.application.ApplicationLayout`;
the rest export the declaration directly, and the difference is exactly
whether the prose has an application path in it.
"""

import lup.harness.models as models
from lup.devtools.harness.content.agents.tdd_implementer import (
    AGENT as AGENT_TDD_IMPLEMENTER,
)
from lup.devtools.harness.content.agents.trace_explorer import (
    agent as build_trace_explorer,
)
from lup.devtools.harness.content.agents.version_explorer import (
    agent as build_version_explorer,
)
from lup.devtools.harness.content.agents.version_reviewer import (
    agent as build_version_reviewer,
)
from lup.devtools.harness.content.application import ApplicationLayout
from lup.devtools.harness.content.skills.add_command import (
    skill as build_add_command,
)
from lup.devtools.harness.content.skills.bump import SKILL as SKILL_BUMP
from lup.devtools.harness.content.skills.close import SKILL as SKILL_CLOSE
from lup.devtools.harness.content.skills.commit import SKILL as SKILL_COMMIT
from lup.devtools.harness.content.skills.analyze import SKILL as SKILL_ANALYZE
from lup.devtools.harness.content.skills.create_investigator import (
    skill as build_create_investigator,
)
from lup.devtools.harness.content.skills.debug import skill as build_debug
from lup.devtools.harness.content.skills.fb_analyze import (
    SKILL as SKILL_FB_ANALYZE,
)
from lup.devtools.harness.content.skills.fb_implement import (
    SKILL as SKILL_FB_IMPLEMENT,
)
from lup.devtools.harness.content.skills.fb_investigate import (
    skill as build_fb_investigate,
)
from lup.devtools.harness.content.skills.fb_reflect import (
    skill as build_fb_reflect,
)
from lup.devtools.harness.content.skills.fb_status import (
    SKILL as SKILL_FB_STATUS,
)
from lup.devtools.harness.content.skills.feedback_loop import (
    SKILL as SKILL_FEEDBACK_LOOP,
)
from lup.devtools.harness.content.skills.hooks import skill as build_hooks
from lup.devtools.harness.content.skills.implementer import (
    SKILL as SKILL_IMPLEMENTER,
)
from lup.devtools.harness.content.skills.land import SKILL as SKILL_LAND
from lup.devtools.harness.content.skills.merge import SKILL as SKILL_MERGE
from lup.devtools.harness.content.skills.modify_command import (
    skill as build_modify_command,
)
from lup.devtools.harness.content.skills.principle import (
    skill as build_principle,
)
from lup.devtools.harness.content.skills.rebase import SKILL as SKILL_REBASE
from lup.devtools.harness.content.skills.refactor import SKILL as SKILL_REFACTOR
from lup.devtools.harness.content.skills.refactor_tools import (
    skill as build_refactor_tools,
)
from lup.devtools.harness.content.skills.report import SKILL as SKILL_REPORT
from lup.devtools.harness.content.skills.resolve import SKILL as SKILL_RESOLVE
from lup.devtools.harness.content.skills.resolve_reviewer import (
    SKILL as SKILL_RESOLVE_REVIEWER,
)
from lup.devtools.harness.content.skills.review import skill as build_review
from lup.devtools.harness.content.skills.verify_solved import (
    SKILL as SKILL_VERIFY_SOLVED,
)


def library_skills(layout: ApplicationLayout) -> list[models.Skill]:
    """Every skill lup ships: the git and review loop, the resolver, code work,
    harness authoring, and the feedback loop. Each automates agent work inside a
    project rather than the standing up of one."""
    # lup: ignore[library-default] — the skills this library authors, so the list is what it ships rather than a choice made for an adopter
    return [
        build_add_command(layout),
        SKILL_ANALYZE,
        SKILL_BUMP,
        SKILL_CLOSE,
        SKILL_COMMIT,
        build_create_investigator(layout),
        build_debug(layout),
        SKILL_FB_ANALYZE,
        SKILL_FB_IMPLEMENT,
        build_fb_investigate(layout),
        build_fb_reflect(layout),
        SKILL_FB_STATUS,
        SKILL_FEEDBACK_LOOP,
        build_hooks(layout),
        SKILL_IMPLEMENTER,
        SKILL_LAND,
        SKILL_MERGE,
        build_modify_command(layout),
        build_principle(layout),
        SKILL_REBASE,
        SKILL_REFACTOR,
        build_refactor_tools(layout),
        SKILL_REPORT,
        SKILL_RESOLVE,
        SKILL_RESOLVE_REVIEWER,
        build_review(layout),
        SKILL_VERIFY_SOLVED,
    ]


def library_agents(layout: ApplicationLayout) -> list[models.Agent]:
    """Every agent lup ships, each a generic role over library machinery."""
    # lup: ignore[library-default] — the agents this library authors, so the list is what it ships rather than a choice made for an adopter
    return [
        AGENT_TDD_IMPLEMENTER,
        build_trace_explorer(layout),
        build_version_explorer(layout),
        build_version_reviewer(layout),
    ]


def library_content(layout: ApplicationLayout) -> models.ContentRoster:
    """What a project starts from: everything lup ships, as one roster to narrow.

    Paired here rather than composed by each adopter so a project takes the two
    halves the same way it takes the sub-app roster — retire what it settled
    differently, add what only it has, and receive the rest of what lup grows
    without a copied list standing between.
    """
    return models.ContentRoster(
        skills=library_skills(layout), agents=library_agents(layout)
    )


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
