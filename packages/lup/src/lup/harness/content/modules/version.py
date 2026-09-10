"""Deciding a version change, and making it.

One skill and two agents, which is the ratio the subject actually has: the
deciding is the work, and it is done by an explorer that inventories what
changed and a reviewer that judges the proposal without having made it. The
separation is the one rule kept from the argument against roles — whoever
proposes a bump does not also ratify it.
"""

from lup.harness.content.agents.version_explorer import agent as build_version_explorer
from lup.harness.content.agents.version_reviewer import agent as build_version_reviewer
from lup.harness.content.application import ApplicationLayout
from lup.harness.content.modules.specs import VERSION
from lup.harness.content.skills.bump import SKILL as SKILL_BUMP
from lup.harness.models import ContentRoster
from lup.harness.modules import Module


def module(layout: ApplicationLayout) -> Module:
    """Version work as one value, against the project's layout."""
    return Module(
        spec=VERSION,
        content=ContentRoster(
            skills=[SKILL_BUMP],
            agents=[build_version_explorer(layout), build_version_reviewer(layout)],
        ),
    )
