"""Whether every declaration a checkout holds is claimed by exactly one module.

A module is one subject as one value, and everything downstream rests on that
being true of the *whole* checkout. It fails silently in both directions: a
skill no module names still renders into the plugin and reaches every project
including the ones that declined its subject, and a subject two modules claim
arrives twice or leaves half of itself behind when one of them is dropped.
Nobody meets either — there is no moment at which a declaration owned by
nothing announces itself.

So this walks what the checkout declares and asks which module claims it. The
census is the filesystem rather than a second roster, because a second roster
is precisely what would go stale: a skill file added and never adopted is what
this exists to find, and a list somebody had to extend to find it would have
been extended when the skill was written. A module under ``skills/``,
``agents/`` or ``docs/`` is a declaration when it binds the name its family's
declarations are bound to, and a helper when it does not — which is why the
shared prose modules sitting beside them cost no exception.

Sub-apps and tool groups are swept the other way round, against the rosters
that serve them, and they are not content families however much they look like
a third and fourth one. A family is a *directory of declaration modules*, and
those two have none: a sub-app is a name in :data:`~lup.devtools.roster.
LIBRARY_ROSTER` and a tool group a name in the toolset factory, so there is no
file that could sit unclaimed. The failure is the opposite shape — an unclaimed
name does not go missing, it is served by every project including the ones that
declined its subject — and it is only findable against the roster that serves
it. One question, two censuses, because the surfaces differ in what can go
wrong: a file can exist with nothing pointing at it, and a name cannot.
"""

import ast
from pathlib import Path

from pydantic import BaseModel

from lup.devtools.subapps import SubAppSpec
from lup.harness.modules import Module


class ContentFamily(BaseModel, frozen=True):
    """One directory of declaration modules, and how one says it holds a declaration.

    Content only. Sub-apps and tool groups reach a project through a module
    too, but neither has a directory of files behind it — so neither is a
    family here, and both are swept against the roster that serves them
    instead.

    Two spellings per family, because a declaration naming a path inside the
    reading project's own package has to be built against a layout while one
    that names none is the value itself — the difference between ``SKILL`` and
    ``skill`` throughout the content tree.
    """

    directory: str
    names: list[str]


CONTENT_FAMILIES = [
    ContentFamily(directory="skills", names=["SKILL", "skill"]),
    ContentFamily(directory="agents", names=["AGENT", "agent"]),
    ContentFamily(directory="docs", names=["DOCUMENT", "document"]),
]
"""How each content family spells the thing a module in it declares.

A default rather than a fixture: this is the library's own naming convention,
and a project laying its content out differently passes its own.
"""


class ContentRoot(BaseModel, frozen=True):
    """One half's declaration tree: where its files sit, and what they import as.

    Both, because the sweep walks files and every claim names a module. A
    prompt records the module it was written in, since that is what
    ``__name__`` gives it, and a page is declared to record the same — so the
    census turns each file it finds into the name a claim would use, and
    nothing has to be taken back apart afterwards.
    """

    directory: Path
    """Where the tree is, relative to the checkout being swept."""

    package: str
    """The dotted prefix a module in it is imported under."""


class Claim(BaseModel, frozen=True):
    """One module saying that one declaration is its subject's."""

    declaration: str
    """What is claimed, spelled the way the census spells it."""

    module: str
    """Which module claims it, by id."""


class CoverageGap(BaseModel, frozen=True):
    """One declaration that no module claims, or that more than one does."""

    surface: str
    """Which kind of thing this is — a skill, a page, a sub-app, a tool group."""

    name: str
    """What it is called, spelled the way whoever looks for it would."""

    owners: list[str] = []
    """The modules claiming it, by id. Empty is the failure this mostly finds."""

    def describe(self) -> str:
        """One line, saying what is wrong rather than that something is."""
        if not self.owners:
            return f"{self.surface} {self.name} is claimed by no module"
        return f"{self.surface} {self.name} is claimed by {', '.join(self.owners)}"


class ModuleCoverage(BaseModel, frozen=True):
    """Everything a checkout declares, beside the modules that could claim it.

    Handed over by the composition root rather than found, because only the
    root knows all of it: which trees hold this project's declarations, which
    command trees its CLI could mount, which tool groups its sessions could
    open. Every one of those it already holds for another reason.
    """

    modules: list[Module] = []
    """Every module in the roster, built — not the adopted subset.

    A module a project declined still owns its declarations, and one that owns
    none is exactly what this looks for, so narrowing first would hide the
    failure. Building them all costs the imports the roster reaches, which is a
    cost only this gate pays and only while it runs.
    """

    roots: list[ContentRoot] = []
    """The declaration trees this checkout actually holds."""

    composed: list[str] = []
    """Declaration modules the composition root publishes itself, dotted.

    The index is the whole of it and cannot be otherwise: its subject is what
    every other module contributed, so no module can see enough to declare it.
    A root publishing something else of its own names it here.
    """

    subapps: list[SubAppSpec] = []
    """Every sub-app this project's CLI could mount, whichever it serves."""

    tool_groups: list[str] = []
    """Every tool group this project's sessions could open, whichever they do."""


