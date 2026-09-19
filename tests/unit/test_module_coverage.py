"""Whether every declaration this checkout holds is claimed by exactly one module.

The gate `dev check` runs, pinned here as well, for the reason the preservation
ledger is: the failure is silent and permanent. A skill no module claims still
renders into the plugin, reaches every project including the ones that declined
its subject, and never announces itself — so the only moment it can be found is
one that goes looking, and a check that runs in CI is that moment.

Two kinds of assertion. The first is over this repository, and is what actually
guards the roster. The rest are over a worked example, and pin the *shape* of
the sweep — that a file with nothing pointing at it is found, that a helper
beside it is not, and that a name two modules claim is a failure rather than a
tie broken silently.
"""

from pathlib import Path

import lup.harness.models as models
from lup.devtools.subapps import SubAppSpec
from lup.harness.coverage import (
    CONTENT_FAMILIES,
    ContentFamily,
    ContentRoot,
    ModuleCoverage,
    coverage_gaps,
    declares,
    declaring_modules,
)
from lup.harness.modules import Adoption, Module, ModuleSelection, ModuleSpec
from lup.workspace.paths import project_root
from lup_template.harness.catalog import declared_coverage

UNCLAIMED_BY_DESIGN = ["docs.rules", "docs.commands", "docs.generated-paths"]
"""The three pages no module declares, named here to say they were considered.

None of them is a declaration module and none reaches the census: the rule
reference renders from the rule registry, the command reference from the wired
CLI, and the generated-path table from the compiled trees. A project cannot
decline any of them, because none has a subject to decline.
"""


def spec(
    identity: str,
    subapps: list[str] | None = None,
    tool_groups: list[str] | None = None,
) -> ModuleSpec:
    """One module spec, carrying whichever name surfaces a case is about."""
    return ModuleSpec(
        id=identity,
        title=identity,
        summary=f"The {identity} subject.",
        subapps=subapps or [],
        tool_groups=tool_groups or [],
    )


def skill(name: str, source: str) -> models.Skill:
    """One skill declaring the module it was written in, which is the claim."""
    return models.Skill(
        id=f"skill.{name}",
        name=name,
        description="A skill declared by a worked example.",
        prompt=models.PromptDocument(
            source=source, parts=[models.TextPart(text="Do the worked example.")]
        ),
    )


def test_this_repository_leaves_no_declaration_unclaimed() -> None:
    """The assertion the gate exists for, over the roster this repository ships."""
    assert [
        gap.describe() for gap in coverage_gaps(project_root(), declared_coverage())
    ] == []


def test_every_module_the_roster_offers_is_built_for_the_sweep() -> None:
    """A module left out of the census cannot be found owning nothing."""
    coverage = declared_coverage()

    assert len(coverage.modules) == len({module.spec.id for module in coverage.modules})
    assert len(coverage.modules) > 1


def test_a_file_nothing_points_at_is_found(tmp_path: Path) -> None:
    """The failure this exists for: a declaration written and never adopted."""
    (tmp_path / "content" / "skills").mkdir(parents=True)
    (tmp_path / "content" / "skills" / "orphan.py").write_text(
        "SKILL = 1\n", encoding="utf-8"
    )
    coverage = ModuleCoverage(
        roots=[ContentRoot(directory=Path("content"), package="worked_example")]
    )

    assert [gap.name for gap in coverage_gaps(tmp_path, coverage)] == [
        "worked_example.skills.orphan"
    ]


def test_a_helper_beside_a_declaration_is_not_one(tmp_path: Path) -> None:
    """Shared prose modules cost no exception, because they declare nothing.

    This is what makes the filesystem usable as a census: the census is not
    "every file", it is "every file binding the name its family's declarations
    are bound to", so a module of reusable parts is simply not a declaration.
    """
    (tmp_path / "content" / "skills").mkdir(parents=True)
    (tmp_path / "content" / "skills" / "shared.py").write_text(
        "def shared_parts() -> list[str]:\n    return []\n", encoding="utf-8"
    )

    assert (
        declaring_modules(
            tmp_path, ContentRoot(directory=Path("content"), package="worked_example")
        )
        == []
    )


