"""What a project can say about a module, and what a module costs when declined.

Adoption is not all-or-nothing at either level. A project takes some modules
and not others; within a module it takes some skills, replaces one, adds its
own, drops a section of prose, and says nothing about the rest. These pin that
every surface answers to the same algebra, that silence inherits, and that a
module nobody took is never built.
"""

from pathlib import Path

import pytest

import lup.harness.models as models
import lup.harness.modules as modules
from lup.harness.content.application import ApplicationLayout
from lup.seams import Selection


def skill(identity: str, name: str, words: str = "Do the thing.") -> models.Skill:
    """One skill, spelled as briefly as a declaration can be."""
    return models.Skill(
        id=identity,
        name=name,
        description="A worked-example skill.",
        prompt=models.PromptDocument(
            source=__name__, parts=[models.TextPart(text=words)]
        ),
    )


def section(identity: str, chapter: models.GuidanceChapter) -> models.GuidanceSection:
    """One guidance section carrying enough prose to tell it from another."""
    return models.GuidanceSection(
        id=identity,
        chapter=chapter,
        parts=[models.TextPart(text=f"## {identity}\n")],
    )


def page(semantic_id: str) -> modules.DocumentEntry:
    """One published page, named by the id ownership records it under."""
    return modules.DocumentEntry(
        semantic_id=semantic_id,
        source=f"worked_example.docs.{semantic_id}",
        build=lambda _: models.Document(
            path=Path("docs") / f"{semantic_id}.md",
            semantic_id=semantic_id,
            source="tmp/worked_example.py",
            document=models.PromptDocument(
                source=__name__, parts=[models.TextPart(text="A page.\n")]
            ),
        ),
    )


CONTEXT = modules.DocumentContext(
    layout=ApplicationLayout(package="worked_example"), root=Path("/worked-example")
)
"""What a page is rendered against, where no page here reads any of it."""


ALPHA_SPEC = modules.ModuleSpec(
    id="alpha",
    title="Alpha",
    summary="The first subject.",
    default_on=True,
    subapps=["alpha"],
    tool_groups=["alpha-tools"],
)

ALPHA = modules.Module(
    spec=ALPHA_SPEC,
    content=models.ContentRoster(
        skills=[skill("skill.a1", "a1"), skill("skill.a2", "a2")]
    ),
    guidance=[section("alpha-code", "code"), section("alpha-process", "process")],
    documents=[page("docs.alpha")],
)

BETA = modules.Module(
    spec=modules.ModuleSpec(
        id="beta", title="Beta", summary="The second subject.", default_on=True
    ),
    content=models.ContentRoster(
        skills=[skill("skill.b1", "b1"), skill("skill.b2", "b2")]
    ),
    guidance=[section("beta-tooling", "tooling")],
)

GAMMA = modules.Module(
    spec=modules.ModuleSpec(
        id="gamma", title="Gamma", summary="A subject most projects lack."
    ),
    content=models.ContentRoster(skills=[skill("skill.g1", "g1")]),
)

ENTRIES = [
    modules.ModuleEntry(spec=ALPHA.spec, build=lambda: ALPHA),
    modules.ModuleEntry(spec=BETA.spec, build=lambda: BETA),
    modules.ModuleEntry(spec=GAMMA.spec, build=lambda: GAMMA),
]


def skill_ids(roster: models.ContentRoster) -> list[str]:
    return [declaration.id for declaration in roster.skills]


def test_silence_takes_each_modules_own_default() -> None:
    """A project that has said nothing is not a project that declined."""
    taken = modules.adopted(ENTRIES)

    assert [module.spec.id for module in taken] == ["alpha", "beta"]


def test_a_module_off_by_default_is_taken_by_saying_so() -> None:
    taken = modules.adopted(
        ENTRIES,
        modules.ModuleSelection(
            adoptions=[modules.Adoption(module="gamma", taken=True)]
        ),
    )

    assert [module.spec.id for module in taken] == ["alpha", "beta", "gamma"]


def test_a_declined_module_is_never_built() -> None:
    """The builder may import an extra, so a declined subject must not run one."""

    def refuse() -> modules.Module:
        raise AssertionError("a declined module was built")

    entries = [
        *ENTRIES,
        modules.ModuleEntry(
            spec=modules.ModuleSpec(id="delta", title="Delta", summary="Costly."),
            build=refuse,
        ),
    ]

    assert [module.spec.id for module in modules.adopted(entries)] == ["alpha", "beta"]


def test_one_project_retires_replaces_and_adds_across_modules() -> None:
    """The whole point of the shape, stated in one declaration.

    Alpha loses a skill, beta's second is rewritten under its own id, a third
    arrives beside it, and nothing else is mentioned — including gamma, which
    keeps its own default of being absent.
    """
    mine = skill("skill.b2", "b2", "Do it this way instead.")
    added = skill("skill.b3", "b3")

    taken = modules.adopted(
        ENTRIES,
        modules.ModuleSelection(
            adoptions=[
                modules.Adoption(
                    module="alpha",
                    content=models.ContentSelection(retired=["skill.a1"]),
                ),
                modules.Adoption(
                    module="beta",
                    content=models.ContentSelection(skills=[mine, added]),
                ),
            ]
        ),
    )

    assert skill_ids(modules.composed_content(taken)) == [
        "skill.a2",
        "skill.b1",
        "skill.b2",
        "skill.b3",
    ]
    resolved = modules.composed_content(taken)
    assert [one for one in resolved.skills if one.id == "skill.b2"] == [mine]


