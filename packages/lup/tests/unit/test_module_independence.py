"""Declining a module leaves every module that did not say it needed it working.

The failure this pins is the one an operator meets without having caused it:
a module is declined, and some *other* module — one the operator kept, one
that never declared needing the first — stops generating, because its content
named a skill, a command or a page the declined module contributed. Three
things answer it, and each is exercised here on a roster small enough to read:
a mention wrapped in :class:`~lup.harness.models.WhereTaken` disappears with
the module it names; an essential module cannot be declined at all; and the
gate reports every mention that is neither declared nor wrapped, naming the
module either answer needs.
"""

from pathlib import Path

import pytest

import lup.harness.models as models
from lup.harness.codescan.common import RuleSelection
from lup.harness.content.application import ApplicationLayout
from lup.harness.content.docs.catalog import page
from lup.harness.content.modules.catalog import library_modules
from lup.harness.content.modules.specs import LIBRARY_SPECS
from lup.harness.dependencies import reaches
from lup.harness.modules import (
    Adoption,
    Composition,
    DocumentContext,
    Module,
    ModuleEntry,
    ModuleSelection,
    ModuleSpec,
    adopted,
    anchored,
    scaffold_selection,
    standing,
)
from lup.harness.requirements import LostCapability, Manifest, Requirement, Run
from lup.devtools.roster import LIBRARY_SPECS as LIBRARY_SUBAPPS
from lup.providers.harness import claude_prompt_renderer, codex_prompt_renderer
from lup.workspace.paths import project_root

RENDERERS = [claude_prompt_renderer(), codex_prompt_renderer()]

BASE = ModuleSpec(id="base", title="Base", summary="Always here.", essential=True)
LOOP = ModuleSpec(
    id="loop",
    title="Loop",
    summary="Commits things.",
    default_on=True,
    subapps=["loop"],
    tool_groups=["loop-tools"],
    requirements=["container runtime"],
)
USER = ModuleSpec(id="user", title="User", summary="Names the loop.", default_on=True)
NEEDY = ModuleSpec(
    id="needy",
    title="Needy",
    summary="Cannot work without the loop.",
    default_on=True,
    requires=["loop"],
)


def skill(name: str, parts: list[models.PromptPart]) -> models.Skill:
    """One skill whose whole prompt is *parts*."""
    return models.Skill(
        id=f"skill.{name}",
        name=name,
        description=f"The {name} skill.",
        prompt=models.PromptDocument(source=__name__, parts=parts),
    )


COMMIT = skill("commit", [models.TextPart(text="Commit what is staged.")])

POINTER = skill(
    "pointer",
    [
        models.TextPart(text="Do the work."),
        models.WhereTaken(
            module="loop",
            parts=[
                models.TextPart(text=" Then run "),
                models.SkillInvocation(plugin="lup", skill="commit"),
                models.TextPart(text="."),
            ],
        ),
    ],
)
"""A mention of the loop's skill that exists only where the loop is taken."""

BARE = skill(
    "bare",
    [
        models.TextPart(text="Then run "),
        models.SkillInvocation(plugin="lup", skill="commit"),
        models.TextPart(text=" and `uv run lup-devtools loop status`."),
    ],
)
"""The same mention with nothing saying so: the defect the gate exists for."""


def modules(user: list[models.Skill]) -> list[Module]:
    """The small roster: an essential base, the loop, and a module naming it."""
    return [
        Module(spec=BASE),
        Module(spec=LOOP, content=models.ContentRoster(skills=[COMMIT])),
        Module(spec=USER, content=models.ContentRoster(skills=user)),
        Module(spec=NEEDY, content=models.ContentRoster(skills=[BARE])),
    ]


def entries(user: list[models.Skill]) -> list[ModuleEntry]:
    """The same roster, each module behind a builder the way a catalog holds it."""
    return [
        ModuleEntry(spec=module.spec, build=lambda held=module: held)
        for module in modules(user)
    ]


def declining(*ids: str) -> ModuleSelection:
    """A selection declining *ids* and saying nothing about the rest."""
    return ModuleSelection(adoptions=[Adoption(module=id, taken=False) for id in ids])


def invoked(roster: list[Module]) -> list[str]:
    """Every skill any skill in *roster* invokes."""
    return [
        issued.skill
        for module in roster
        for declared in module.content.skills
        for part in declared.prompt.walked()
        if (issued := part.invocation) is not None
    ]


def test_a_wrapped_mention_is_kept_where_its_module_is_taken() -> None:
    kept = adopted(entries([POINTER]), ModuleSelection())

    assert "commit" in invoked([module for module in kept if module.spec.id == "user"])
    rendered = claude_prompt_renderer().render(
        next(module for module in kept if module.spec.id == "user")
        .content.skills[0]
        .prompt
    )
    assert "Then run" in rendered


