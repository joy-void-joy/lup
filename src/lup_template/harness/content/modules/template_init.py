"""Standing a lup project up, and keeping it configured once it is standing.

Four skills whose subject is the project rather than the work inside it:
designing one before any code exists, initializing it, installing the plugin
into it, and restarting one from a predecessor that was explored rather than
finished. They have nothing to say inside a working repository, which is why
they stay behind when the rest of the roster becomes the library's.

On for an adopter, not only for the scaffold. A project built from this one
still runs ``/lup:init`` — the whole point of the module system is that
initialization becomes a module selection — and still installs the plugin into
whatever it grows into next. What an adopter drops is ``examples``.

The configuration section is here because it is the same subject at rest: what
a project reads from its environment, and where the variables are written
down. It closes the tooling chapter, after the library's word on long-running
work, which is the ordering this module's position in the roster produces.
"""

import lup_template.harness.content.guidance as guidance
from lup.harness.content.docs.catalog import page
from lup.harness.modules import Module
from lup.harness.content.application import ApplicationLayout
from lup.harness.models import ContentRoster
from lup_template.harness.content.docs import template
from lup_template.harness.content.modules.specs import TEMPLATE_INIT
from lup_template.harness.content.skills.brainstorm import skill as build_brainstorm
from lup_template.harness.content.skills.distill import SKILL as SKILL_DISTILL
from lup_template.harness.content.skills.init import SKILL as SKILL_INIT
from lup_template.harness.content.skills.install import SKILL as SKILL_INSTALL


def module(layout: ApplicationLayout) -> Module:
    """Standing a project up as one value, against the project's layout."""
    return Module(
        spec=TEMPLATE_INIT,
        content=ContentRoster(
            skills=[
                build_brainstorm(layout),
                SKILL_DISTILL,
                SKILL_INIT,
                SKILL_INSTALL,
            ]
        ),
        guidance=[guidance.CONFIGURATION],
        documents=[
            page(
                "template",
                "template.md",
                lambda context: template.document(context.root, context.subapps),
                layout.docs(),
            )
        ],
    )
