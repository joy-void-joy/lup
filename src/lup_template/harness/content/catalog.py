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
from lup.devtools.roster import LIBRARY_SPECS as LIBRARY_SUBAPPS
from lup.devtools.subapps import unowned
from lup.harness.codescan.common import RuleSelection
from lup.harness.content.application import ApplicationLayout
from lup.harness.modules import (
    Adoption,
    Module,
    ModuleEntry,
    ModuleSelection,
    adopted,
    composed_content,
    composed_guidance,
    scaffold_selection,
)
from lup.seams import Selection
from lup_template.devtools.subapps import APPLICATION_ROSTER
from lup_template.harness.content.modules.catalog import composed_entries
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


def entries(layout: ApplicationLayout = LAYOUT) -> list[ModuleEntry]:
    """Every module this repository could take, each beside its builder."""
    return composed_entries(layout, RULES)


DECLINED: list[str] = []
"""Modules this project does not have, by id.

# lup: template: which of lup's modules this domain has no subject for.
Empty here and spelled anyway, because a default nobody was shown is not a
decision. This repository takes every module it ships — a scaffold is the
demonstration of its own machinery, so a subject nobody composes is a subject
nobody would notice breaking — and that is a statement about *this* repository
rather than advice to a project built from it.

A domain names what it declines here and gets none of it: no skill, no page, no
paragraph, no command tree, no tool group. `dev modules` prints the roster with
each module's summary and what its prose costs, which is the reading this list
is written against; `/lup:init` walks it once with the user. Every module left
unnamed arrives under its own default, including the ones lup grows after this
line was last edited — which is the whole reason this is a list of refusals
rather than a list of what is kept.
"""


def selection(layout: ApplicationLayout = LAYOUT) -> ModuleSelection:
    """What this project has: the derived answers, less what it declined.

    :func:`~lup.harness.modules.scaffold_selection` settles the two answers a
    scaffold should not be making module by module — whether a module is taken,
    and whether its prose loads — and the refusals are applied over that. There
    is no contradiction between the two: naming a module you do not have *is*
    the decision the derivation stands in for, so a stated refusal wins over a
    rule that exists because nobody had stated anything.
    """
    derived = scaffold_selection(
        [entry.spec for entry in entries(layout)], adoptions(layout)
    )
    return ModuleSelection(
        adoptions=[
            entry.model_copy(update={"taken": False})
            if entry.module in DECLINED
            else entry
            for entry in derived.adoptions
        ]
    )


MODULE_SPECS = [entry.spec for entry in entries()]
"""Every module this repository could take, in the order it lays them out.

The roster read through the half that costs nothing. This repository's own
framing opens it and what it says about its own tooling closes it, with the
library's modules in between — a statement about the document rather than about
importance, since guidance renders as the chapter spine crossed with this order.

Projected from the entries rather than listed again, so the order cannot be
stated twice and come out differently the second time.
"""

MODULE_SELECTION = selection()
"""What this repository settled, under its own package name."""

SUBAPPS = MODULE_SELECTION.subapps(MODULE_SPECS)
"""Every top-level CLI group the adopted modules own.

Read before anything is built, which is what makes it usable: the CLI has to
know which command trees it serves in order to compose them, and a name is
known from the spec while a skill is not. What the CLI serves is the
intersection of this and what the library ships, so a module nobody took takes
its commands with it rather than leaving them answering for machinery the
project does not have.
"""

TOOL_GROUPS = MODULE_SELECTION.tool_groups(MODULE_SPECS)
"""Every MCP tool group a session is offered, by adopted module."""

SUBAPP_SELECTION = unowned(SUBAPPS, LIBRARY_SUBAPPS)
"""Which of lup's own sub-apps this CLI declines, as the roster decided it.

Empty for this repository, which takes every module it ships — and that is the
derivation working rather than a statement about lup.
"""

APPLICATION_SPECS = [spec for spec in APPLICATION_ROSTER if spec.name in SUBAPPS]
"""The sub-apps only this application has, narrowed the same way.

``agent`` is served because this project took ``project``, whose subject it is.
"""

SUBAPP_SPECS = SUBAPP_SELECTION.specs(LIBRARY_SUBAPPS, APPLICATION_SPECS)
"""Every sub-app this CLI serves, in the order `--help` lists them."""


def modules(layout: ApplicationLayout = LAYOUT) -> list[Module]:
    """The modules this repository composes, in reading order.

    The layout is a parameter so the roster can be resolved under a package
    name that is not this one. Under this repository's own name a declaration
    that took the layout and one that wrote ``lup_template`` down render the
    same string, so only a roster built as some other project can tell them
    apart — which is the one thing an adopter needs to be true.
    """
    return adopted(entries(layout), selection(layout))


MODULES = modules()
"""The composed roster, built once because every surface below reads it."""

CONTENT = composed_content(MODULES)
"""Every skill and agent this repository's plugin ships, in module order."""

SKILLS = CONTENT.skills
"""Every skill this repository's plugin ships."""

AGENTS = CONTENT.agents
"""Every agent this repository's plugin ships."""

GUIDANCE_SECTIONS = composed_guidance(MODULES, MODULE_SELECTION)
"""The always-loaded document's sections, chapter by chapter and module by module."""

GUIDANCE = guidance.document(GUIDANCE_SECTIONS)
"""The always-loaded document itself."""

PLUGIN_NAME: models.NativeName = "lup"
"""The plugin every declared skill is invoked through.

Named here rather than read off the harness because the roster documents are
compiled into that harness: reading it back to render them would close the
loop between what is declared and what describes the declaration.
"""