def test_a_section_of_one_modules_prose_is_dropped_on_its_own() -> None:
    """Guidance narrows by section, the way content narrows by declaration."""
    taken = modules.adopted(
        ENTRIES,
        modules.ModuleSelection(
            adoptions=[
                modules.Adoption(
                    module="alpha", guidance=Selection(retired=["alpha-process"])
                )
            ]
        ),
    )

    assert [one.id for one in modules.composed_guidance(taken)] == [
        "alpha-code",
        "beta-tooling",
    ]


def test_a_project_rewrites_one_section_and_keeps_its_chapter() -> None:
    mine = models.GuidanceSection(
        id="alpha-code",
        chapter="code",
        parts=[models.TextPart(text="## Our own words\n")],
    )

    taken = modules.adopted(
        ENTRIES,
        modules.ModuleSelection(
            adoptions=[
                modules.Adoption(module="alpha", guidance=Selection(overrides=[mine]))
            ]
        ),
    )

    assert modules.composed_guidance(taken)[0] == mine


def test_a_module_can_be_taken_for_its_tools_and_none_of_its_prose() -> None:
    """The budget answer, which listing every section would not survive.

    Guidance is spent in every session whether the subject comes up or not, so
    declining it is one word — and a module that grows a section afterwards
    does not quietly reintroduce the cost.

    The module keeps its sections through resolution and falls silent where the
    document is composed, which is what lets the budget ask what a project
    turning it back on would carry: the prose is not gone, it is unspent.
    """
    selection = modules.ModuleSelection(
        adoptions=[modules.Adoption(module="alpha", loads_guidance=False)]
    )
    taken = modules.adopted(ENTRIES, selection)

    assert [one.id for one in modules.composed_guidance(taken, selection)] == [
        "beta-tooling"
    ]
    assert [one.id for one in modules.unloaded_guidance(taken, selection)] == [
        "alpha-code",
        "alpha-process",
    ]
    assert skill_ids(modules.composed_content(taken)) == [
        "skill.a1",
        "skill.a2",
        "skill.b1",
        "skill.b2",
    ]


def test_documents_subapps_and_tool_groups_each_narrow_on_their_own() -> None:
    """The three surfaces answer separately, two of them without building.

    Sub-apps and tool groups are names on the spec, so they narrow against the
    selection alone — which is the property the CLI depends on: it has to know
    which command trees it serves before it composes them.
    """
    selection = modules.ModuleSelection(
        adoptions=[
            modules.Adoption(
                module="alpha",
                documents=Selection(retired=["docs.alpha"]),
                subapps=["alpha"],
                tool_groups=["alpha-tools"],
            )
        ]
    )
    taken = modules.adopted(ENTRIES, selection)

    assert modules.composed_documents(taken, CONTEXT) == []
    assert selection.subapps([ALPHA_SPEC]) == []
    assert selection.tool_groups([ALPHA_SPEC]) == []


def test_the_spine_orders_the_document_across_modules() -> None:
    """Chapter first, module second — so a chapter is not scattered by owner."""
    taken = modules.adopted(ENTRIES)

    assert [one.id for one in modules.composed_guidance(taken)] == [
        "alpha-code",
        "beta-tooling",
        "alpha-process",
    ]


def test_a_project_that_disagrees_with_the_spine_says_so_once() -> None:
    reordered = modules.composed_guidance(
        modules.adopted(ENTRIES), chapters=["process", "tooling", "code"]
    )

    assert [one.id for one in reordered] == [
        "alpha-process",
        "beta-tooling",
        "alpha-code",
    ]


def test_taking_a_module_without_what_it_reaches_into_is_refused() -> None:
    """Named in the vocabulary the decision was made in, before anything builds.

    A skill invocation that resolves to nothing is refused when the harness is
    assembled, so the gap never ships either way. What this answers is *which
    module* the operator turned off, which the later diagnostic cannot say.
    """
    entries = [
        *ENTRIES,
        modules.ModuleEntry(
            spec=modules.ModuleSpec(
                id="epsilon",
                title="Epsilon",
                summary="Reaches into a subject it does not own.",
                default_on=True,
                requires=["gamma"],
            ),
            build=lambda: modules.Module(
                spec=modules.ModuleSpec(
                    id="epsilon", title="Epsilon", summary="", requires=["gamma"]
                )
            ),
        ),
    ]

    with pytest.raises(ValueError, match="requires 'gamma'"):
        modules.adopted(entries)


def test_a_requirement_a_project_took_is_met() -> None:
    entries = [
        *ENTRIES,
        modules.ModuleEntry(
            spec=modules.ModuleSpec(
                id="epsilon",
                title="Epsilon",
                summary="Reaches into a subject it does not own.",
                default_on=True,
                requires=["gamma"],
            ),
            build=lambda: modules.Module(
                spec=modules.ModuleSpec(
                    id="epsilon", title="Epsilon", summary="", requires=["gamma"]
                )
            ),
        ),
    ]

    taken = modules.adopted(
        entries,
        modules.ModuleSelection(
            adoptions=[modules.Adoption(module="gamma", taken=True)]
        ),
    )

    assert "epsilon" in [module.spec.id for module in taken]