def test_a_declaration_two_modules_claim_is_a_gap(tmp_path: Path) -> None:
    """Contested is a failure, not a tie the composition breaks quietly.

    A subject claimed twice arrives twice while both modules are taken, and
    leaves half of itself behind the moment one of them goes — which reads as
    a module that partly stopped working rather than as a roster defect.
    """
    (tmp_path / "content" / "skills").mkdir(parents=True)
    (tmp_path / "content" / "skills" / "shared.py").write_text(
        "SKILL = 1\n", encoding="utf-8"
    )
    contested = skill("shared", "worked_example.skills.shared")
    coverage = ModuleCoverage(
        modules=[
            Module(
                spec=spec("alpha"), content=models.ContentRoster(skills=[contested])
            ),
            Module(spec=spec("beta"), content=models.ContentRoster(skills=[contested])),
        ],
        roots=[ContentRoot(directory=Path("content"), package="worked_example")],
    )

    assert [gap.describe() for gap in coverage_gaps(tmp_path, coverage)] == [
        "skill or agent worked_example.skills.shared is claimed by alpha, beta"
    ]


def test_a_declaration_the_project_rewrote_under_its_id_stays_claimed(
    tmp_path: Path,
) -> None:
    """A rewrite under the library's own id hides that file from the resolved view.

    The resolved module carries the project's declaration in the library's
    place, so read alone it would report the library's file as claimed by
    nobody — the shape this repository's own review skill takes. Both views
    are read, and the library's file stays the module's.
    """
    (tmp_path / "content" / "skills").mkdir(parents=True)
    (tmp_path / "content" / "skills" / "shared.py").write_text(
        "SKILL = 1\n", encoding="utf-8"
    )
    library = skill("shared", "worked_example.skills.shared")
    rewritten = skill("shared", "adopter.skills.shared")
    coverage = ModuleCoverage(
        modules=[
            Module(spec=spec("alpha"), content=models.ContentRoster(skills=[library]))
        ],
        selection=ModuleSelection(
            adoptions=[
                Adoption(
                    module="alpha",
                    content=models.ContentSelection(skills=[rewritten]),
                )
            ]
        ),
        roots=[ContentRoot(directory=Path("content"), package="worked_example")],
    )

    assert coverage_gaps(tmp_path, coverage) == []


def test_a_subapp_no_module_owns_is_a_gap(tmp_path: Path) -> None:
    """The other half of the sweep, where nothing on disk could have gone missing.

    An unclaimed sub-app does not disappear — it is served by every project
    including the ones that declined its subject, which is why it can only be
    found against the roster that serves it.
    """
    coverage = ModuleCoverage(
        modules=[Module(spec=spec("alpha", subapps=["alpha"]))],
        subapps=[
            SubAppSpec(name="alpha", help="Owned."),
            SubAppSpec(name="stray", help="Owned by nobody."),
        ],
    )

    assert [gap.describe() for gap in coverage_gaps(tmp_path, coverage)] == [
        "sub-app stray is claimed by no module"
    ]


def test_a_tool_group_no_module_owns_is_a_gap(tmp_path: Path) -> None:
    """A group every session opens because nobody said whose subject it is."""
    coverage = ModuleCoverage(
        modules=[Module(spec=spec("alpha", tool_groups=["alpha-tools"]))],
        tool_groups=["alpha-tools", "stray-tools"],
    )

    assert [gap.name for gap in coverage_gaps(tmp_path, coverage)] == ["stray-tools"]


def test_the_composition_root_may_claim_its_own_pages(tmp_path: Path) -> None:
    """The index is nobody's module, because its subject is every other module."""
    (tmp_path / "content" / "docs").mkdir(parents=True)
    (tmp_path / "content" / "docs" / "index.py").write_text(
        "def document() -> int:\n    return 1\n", encoding="utf-8"
    )
    roots = [ContentRoot(directory=Path("content"), package="worked_example")]

    assert coverage_gaps(tmp_path, ModuleCoverage(roots=roots)) != []
    assert (
        coverage_gaps(
            tmp_path,
            ModuleCoverage(roots=roots, composed=["worked_example.docs.index"]),
        )
        == []
    )


def test_each_family_knows_the_name_its_declarations_are_bound_to(
    tmp_path: Path,
) -> None:
    """Three families, three spellings, and both forms of each recognised."""
    for family in CONTENT_FAMILIES:
        for name in family.names:
            source = tmp_path / f"{family.directory}_{name}.py"
            source.write_text(f"{name} = 1\n", encoding="utf-8")

            assert declares(source, family)


def test_a_family_reads_only_its_own_name(tmp_path: Path) -> None:
    """A page module in the skills directory is not a skill."""
    source = tmp_path / "page.py"
    source.write_text("DOCUMENT = 1\n", encoding="utf-8")

    assert not declares(source, ContentFamily(directory="skills", names=["SKILL"]))
