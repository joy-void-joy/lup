# lup: ignore[constant-declaration]
# Every constant here is this repository's own composition — which modules it
# takes, what it changed about each, and what its plugin is called. A
# composition root is where a judgement is finally made rather than passed on,
# so there is no caller above it to take these from.
"""Which modules this repository takes, and what it changed about each.

What reaches a project is a set of modules rather than a list of skills, so
this states a delta against that set and nothing else. Everything downstream
— the plugin's skills and agents, the pages under ``docs/``, the always-loaded
document, which sub-apps the CLI serves, which tool groups a session is
offered — is derived from the result rather than declared beside it, which is
what makes declining a subject remove all five at once instead of four.

This is also where the library learns what this application is called. Several
of its skills name a path inside the reading project's own package, and only
the project knows that name, so it is supplied here rather than assumed there.
"""

from pathlib import Path

import lup.harness.models as models
import lup_template.harness.content.guidance as guidance
from lup.harness.codescan.common import RuleSelection
from lup.harness.content.application import ApplicationLayout
from lup.harness.content.modules.catalog import library_modules
from lup.harness.content.modules.specs import LIBRARY_SPECS
from lup.harness.modules import (
    Adoption,
    Module,
    ModuleSelection,
    adopted,
    composed_content,
    composed_guidance,
    scaffold_selection,
)
from lup.seams import Selection
from lup_template.harness.content.modules.catalog import (
    closing_modules,
    opening_modules,
)
from lup_template.harness.content.modules.specs import PROJECT_SPECS
from lup_template.harness.content.skills.meta import skill as build_meta

LAYOUT = ApplicationLayout(package=Path(__file__).resolve().parents[2].name)
"""Where this application's own code sits, for the library prose that names it.

Derived from where this file actually sits rather than written down, for the
reason ``DevProject.package`` derives its own: initialization renames the
package, and a literal would go on naming one that is gone.
"""

RULES = RuleSelection(retired=[])
"""Which of the library's scan rules this repository holds itself to.

# lup: template: which of the library's scan rules this domain holds itself to.
Spelled empty rather than left to the default, because a default nobody was
shown is not a decision — and a repository that settled a convention
differently is not defective there. Name the few it drops with
`dev seams --retire <rule-id>`, or drop the family outright with
`--retire-all`, which is one answer here instead of thirty retirements one
denial at a time.

Read by two things that have to agree: the hook set enforcing these rules, and
the design-principles section teaching them. A rule retired in one place and
taught in the other would be prose describing a gate that never fires, so both
take this one value rather than each declaring its own.
"""


def adoptions(layout: ApplicationLayout) -> list[Adoption]:
    """What this repository declares against modules whose subjects it shares.

    Additions rather than forks. Each of these is a section or a skill this
    repository wrote about a subject the library owns — how *this* project's
    policy is changed, what its markers mean, where its deferred work goes —
    and each arrives under a new id, so the module goes on growing underneath
    while this states only what it added.

    Built against a layout rather than declared, for the same reason the
    library's builders are: ``/lup:meta`` names a path inside the reading
    project's own package, so a constant here would go on naming this one
    after an adopter renamed theirs.

    Nothing here says ``taken`` or ``loads_guidance``: those two are derived
    from the roster by :func:`~lup.harness.modules.scaffold_selection`,
    because a scaffold settling them module by module is how a list goes
    stale.
    """
    return [
        Adoption(
            module="core",
            guidance=Selection(
                overrides=[
                    guidance.CHANGING_THE_POLICY,
                    guidance.MARKER_VOCABULARY,
                    guidance.DEFERRED_WORK,
                ]
            ),
        ),
        Adoption(
            module="git-workflow",
            guidance=Selection(overrides=[guidance.COMMIT_TYPE_POINTER]),
        ),
        Adoption(
            module="feedback-loop",
            guidance=Selection(overrides=[guidance.SELF_IMPROVEMENT]),
        ),
        Adoption(
            module="meta",
            content=models.ContentSelection(skills=[build_meta(layout)]),
        ),
    ]


def selection(layout: ApplicationLayout = LAYOUT) -> ModuleSelection:
    """Every module taken, only the offered ones' prose loaded, plus the delta."""
    return scaffold_selection([*PROJECT_SPECS, *LIBRARY_SPECS], adoptions(layout))


MODULE_SELECTION = selection()
"""What this repository settled, under its own package name."""


def modules(layout: ApplicationLayout = LAYOUT) -> list[Module]:
    """The modules this repository composes, in reading order.

    This repository's own framing opens the roster and what it says about its
    own tooling closes it, with the library's modules in between. That is a
    statement about the document rather than about importance: guidance renders
    as the chapter spine crossed with this order, so a section's place inside
    its chapter is its module's place here.

    The layout is a parameter so the roster can be resolved under a package
    name that is not this one. Under this repository's own name a declaration
    that took the layout and one that wrote ``lup_template`` down render the
    same string, so only a roster built as some other project can tell them
    apart — which is the one thing an adopter needs to be true.
    """
    return adopted(
        [
            *opening_modules(),
            *library_modules(layout, RULES),
            *closing_modules(layout),
        ],
        selection(layout),
    )


MODULES = modules()
"""The composed roster, built once because every surface below reads it."""

CONTENT = composed_content(MODULES)
"""Every skill and agent this repository's plugin ships, in module order."""

SKILLS = CONTENT.skills
"""Every skill this repository's plugin ships."""

AGENTS = CONTENT.agents
"""Every agent this repository's plugin ships."""

GUIDANCE_SECTIONS = composed_guidance(MODULES)
"""The always-loaded document's sections, chapter by chapter and module by module."""

GUIDANCE = guidance.document(GUIDANCE_SECTIONS)
"""The always-loaded document itself."""

SUBAPPS = [name for module in MODULES for name in module.subapps]
"""Every top-level CLI group the adopted modules own.

What the CLI serves is the intersection of this and what the library ships, so
a module nobody took takes its commands with it rather than leaving them
answering for machinery the project does not have.
"""

TOOL_GROUPS = [group for module in MODULES for group in module.tool_groups]
"""Every MCP tool group a session is offered, by adopted module."""

PLUGIN_NAME: models.NativeName = "lup"
"""The plugin every declared skill is invoked through.

Named here rather than read off the harness because the roster documents are
compiled into that harness: reading it back to render them would close the
loop between what is declared and what describes the declaration.
"""