def test_a_wrapped_mention_leaves_with_the_module_it_names() -> None:
    """Declining the loop takes its sentence out of a module that kept going."""
    kept = adopted(entries([POINTER]), declining("loop", "needy"))

    user = next(module for module in kept if module.spec.id == "user")
    assert invoked([user]) == []
    assert claude_prompt_renderer().render(user.content.skills[0].prompt) == (
        "Do the work.\n"
    )


def test_a_module_declaring_its_need_goes_when_what_it_needs_goes() -> None:
    with pytest.raises(ValueError, match="'needy' requires 'loop'"):
        adopted(entries([POINTER]), declining("loop"))


def test_an_essential_module_cannot_be_declined() -> None:
    """Honouring the decline would break every module at once, so it is refused."""
    with pytest.raises(ValueError, match="'base' is essential"):
        adopted(entries([POINTER]), declining("base"))


def test_a_module_stands_on_what_it_requires_and_on_every_essential_one() -> None:
    specs = [BASE, LOOP, USER, NEEDY]

    assert anchored(specs) == ["base"]
    assert standing("user", specs) == ["user", "base"]
    assert standing("needy", specs) == ["needy", "base", "loop"]


def test_the_gate_reports_a_mention_nobody_declared() -> None:
    found = reaches(modules([BARE]), RENDERERS)

    assert {(reach.module, reach.named.kind, reach.named.name) for reach in found} == {
        ("user", "skill", "commit"),
        ("user", "command", "loop"),
    }
    assert all(reach.owner == "loop" for reach in found)
    assert "WhereTaken(module='loop')" in found[0].describe()


def test_the_gate_accepts_a_wrapped_mention_and_a_declared_one() -> None:
    """`needy` names the loop bare and says it needs it; `user` wraps its mention."""
    assert reaches(modules([POINTER]), RENDERERS) == []


def test_a_page_is_read_against_what_its_own_module_stands_on() -> None:
    """A page listing the roster names only what its module could hold.

    Read against the whole composition, a page describing every skill would
    report each one as a reach; read against the modules its own module
    stands on, it lists what that project would have, which names nothing
    outside it.
    """

    def roster_page(context: DocumentContext) -> models.PromptDocument:
        return models.PromptDocument(
            source=__name__,
            parts=[
                models.SkillInvocation(plugin="lup", skill=declared.name)
                for declared in context.skills
            ],
        )

    listing = Module(
        spec=USER,
        documents=[page("listing", "listing.md", roster_page)],
    )
    roster = [*modules([]), listing]
    context = DocumentContext(
        layout=ApplicationLayout(package="worked_example"),
        root=Path("."),
        skills=[COMMIT, BARE],
    )

    assert [
        reach for reach in reaches(roster, RENDERERS, context) if reach.module == "user"
    ] == []


def test_a_requirement_only_a_declined_module_claims_is_not_asked_for() -> None:
    """Declining the sandbox should cost a machine nothing it only needed for it."""
    container = Requirement(
        capability="container runtime",
        purpose="the loop's containers",
        exercise=Run(command=["docker", "info"]),
        absence=LostCapability(capability="the loop"),
    )
    git = container.model_copy(update={"capability": "git", "purpose": "history"})
    manifest = Manifest(requirements=[git, container])
    specs = [BASE, LOOP, USER, NEEDY]

    kept = ModuleSelection().requirements(manifest, specs)
    narrowed = declining("loop", "needy").requirements(manifest, specs)

    assert [item.capability for item in kept.requirements] == [
        "git",
        "container runtime",
    ]
    assert [item.capability for item in narrowed.requirements] == ["git"]


def test_a_declined_modules_tool_group_is_withheld() -> None:
    specs = [BASE, LOOP, USER, NEEDY]

    assert ModuleSelection().withheld_tool_groups(specs) == []
    assert declining("loop", "needy").withheld_tool_groups(specs) == ["loop-tools"]


def test_a_composition_is_every_surface_read_off_one_selection() -> None:
    composed = Composition.of(entries([POINTER]), declining("loop", "needy"))

    assert composed.taken() == ["base", "user"]
    assert composed.subapps() == []
    assert composed.withheld_tool_groups() == ["loop-tools"]
    assert [declared.name for declared in composed.content().skills] == ["pointer"]


def test_lups_own_roster_reaches_only_what_it_stands_on() -> None:
    """Every library module, read without the application composing it.

    The library half of the gate `dev check` runs over the whole roster: a
    module lup ships that named another lup module without standing on it
    would break every adopter declining the second, and none of them could
    edit the prose that did it.
    """
    layout = ApplicationLayout(package="worked_example")
    library = [entry.build() for entry in library_modules(layout, RuleSelection())]
    content = Composition.of(
        library_modules(layout, RuleSelection()), scaffold_selection(LIBRARY_SPECS)
    ).content()
    context = DocumentContext(
        layout=layout,
        root=project_root(),
        skills=content.skills,
        agents=content.agents,
        subapps=LIBRARY_SUBAPPS,
        library_checkout=project_root(),
    )

    found = reaches(library, RENDERERS, context)

    assert [reach.describe() for reach in found] == []
