"""A module: everything one subject contributes, taken or declined as a whole.

A subject reaches a project across five surfaces at once — skills and agents,
a page under ``docs/``, prose in the always-loaded document, a tool group, a
sub-app. A module is that subject as one value, so adopting it takes every
surface and declining it leaves none behind. What a project keeps of what it
took is :class:`Adoption`, resolved through the algebra :mod:`lup.seams`
already applies to the shell and edit tables.

Three properties fall out of the shape:

*Guidance is declined separately.* The always-loaded document sits under a
ceiling that truncates silently rather than failing, so prose cannot arrive as
an implication of adopting a subject — two modules taken for their tools would
spend a budget nobody was asked about. ``Adoption.guidance`` is its own
answer.

*A declined module is never built.* :class:`ModuleEntry` carries a builder, so
a module whose builder imports an optional extra costs that dependency only to
a project that has the subject.

*What one module needs from another is declared.* The resolver names
``skill.merge``, which git-workflow owns.
:class:`~lup.harness.models.Harness` refuses an invocation that resolves to
nothing, so the gap is caught either way — but it is caught at the end and it
names the skill, and an operator who declined a module is owed the answer in
the vocabulary they decided in. ``requires`` gives it, before anything builds.
"""

from collections.abc import Callable

from pydantic import BaseModel

import lup.harness.models as models
from lup.seams import SelectableRule, Selection


class ModuleSpec(SelectableRule, frozen=True):
    """What a module is called, what it is for, and whether it is taken by default.

    Separate from the module it names for the reason
    :class:`~lup.devtools.subapps.SubAppSpec` is separate from its app: prose
    listing which modules exist is generated into the harness, and a document
    that built each one to learn its name would make the listing depend on
    every optional extra the listed modules import.
    """

    id: str
    title: str
    summary: str

    default_on: bool = False
    """Whether a project that has said nothing about this module has it.

    Off for a subject most projects do not have, because the costs are
    asymmetric: a module carried by default that nobody wanted spends guidance
    budget and session context every time, and one off by default that
    somebody wants is a single line to adopt.
    """

    requires: list[str] = []
    """Modules this one's declarations reach into, by id."""

    def selection_id(self) -> str:
        return self.id


class Module(BaseModel, frozen=True):
    """One module as adopted: what it is, and everything it contributes.

    Every surface defaults to nothing, because carrying only some of them is
    the ordinary case: a module can be tools and policy with no content at
    all, or one document and one sub-app. Defaulting them lets a declaration
    say what a subject has by naming it, rather than by an emptiness a reader
    has to infer.
    """

    spec: ModuleSpec

    content: models.ContentRoster = models.ContentRoster()
    """The skills and agents this module's subject is served by."""

    guidance: list[models.GuidanceSection] = []
    """What it contributes to the always-loaded document, where one is taken."""

    documents: list[models.Document] = []
    """Pages under ``docs/`` whose subject is this module's."""

    tool_groups: list[str] = []
    """MCP tool groups served to a session while this module is adopted."""

    subapps: list[str] = []
    """Top-level CLI groups this module owns, by name.

    Top-level only: a command group nested inside another module's sub-app is
    not claimable here, so the resolver's commands under ``harness`` stay
    where they are and this names none of them. Nesting is a shape of its own
    and does not gate this one.
    """


class Adoption(BaseModel, frozen=True):
    """What one project changed about one module, surface by surface.

    Adopting a module is not all-or-nothing, and neither is any surface within
    it. A project retires one module's skill, rewrites a second module's skill
    under the same id, adds a third skill of its own beside them, drops a
    section of a fourth module's prose, and says nothing at all about the rest
    — each of those is one entry naming one thing, against a module that goes
    on growing underneath.

    Every surface carries the same algebra, so what a project learns once it
    can spell everywhere: name what you drop, declare what you have, and stay
    silent about the rest. A surface a project says nothing about is the
    module's own answer for it, including for what the module grows after that
    project last read it.
    """

    module: str
    """Which module this is about, by id."""

    taken: bool | None = None
    """Whether this project has it — ``None`` defers to the module's default."""

    content: models.ContentSelection = models.ContentSelection()
    """Which of the module's skills and agents this project ships, and its own."""

    guidance: Selection[models.GuidanceSection] = Selection()
    """Which of its sections reach the document, and what this project rewrote.

    A section declared here replaces the module's under that id and renders in
    its chapter, so a project that keeps a subject but states it differently
    edits prose rather than forking the module.
    """

    loads_guidance: bool | None = None
    """Whether its prose reaches the document at all — ``None`` takes what it has.

    The coarse answer beside the fine one, because the two questions are
    different and only one of them is about words. Guidance is paid for in
    every session whether the subject comes up or not, and a project adopting
    a module for its tools is entitled to none of its prose without listing
    the sections it is declining — a list that would go stale the moment the
    module grew one.
    """

    documents: Selection[models.Document] = Selection()
    """Which pages under ``docs/`` it publishes, by semantic id, and its own."""

    subapps: list[str] = []
    """Sub-app names from this module that its CLI does not serve."""

    tool_groups: list[str] = []
    """Tool groups from this module that its sessions are not offered.

    Retirement only, here and for ``subapps``: both are names resolved
    elsewhere rather than declarations carried here, so replacing one is
    something the module that owns it does, and adding one is something a
    project does by declaring a module of its own.
    """


