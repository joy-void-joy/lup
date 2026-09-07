"""Turning an observed agent failure into a durable capability change.

The phases are separate skills because the loop is separable: noticing, then
investigating what actually happened, then deciding what change answers it,
then making that change, then reflecting on whether it held. A project that
does not run this loop reclaims the sub-app, the seven skills, the explorer
agent, the page, and the guidance section that points at all of them.

The reporting-friction and defect-disposition prose is *not* here. Both say
what to do about a defect the moment you see one, which a project without this
loop still has to answer — so they sit in core and this module carries only
the loop's own section.
"""

from lup.harness.content.agents.trace_explorer import agent as build_trace_explorer
from lup.harness.content.application import ApplicationLayout
from lup.harness.content.docs import self_improvement
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.specs import FEEDBACK_LOOP
from lup.harness.content.skills.fb_analyze import SKILL as SKILL_FB_ANALYZE
from lup.harness.content.skills.fb_implement import SKILL as SKILL_FB_IMPLEMENT
from lup.harness.content.skills.fb_investigate import skill as build_fb_investigate
from lup.harness.content.skills.fb_reflect import skill as build_fb_reflect
from lup.harness.content.skills.fb_status import SKILL as SKILL_FB_STATUS
from lup.harness.content.skills.feedback_loop import SKILL as SKILL_FEEDBACK_LOOP
from lup.harness.content.skills.review import skill as build_review
from lup.harness.models import ContentRoster
from lup.harness.modules import Module


def module(layout: ApplicationLayout) -> Module:
    """The self-improvement loop as one value, against the project's layout."""
    return Module(
        spec=FEEDBACK_LOOP,
        content=ContentRoster(
            skills=[
                SKILL_FB_ANALYZE,
                SKILL_FB_IMPLEMENT,
                build_fb_investigate(layout),
                build_fb_reflect(layout),
                SKILL_FB_STATUS,
                SKILL_FEEDBACK_LOOP,
                build_review(layout),
            ],
            agents=[build_trace_explorer(layout)],
        ),
        documents=[
            page(
                "self_improvement",
                "self-improvement.md",
                lambda _: self_improvement.DOCUMENT,
            )
        ],
    )
