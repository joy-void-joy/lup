"""What an application tells the shared development tooling about itself.

The commands under :mod:`lup.devtools` are workflow rather than domain: they
scan, check, and generate against whichever repository they are pointed at.
A few facts about that repository are not theirs to infer — the import root
the application publishes, which initialization renames, and the roots whose
contents answer to some purpose other than production. Reaching back for
those by name is what kept these commands in an application package; taking
them as a declaration is what lets any adopter supply its own.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from lup.harness.codescan.boundaries import ApplicationRoots
from lup.harness.codescan.common import AntiPattern, RuleSelection
from lup.devtools.dev.seams import DECLARED_SEAMS, Seam
from lup.devtools.subapps import SubAppSelection
from lup.harness.coverage import ModuleCoverage
from lup.harness.models import GuidanceSection
from lup.harness.modules import ModuleSelection
from lup.policy.kernel.rows import PathRoleRow


class Tracker(BaseModel, frozen=True):
    """One repository beyond this checkout that this project may report to.

    A project consuming lup as a dependency hits most of its friction in
    machinery it cannot edit -- the resolver, the permission policy, the
    sandbox -- and a report filed where the session happened to be standing
    lands on the wrong tracker. Worse than misfiled: the resolver's intake
    takes every open issue in the checkout's repository, so a misfiled
    upstream defect becomes evidence for the next downstream run, which plans
    a repair to code that is not in the tree.

    Declared rather than discovered, and the discovery worth naming is the
    one not taken: `origin` says where this checkout came from and nothing
    says where its dependencies' defects belong. Reading a remote named
    `upstream` would work in the checkouts whose owner spells it that way and
    reach somewhere else in the ones that do not, which is one command
    meaning two things.

    Nothing here is compiled into a generated tree. This is a list of
    repositories a devtools command may name, read when the command runs, and
    an entry going stale costs a failed `gh` call rather than a permission
    that decided wrongly in silence.
    """

    repository: str = Field(
        min_length=1,
        description=(
            "Where reports go, as `owner/name` or `host/owner/name`. Write "
            "the host when this project reaches two forges — an enterprise "
            "one beside the public one carries the same owner and name for a "
            "different repository, and the host is what tells them apart. "
            "Written as a bare pair, any host answering to that pair is "
            "reachable, which is what a single-forge project means"
        ),
    )
    what: str = Field(
        min_length=1,
        description=(
            "Why this project may report there, in a few words. Read by "
            "whoever meets the refusal for a repository that is not listed, "
            "so it says what the tracker is for rather than naming it twice"
        ),
    )
    components: list[str] = Field(
        default=[],
        description=(
            "Owning-component prefixes this tracker answers for, matched "
            "against what a report names as its component -- `lup/policy` "
            "and `lup.resolver.state` both answer to `lup`. Empty claims no "
            "component, which leaves the tracker reachable by name and never "
            "chosen automatically"
        ),
    )

    def claims(self, component: str) -> bool:
        """Whether a report's owning component belongs to this tracker.

        A prefix claims what continues it at a word boundary rather than
        whatever merely starts with it: `lup` answers for `lup/policy`,
        `lup.resolver.state` and `lup-devtools`, and never for `lupine`.
        Stated as "what follows is not part of a word" rather than as a list
        of separators, because the separator is whatever the reporter typed
        and a list of those is a list somebody has to keep.
        """
        named = component.casefold()

        def continues(prefix: str) -> bool:
            following = named[len(prefix) :][:1]
            return named.startswith(prefix) and not (
                following.isalnum() or following == "_"
            )

        return any(continues(word.casefold()) for word in self.components)


class DevProject(BaseModel, frozen=True):
    """The repository facts shared development tooling cannot work out alone."""

    package: str
    """The import root this application publishes.

    Only the application knows it: initialization renames the package, so a
    value written down in the library would go on naming one that is gone
    and silently resolve nothing.
    """

    path_roles: list[PathRoleRow] = []
    """Roots whose contents are judged by a purpose other than production.

    Test and data roots are judged by behaviour and retained evidence rather
    than by production's conventions, so a scan that read them all the same
    way would report fixtures and generated research payloads as defects.
    """

    rules: RuleSelection = RuleSelection()
    """Which of the library's scan rules this repository holds itself to.

    Carried here so the sweep reads the selection the edit hook was compiled
    with: an application declares it once on its ``HookSet`` and hands it
    over, the way it already hands over its path roles.
    """

    anti_patterns: list[AntiPattern] = []
    """Code shapes only this repository refuses, beside the library's own.

    Carried here for the reason the selection is: the sweep and the edit hook
    have to read one table. A rule declared on the ``HookSet`` and not handed
    over would be enforced on every edit and invisible to ``dev check``, which
    is the disagreement the selection already exists to prevent.
    """

    subapps: SubAppSelection = SubAppSelection()
    """Which of the library's sub-apps this repository's CLI serves."""

    trackers: list[Tracker] = []
    """Repositories beyond this checkout that this project may report to.

    Empty is the shipped answer and a real one: a project whose defects are
    all its own reaches its own tracker and nothing else, which is what
    `origin` already says. A project built on a dependency it cannot edit
    names that dependency's tracker here, and `dev tracker` will reach it.

    The list is what a refusal reads out, so it doubles as the answer to
    "where else may this go?" -- a question nobody can answer from a denial
    that only says no.
    """

    modules: ModuleSelection = ModuleSelection()
    """Which of the library's modules this project takes, and what it changed.

    Carried beside the other two because every one of them is the same kind of
    fact — something this repository declined that the library still ships —
    and the gate reports them together. A retirement nobody can see becomes
    permanent by default: the roster it was taken from goes on growing, and
    the project that opted out once never meets the decision again.

    A module rather than a skill, because a subject declined at one surface and
    kept at four is the failure this replaced: the skills went and the page,
    the sub-app, the tool group and the paragraph stayed, each looking like a
    decision somebody made."""

    declined_guidance: list[GuidanceSection] = []
    """Prose this project's modules offer that its own document does not carry.

    The other half of what the guidance budget has to know. This repository's
    document is one composition of the roster and the lightest interesting one,
    because a scaffold takes every module and loads the prose of only the ones
    it offers — so weighing it answers what *this* tree costs and says nothing
    about the ceiling an adopter is bounded by. These are the sections between
    the two: what the same roster weighs with every module's prose loaded is
    this plus what the tree already carries, and that is the number a module
    growing a paragraph has to stay under.
    """

    coverage: ModuleCoverage = ModuleCoverage()
    """Everything this checkout declares, beside the modules that could claim it.

    Empty is a real answer and a weak one: a project declaring nothing here has
    a roster nothing audits, which is safe exactly as long as every subject
    happens to be claimed. Filling it in costs four facts the composition root
    already holds, and buys the one failure the module system cannot see from
    inside itself — a declaration owned by nothing, which reaches every project
    including the ones that declined its subject and says nothing while it does.
    """

    roots: ApplicationRoots = ApplicationRoots()
    """Where this application is allowed to name a concrete implementation.

    The seam guard reads it to tell a composition root — which may say
    ``ClaudeSpellings`` because choosing is its whole job — from a module
    that reached past the abstraction it was handed.
    """

    catalog: Path | None = None
    """Where this repository writes down what it settled about itself.

    Named rather than derived, because the layout is the application's and a
    library guessing at one would report the wrong file as unanswered.
    Declaring none is a real answer — a project curating its declarations by
    hand needs no surface over them — and the seam command says so rather
    than reading somewhere it was never pointed.
    """

    seams: list[Seam] = DECLARED_SEAMS
    """Which declarations this project is asked about, and where each is written.

    The library's list as an overridable default, which is what that list
    already said it was. A domain with a seam of its own extends this rather
    than forking it — and a seam living outside the catalog is why it has to
    be declared here: where an application keeps a declaration is the
    application's business, and a library naming one of its paths has reached
    into it.
    """