def bound(node: ast.stmt) -> str:
    """The top-level name one statement binds, or nothing where it binds none."""
    match node:
        case ast.Assign(targets=[ast.Name(id=name)]):
            return name
        case ast.AnnAssign(target=ast.Name(id=name)):
            return name
        case ast.FunctionDef(name=name):
            return name
        case _:
            return ""


def declares(source: Path, family: ContentFamily) -> bool:
    """Whether one module binds a name its family's declarations are bound to.

    Read from the source rather than by importing it: the sweep runs over every
    file in the tree, and importing them all would pull in every optional extra
    the roster reaches in order to find out that a file declares nothing.
    """
    return any(
        bound(node) in family.names
        for node in ast.parse(source.read_text(encoding="utf-8")).body
    )


def declaring_modules(
    root: Path, content: ContentRoot, families: list[ContentFamily] | None = None
) -> list[str]:
    """Every declaration module beneath one content root, by dotted name."""
    return [
        f"{content.package}.{family.directory}.{source.stem}"
        for family in families or CONTENT_FAMILIES
        for source in sorted((root / content.directory / family.directory).glob("*.py"))
        if source.stem != "__init__" and declares(source, family)
    ]


def content_claims(modules: list[Module]) -> list[Claim]:
    """Which module claims which skill or agent module.

    Every prompt carries the module it was written in, so ownership is read off
    the declarations themselves rather than off a table pairing them with
    modules — the pairing is the import each module already wrote down.
    """
    return [
        Claim(declaration=prompt.declared_source(), module=module.spec.id)
        for module in modules
        for prompt in (
            *(skill.prompt for skill in module.content.skills),
            *(agent.prompt for agent in module.content.agents),
        )
    ]


def page_claims(modules: list[Module]) -> list[Claim]:
    """Which module publishes which page module, without rendering a page.

    A page entry carries where it is declared for exactly this reason: knowing
    who publishes it must not require the context that renders it.
    """
    return [
        Claim(declaration=entry.source, module=module.spec.id)
        for module in modules
        for entry in module.documents
    ]


def subapp_claims(modules: list[Module]) -> list[Claim]:
    """Which module owns which top-level command tree."""
    return [
        Claim(declaration=name, module=module.spec.id)
        for module in modules
        for name in module.spec.subapps
    ]


def tool_group_claims(modules: list[Module]) -> list[Claim]:
    """Which module owns which MCP tool group."""
    return [
        Claim(declaration=name, module=module.spec.id)
        for module in modules
        for name in module.spec.tool_groups
    ]


def gaps(surface: str, declared: list[str], claims: list[Claim]) -> list[CoverageGap]:
    """Every declared name no module claims, or that more than one claims."""
    return [
        CoverageGap(surface=surface, name=name, owners=holders)
        for name in declared
        if len(
            holders := list(
                dict.fromkeys(
                    claim.module for claim in claims if claim.declaration == name
                )
            )
        )
        != 1
    ]


def coverage_gaps(root: Path, coverage: ModuleCoverage) -> list[CoverageGap]:
    """Every declaration in this checkout that no module claims, or that two do.

    Content and pages are swept against the filesystem; sub-apps and tool groups
    against the rosters that serve them. The two halves ask one question of
    different censuses because the surfaces differ in what can go missing: a
    file can sit in the tree with nothing pointing at it, and a name cannot.
    """
    declared = [
        name
        for entry in coverage.roots
        for name in declaring_modules(root, entry)
        if name not in coverage.composed
    ]
    pages = [name for name in declared if ".docs." in name]
    return [
        *gaps(
            "skill or agent",
            [name for name in declared if name not in pages],
            content_claims(coverage.modules),
        ),
        *gaps("page", pages, page_claims(coverage.modules)),
        *gaps(
            "sub-app",
            [spec.name for spec in coverage.subapps],
            subapp_claims(coverage.modules),
        ),
        *gaps("tool group", coverage.tool_groups, tool_group_claims(coverage.modules)),
    ]
