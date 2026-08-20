"""A project's roster delta, and the two readings it has to reach together.

The failure this guards against is the one the roster exists to remove: a
sub-app the library ships that a project never learns it has. That failure is
silent by construction — an absent name looks exactly like a declined one — so
what is pinned here is that the default really is everything, that a retirement
reaches both the wired CLI and the documents describing it, and that this
repository has declined nothing without saying so.

The wired half is exercised end to end by ``test_devtools_cli``, which walks
the composed tree; what these need is the projection, so they take specs and
throwaway Typer apps rather than a whole declaration.
"""

import typer

from lup.devtools.harness.content.application import ApplicationLayout
from lup.devtools.harness.content.catalog import library_content
from lup.devtools.roster import LIBRARY_ROSTER, LIBRARY_SPECS
from lup.devtools.subapps import SubApp, SubAppSelection, subapp
from lup.harness.models import ContentSelection
from lup_template.devtools.subapps import APPLICATION_SPECS, SELECTION, SUBAPP_SPECS

LIBRARY_CONTENT = library_content(ApplicationLayout(package="worked_example"))
"""The whole library roster, under a package name that is nobody's real one.

Selection is what these exercise, and it does not read a path — so naming a
package here that no checkout has keeps a roster assertion from passing only
because the layout happened to match this repository's own.
"""

RETIRED = SubAppSelection(retired=["dashboard", "report"])


def wired(name: str) -> SubApp:
    """One throwaway entry, for a projection that never runs a command."""
    return subapp(name, f"{name} help", typer.Typer())


def test_selecting_nothing_serves_every_subapp_the_library_ships() -> None:
    """The default has to be the whole roster, or adopting the seam changes it."""
    defaults = [wired(spec.name) for spec in LIBRARY_SPECS]

    served = SubAppSelection().over(defaults, [])

    assert [entry.spec.name for entry in served] == sorted(
        spec.name for spec in LIBRARY_SPECS
    )


def test_a_retired_subapp_leaves_the_wired_roster() -> None:
    defaults = [wired(spec.name) for spec in LIBRARY_SPECS]

    served = {entry.spec.name for entry in RETIRED.over(defaults, [])}

    assert served.isdisjoint(RETIRED.retired)
    assert "dev" in served


def test_a_retired_subapp_leaves_the_documents_that_name_the_roster() -> None:
    """A page promising a command tree nothing serves is worse than no page."""
    named = {spec.name for spec in RETIRED.specs(LIBRARY_SPECS, [])}

    assert named.isdisjoint(RETIRED.retired)
    assert "dev" in named


def test_an_added_subapp_naming_a_default_replaces_it() -> None:
    """Overriding is how a project keeps its own, not retire-then-add."""
    defaults = [wired(spec.name) for spec in LIBRARY_SPECS]
    own = subapp("trace", "this project's own tracing", typer.Typer())

    served = SubAppSelection().over(defaults, [own])

    assert [entry for entry in served if entry.spec.name == "trace"] == [own]
    assert len(served) == len(LIBRARY_SPECS)


def test_both_readings_of_the_roster_name_the_same_subapps() -> None:
    """One table, two projections — a document and a CLI cannot disagree."""
    assert LIBRARY_SPECS == [entry.spec for entry in LIBRARY_ROSTER]


def test_a_retired_skill_leaves_the_roster_the_plugin_ships() -> None:
    """Named by declaration id, which prefixes what a skill and an agent share."""
    retired = ContentSelection(retired=["skill.commit"])

    kept = LIBRARY_CONTENT.selected(retired)

    assert {skill.id for skill in kept.skills}.isdisjoint(retired.retired)
    assert any(skill.id == "skill.review" for skill in kept.skills)
    assert kept.agents == LIBRARY_CONTENT.agents


def test_one_selection_reaches_agents_as_well_as_skills() -> None:
    retired = ContentSelection(retired=["agent.implementer"])

    kept = LIBRARY_CONTENT.selected(retired)

    assert {agent.id for agent in kept.agents}.isdisjoint(retired.retired)
    assert kept.skills == LIBRARY_CONTENT.skills


def test_selecting_nothing_ships_every_declaration_the_library_has() -> None:
    whole = LIBRARY_CONTENT.selected(ContentSelection())

    assert whole == LIBRARY_CONTENT


def test_extending_keeps_the_inherited_half_first() -> None:
    extended = LIBRARY_CONTENT.selected(ContentSelection()).extended([], [])

    assert extended.skills == LIBRARY_CONTENT.skills


def test_no_library_declaration_names_the_template_package() -> None:
    """A library skill must name the reading project's package, not the template's.

    The template's own package is `lup_template`, and for most of this
    library's life every declaration that needed to name an application path
    wrote that literal. It reads correctly in exactly one repository: the
    renamer rewrites imports and dotted module paths but not prose, and a
    project resolving lup from the index, from git, or from a linked checkout
    never renames the library at all. So the literal survives into every
    downstream tree and sends its reader to a directory that is not there.

    Built here under a package no checkout has, so the assertion cannot pass
    by the layout happening to match this repository's own.
    """
    declarations = [*LIBRARY_CONTENT.skills, *LIBRARY_CONTENT.agents]
    leaked = {
        declaration.id
        for declaration in declarations
        for part in declaration.prompt.parts
        if "lup_template" in (part.text_payload or "")
    }

    assert leaked == set()


def test_this_repository_declines_nothing_without_saying_so() -> None:
    """lup authors these, so retiring one would mean it should not exist."""
    assert SELECTION.retired == []
    assert {spec.name for spec in SUBAPP_SPECS} == {
        *(spec.name for spec in LIBRARY_SPECS),
        *(spec.name for spec in APPLICATION_SPECS),
    }