class ModuleSelection(BaseModel, frozen=True):
    """Which modules a project has, and what it changed about each.

    A delta rather than a list of what is taken, so a module the library grows
    arrives under its own default instead of being absent from an enumeration
    nobody extended — the inversion every selection here takes, for the reason
    every one of them states.
    """

    adoptions: list[Adoption] = []

    def adoption(self, module_id: str) -> Adoption:
        """What this project said about one module, or that it said nothing."""
        for entry in self.adoptions:
            if entry.module == module_id:
                return entry
        return Adoption(module=module_id)

    def takes(self, spec: ModuleSpec) -> bool:
        """Whether this project has a module, deferring where it stated nothing."""
        taken = self.adoption(spec.id).taken
        return spec.default_on if taken is None else taken

    def resolved(self, module: Module) -> Module:
        """One module as this project takes it, every surface narrowed.

        Returning a module rather than a list per surface is what keeps the
        result readable: whatever walks the composition sees the same type it
        would have seen with no selection at all, and a reader asking what a
        project actually ships reads it off one value.
        """
        entry = self.adoption(module.spec.id)
        sections = [] if entry.loads_guidance is False else module.guidance
        return Module(
            spec=module.spec,
            content=module.content.selected(entry.content),
            guidance=entry.guidance.over(sections),
            documents=entry.documents.over(module.documents),
            tool_groups=[
                group for group in module.tool_groups if group not in entry.tool_groups
            ],
            subapps=[name for name in module.subapps if name not in entry.subapps],
        )


class ModuleEntry(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """One module the library ships: what it says it is, and how it is built.

    The pair is what makes the two readings one table. A roster listed in a
    document and a roster composed into a harness are the same entries seen
    through different halves of this model, so neither can name a module the
    other does not — and the builder answers only for a module somebody took.
    """

    spec: ModuleSpec
    build: Callable[[], Module]


def unmet_requirements(specs: list[ModuleSpec]) -> list[str]:
    """Every ``requires`` among these modules naming one that is not among them.

    Returned rather than raised, so the caller decides what a gap means: a
    composition refuses on it, and a listing command shows the same rows as
    something an operator is about to settle.
    """
    present = {spec.id for spec in specs}
    return [
        f"module {spec.id!r} requires {needed!r}, which this project does not take"
        for spec in specs
        for needed in spec.requires
        if needed not in present
    ]


def adopted(
    entries: list[ModuleEntry], selection: ModuleSelection | None = None
) -> list[Module]:
    """Build the modules this project takes, and only those.

    The requirement check runs before any builder, which is what keeps a
    declined subject from costing an import: a module reaching into one the
    project does not have is answered here rather than by whichever
    declaration first fails to resolve.
    """
    resolved = selection or ModuleSelection()
    taken = [entry for entry in entries if resolved.takes(entry.spec)]
    unmet = unmet_requirements([entry.spec for entry in taken])
    if unmet:
        raise ValueError("; ".join(unmet))
    return [resolved.resolved(entry.build()) for entry in taken]


def composed_content(modules: list[Module]) -> models.ContentRoster:
    """Every adopted module's roster, in module order.

    The narrowing happened where the module was resolved, so this is a
    concatenation and nothing else: a surface that had to consult the
    selection a second time would be a second place for the same decision to
    come out differently.
    """
    return models.ContentRoster(
        skills=[skill for module in modules for skill in module.content.skills],
        agents=[agent for module in modules for agent in module.content.agents],
    )


def composed_documents(modules: list[Module]) -> list[models.Document]:
    """Every page the adopted modules publish, in module order."""
    return [document for module in modules for document in module.documents]


def composed_guidance(
    modules: list[Module], chapters: list[models.GuidanceChapter] | None = None
) -> list[models.GuidanceSection]:
    """The always-loaded document, chapter by chapter and module by module.

    Reading order is the spine crossed with the module roster, and neither
    half alone will do. Ordering by module scatters a chapter across the
    document — what to run is three subjects in a row — and ordering by a
    central list of section ids puts every module the library grows through an
    edit in every project that adopts it. A section names only its chapter;
    where it sits inside one is where its module sits, which is declared
    already.
    """
    order = models.default_chapters() if chapters is None else chapters
    return [
        section
        for chapter in order
        for module in modules
        for section in module.guidance
        if section.chapter == chapter
    ]
