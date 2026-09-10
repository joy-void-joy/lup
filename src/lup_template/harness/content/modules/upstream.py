"""Keeping a project in step with what it was built from.

Two skills and the commands underneath them. ``/lup:update`` reviews every
upstream commit since the last sync and decides what to apply here; ``import``
pulls one feature from a tracked repository rather than rewriting it. The
``sync`` sub-app is the read half of the first — its own docstring says so —
which is why it belongs here rather than beside the other project commands.

A project with no upstream declines this and loses nothing. A project that has
one and declines it goes on diverging from it silently, which is the failure
this exists to make visible.
"""

from lup.harness.content.docs import upstream_reports
from lup.harness.content.docs.catalog import page
from lup.harness.models import ContentRoster
from lup.harness.modules import Module
from lup_template.harness.content.modules.specs import UPSTREAM
from lup_template.harness.content.skills.import_skill import SKILL as SKILL_IMPORT
from lup_template.harness.content.skills.update import SKILL as SKILL_UPDATE


def module() -> Module:
    """Staying in step with upstream as one value."""
    return Module(
        spec=UPSTREAM,
        content=ContentRoster(skills=[SKILL_IMPORT, SKILL_UPDATE]),
        documents=[
            page(
                "upstream_reports",
                "upstream-reports.md",
                lambda _: upstream_reports.document(),
            )
        ],
    )
