"""A declaration resolved: each kind's entries, from the modules it selects.

Resolving applies every layer in order, then reads each kind from the modules that
hold it, by the kind's type (`docs/declaration.md`, *Resolving it*):
- `Core` is held, and every module a selected module requires is selected,
  without a cycle; lup never adds or drops a module behind the project's back;
- names are per kind and shared across modules, so one name from two modules
  fails, naming both, but for a path pattern, which from two modules is one
  pattern, a package, which from two modules or a requirement is one package, a
  related repository, which from two modules is one where both give it one path,
  a requirement, which is checked for each module needing it, and an exemption,
  which each module keeps for its own paths;
- entries placed `before=` or `after=` another go there, whichever module holds
  it, and the rest keep the order of their modules;
- each module's classes of methods (`Serving`) are made with that module, so
  each must narrow `module` to its class; a tool's name and a request's kind
  are shared across modules, so one from two modules fails, naming both;
- the runner comes from the one module holding one, `Plain()` where none does,
  the session settings from the one holding them, `Core`, with the fields the
  declaration set, which a launch imposes over the person's own, and the limits
  on the operator's credentials from the one holding them, `Core` too;
- the package age is `Core`'s own field, read from it by name, since a
  duration isn't a kind: another module's `timedelta` would be its own setting;
- pyright's source is in the room's image where any module holds a
  `PyrightSource`, as lup's own `LupDevelopment` does.

Rule selections are kept as recorded, one per module beside the module's own
default, for the engine to resolve.

What judging a write reads of it is kept apart, as a `Declaration` of plain values,
since the modules and the runner may be a project's own classes, which JSON can't
bring back: the judge keeps the last declaration that loaded, to stand in for one
that can't.
"""

from datetime import timedelta
from pathlib import Path
from typing import Self

from pydantic import model_validator

from lup.blocks import SHELL_TONES
from lup.doors import served as methods
from lup.types import Model
from lup_dev.catalog.gate import Step
from lup_dev.catalog.paths import CorePaths
from lup_dev.catalog.room import CacheLifetime
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Named, listed, set_fields
from lup_dev.declaration.kinds import (
    Credentials,
    Exemption,
    Exemptions,
    Folds,
    Gate,
    Guidance,
    Mounted,
    Package,
    Packages,
    Paths,
    PyrightSource,
    Pytest,
    RemovedTools,
    Repositories,
    Repository,
    Rules,
    Section,
    Serving,
    Session,
    TestRoots,
    Tones,
)
from lup_dev.declaration.load import load
from lup_dev.declaration.module import Module
from lup_dev.declaration.modules.core import Core
from lup_dev.declaration.modules.shipped import default, shipped
from lup_dev.declaration.project import Project
from lup_dev.declaration.requirements import Needed
from lup_dev.declaration.runner import Plain, Prefixed, Runner
from lup_dev.declaration.serving import ModuleServing, made_with, requests, tools
from lup_dev.host.protocol import Drawn, Limits, Looks


class PathRoles(Model, extra="forbid"):
    """Each role's patterns from every selected module, as the roles read them."""

    protected: list[str]
    secret: list[str] = CorePaths().secret
    """lup's own in a declaration kept before this role, which may still stand
    in: none would leave every secret's path writable unasked."""
    operator_documents: list[str]
    excluded: list[str]
    tests: list[str] = []
    """Empty in a declaration kept before this role, which may still stand in."""
    scratch: list[str]
    docs: list[str]
    data: list[str]
    source_trees: list[str]
    python: list[str]
    conftest: list[str]


class Selected(Model):
    """One module's rule selection, as it's recorded, for the engine to resolve.

    The engine resolves `default` from nothing beneath it, then `rules` from that:
    `Rules.default()` there starts from the module's own default, and `Rules()`
    from nothing beneath it, since its operations begin with the default's
    (`docs/declaration.md`, *Selecting the rules*).
    """

    module: str
    """The module's name."""
    rules: Rules
    """Its selection with every layer applied over its own default, as `Modules`
    places it."""
    default: Rules
    """The module's own default for its rules: what `Rules.default()` starts from
    there. `Rules()` is none."""


class SessionChoices(Model, extra="forbid"):
    """How the project's sessions run: `Core`'s `session`, its removed tools resolved.

    Its fields are `Session`'s, each as a plain value, for the launch to compile
    into each runtime's settings, and which of them the declaration set: those
    are imposed over the person's own runtime settings, and the rest are lup's
    defaults, which theirs outrank.
    """

    subagent_cache: CacheLifetime
    auto_memory: bool
    idle_compaction: bool
    removed_tools: list[str]
    """A runtime's built-in tools removed from a session's context, by name."""
    account_connectors: bool
    declared: list[str] = []
    """The fields some layer of the declaration set, by name, in the order
    they're declared; every other field is lup's default."""

    @model_validator(mode="after")
    def declared_fields(self) -> Self:
        """Refuse a declared field that isn't a session setting."""
        settings = [field for field in type(self).model_fields if field != "declared"]
        unknown = [field for field in self.declared if field not in settings]
        if unknown:
            message = (
                f"{listed(unknown)} aren't session settings; {listed(settings)} are"
            )
            raise ValueError(message)
        return self


class Part[K](Model):
    """One module's value of a kind, and the module's own default for it."""

    module: str
    """The module's name."""
    value: K
    """Every layer applied over the module's own default, as `Modules` places
    it, so its operations begin with the default's where none starts over."""
    default: K | None
    """The module's own default for the field holding it: what `Kind.default()`
    starts from there. `Kind()` starts from nothing beneath it."""


class Owned(Model):
    """An entry's name, and the module holding it."""

    module: str
    name: str


class Kept[E](Model):
    """One entry of a kind, and the module holding it."""

    module: str
    entry: E


class Served(Model):
    """A class of a module's methods, with the module it's made with."""

    module: Module
    serving: type[ModuleServing]


class Shared(Model):
    """A module whose own data directory for the repository a room mounts: every room, or a launch lending it."""

    module: str
    """The module's name."""
    read_only: bool
    always: bool = False
    """Whether every room mounts it; otherwise only a launch lending it by the
    module's name."""


class Resolved(Model):
    """A declaration resolved: what its readers need, each kind from every module."""

    modules: list[Module]
    """The selected modules in order, every layer applied, each field a layer set
    credited to that layer (`Module.origins`)."""
    paths: PathRoles
    gate: list[Step]
    """The gate's steps, in the order they run."""
    rules: list[Selected]
    """Each module's rule selection, as recorded."""
    exempt: list[Exemption]
    tests: list[Pytest]
    conditions: list[str]
    """The Python modules declaring the conditions a `defer` waits on, by name."""
    runner: Runner
    requirements: list[Needed]
    """Every selected module's requirements, its runner's among them."""
    packages: list[Package]
    """The room's image's packages: every selected module's own, in their order,
    then the one each requirement names. One name from two places is one
    package, the first's."""
    session: SessionChoices
    package_age: timedelta
    """How long a package must have been published before the room's package
    managers install it: `Core`'s `package_age`."""
    limits: Limits
    """What the host does with the operator's credentials for a launched
    session without asking, and the refs no push updates: `Core`'s
    `credentials`, resolved."""
    guidance: list[Section]
    """The sections of guidance, in the order of their modules but where one is
    placed by another's name."""
    repositories: list[Repository]
    """The other repositories the project's sessions may read, from every module
    holding some, merged by name; each path as written. A person names theirs
    in their own layer, `lup_project.local.py`."""
    held: list[str]
    """What a change waits for the operator's answer on, by name (`Project.held`)."""
    flagged: list[str]
    """What a change lands with, flagged, by name (`Project.flagged`)."""
    profile: str | None = None
    """The profile the person's layer chooses for the repository's launches,
    by its name (`Project.profile`); none for `default`, where `--profile`
    names none."""
    served: list[Served] = []
    """Each module's classes of methods, each with its module: its tools, its
    requests and its hooks."""
    shared: list[Shared] = []
    """The modules whose own data directory each room mounts."""
    looks: Looks = Looks()
    """The fold kinds, tones and drawers the modules' views declare."""
    pyright_source: PyrightSource | None = None
    """pyright's source in the room's image, for the engine's build in the room,
    where a module holds it; none otherwise."""


def parts[K](modules: list[Module], kind: type[K]) -> list[Part[K]]:
    """Return every module's values of `kind`, in the order of the modules."""
    return [
        Part(
            module=module.name,
            value=value,
            default=default if isinstance(default := info.default, kind) else None,
        )
        for module in modules
        for field, info in type(module).model_fields.items()
        if isinstance(value := getattr(module, field), kind)
    ]


def distinct(label: str, owned: list[Owned]) -> None:
    """Raise `ProjectError` where two modules give a kind's entry the same name."""
    clashes = [
        f"`{one.name}` from `{one.module}` and `{other.module}`"
        for at, one in enumerate(owned)
        for other in owned[at + 1 :]
        if one.name == other.name
    ]
    if clashes:
        message = (
            f"{label}: two modules name one entry alike, {'; '.join(clashes)}. "
            "Names are shared across modules: drop or rename one"
        )
        raise ProjectError(message)


def own[E](part: Part[Named[E]]) -> list[E]:
    """Return a module's own default entries of a kind, resolved: what `Kind.default()` starts from there."""
    if part.default is None:
        return []
    return [each.entry for each in part.default.resolve([], [])]


def entries[E](modules: list[Module], kind: type[Named[E]]) -> list[Kept[E]]:
    """Return every module's entries of `kind`, resolved, each with its module's name."""
    return [
        Kept(module=part.module, entry=each.entry)
        for part in parts(modules, kind)
        for each in part.value.resolve(own(part), own(part))
    ]


def made(label: str, owners: list[Owned], wrong: list[Owned]) -> None:
    """Raise `ProjectError` where an entry isn't made with the module holding it, or two modules name one alike."""
    if wrong:
        named = "; ".join(f"`{each.name}` in `{each.module}`" for each in wrong)
        message = (
            f"{label}: {named} narrows its `module` to another module's class, so "
            "it can't be made with the module holding it"
        )
        raise ProjectError(message)
    distinct(label, owners)


def served(modules: list[Module]) -> list[Served]:
    """Return each module's classes of methods, each with its module, checking each is made with it, and that each tool's name and each kind of request is one module's."""
    by_name = {module.name: module for module in modules}
    found = [
        Served(module=by_name[each.module], serving=each.entry)
        for each in entries(modules, Serving)
    ]
    made(
        "Serving",
        [],
        [
            Owned(module=each.module.name, name=each.serving.__name__)
            for each in found
            if not made_with(each.serving, each.module)
        ],
    )
    distinct(
        "Tools",
        [
            Owned(module=each.module.name, name=spec.name)
            for each in found
            for spec in tools(each.serving)
        ],
    )
    distinct(
        "The room's requests",
        [
            Owned(module=each.module.name, name=kind)
            for each in found
            for kind in requests(each.serving)
        ],
    )
    return found


def looked(modules: list[Module], found: list[Served]) -> Looks:
    """Return how the modules' views look: each module's fold kinds and tones, and the drawers its views are placed in.

    Raise `ProjectError` where two take one letter, a fold kind's or a drawer's;
    where a tone takes a shell tone's name, takes the look of a tone that's
    none of the shell's or the modules', or takes no look at all.
    """
    folds = held(Folds(), parts(modules, Folds), "Fold kinds")
    tones = held(Tones(), parts(modules, Tones), "Tones")
    drawers = [
        Drawn(module=each.module.name, view=name, place=door.place)
        for each in found
        for name, method in methods(each.serving).items()
        if (door := method.viewing()) is not None and door.place is not None
    ]
    distinct(
        "Fold keys",
        [
            *(Owned(module="its fold kinds", name=fold.letter) for fold in folds),
            *(Owned(module=each.module, name=each.place.letter) for each in drawers),
        ],
    )
    shell = [tone.name for tone in SHELL_TONES]
    known = [*shell, *(tone.name for tone in tones)]
    wrong = [
        f"`{tone.name}` takes a name of the shell's tones, {', '.join(shell)}"
        if tone.name in shell
        else f"`{tone.name}` takes the look of `{tone.like}`, which is no tone"
        if tone.like is not None and tone.like not in known
        else f"`{tone.name}` takes no look: give it `like=` or `colour=`"
        for tone in tones
        if tone.name in shell
        or (tone.like is not None and tone.like not in known)
        or (tone.like is None and tone.colour is None)
    ]
    if wrong:
        message = f"Tones: {'; '.join(wrong)}"
        raise ProjectError(message)
    return Looks(folds=folds, tones=tones, drawers=drawers)


def held[E](
    kind: Named[E], found: list[Part[Named[E]]], label: str, *, shared: bool = True
) -> list[E]:
    """Resolve each module's selection of a kind, check its names, and order it.

    `Kind.default()` in a selection starts from the module's own default,
    resolved, and `Kind()` from nothing beneath it, so the default's operations
    run once. With `shared`, a name is shared across modules, so one from two
    modules fails; without, each module's entries stand beside the others', as
    an exemption's do.
    """
    resolved = [part.value.resolve(own(part), own(part)) for part in found]
    if shared:
        distinct(
            label,
            [
                Owned(module=part.module, name=kind.named(each.entry))
                for part, placed in zip(found, resolved, strict=True)
                for each in placed
            ],
        )
    return kind.ordered([each for placed in resolved for each in placed])


def image(modules: list[Module], requirements: list[Needed]) -> list[Package]:
    """Return the room's image's packages: the modules' own, then the requirements'.

    A requirement's package joins with the requirement's reason. A name from two
    places is one package, the first's.
    """
    own = held(Packages(), parts(modules, Packages), "Packages", shared=False)
    provided = [
        Package(
            name=each.requirement.package,
            why=(
                f"provides `{each.requirement.named()}` for `{each.module}`: "
                f"{each.requirement.why or 'no reason given'}"
            ),
        )
        for each in requirements
        if each.requirement.package is not None
    ]
    every = [*own, *provided]
    names = [each.name for each in every]
    return [each for at, each in enumerate(every) if each.name not in names[:at]]


def neighbours(modules: list[Module]) -> list[Repository]:
    """Return the other repositories `modules` declare, merged by name.

    One name from two modules is one repository, the first's, where both give
    it the same path; with different paths, the load fails naming both.
    """
    every = held(
        Repositories(), parts(modules, Repositories), "Repositories", shared=False
    )
    clashes = [
        f"`{one.name}` at `{one.path}` and at `{other.path}`"
        for at, one in enumerate(every)
        for other in every[at + 1 :]
        if one.name == other.name and one.path != other.path
    ]
    if clashes:
        message = (
            f"Repositories: two modules give one repository different paths, "
            f"{'; '.join(clashes)}. A name is one repository: give it one path, "
            "or rename one"
        )
        raise ProjectError(message)
    names = [each.name for each in every]
    return [each for at, each in enumerate(every) if each.name not in names[:at]]


def settled(found: list[Part[Session]]) -> SessionChoices:
    """Return the session settings from the one module holding them.

    `Core` holds them, so a module of a project's own holding them too fails,
    naming both; with none, they're lup's. The fields declared are those the
    value's layers set: each layer is a copy of the one below with its fields
    updated (`applied`), which pydantic counts as set, so a field nothing set
    stays lup's default.
    """
    if len(found) > 1:
        holding = listed([part.module for part in found])
        message = (
            f"{holding} each give session settings, and a project's sessions run "
            "one way: change `Core`'s with `.edit(Core(session=Session(…)))`"
        )
        raise ProjectError(message)
    session = found[0].value if found else Session()
    default = found[0].default if found and found[0].default else Session()
    own = [each.entry for each in default.removed_tools.resolve([], [])]
    removed = RemovedTools().ordered(session.removed_tools.resolve(own, own))
    return SessionChoices(
        subagent_cache=session.subagent_cache,
        auto_memory=session.auto_memory,
        idle_compaction=session.idle_compaction,
        removed_tools=removed,
        account_connectors=session.account_connectors,
        declared=set_fields(session),
    )


def limited(found: list[Part[Credentials]]) -> Limits:
    """Return the limits on the operator's credentials, from the one module holding them.

    `Core` holds them, so a module of a project's own holding them too fails,
    naming both: a launch has one set of limits. With none, they're lup's.
    """
    if len(found) > 1:
        holding = listed([part.module for part in found])
        message = (
            f"{holding} each give limits on the operator's credentials, and a "
            "launch has one set: change `Core`'s with "
            "`.edit(Core(credentials=Credentials(…)))`"
        )
        raise ProjectError(message)
    credentials = found[0].value if found else Credentials()
    default = found[0].default if found and found[0].default else Credentials()
    return credentials.resolve(default)


def checked(modules: list[Module]) -> list[Module]:
    """Return `modules` once `Core` and every module required are among them."""
    if not any(type(module) is Core for module in modules):
        message = (
            "`Core` is required: every project holds lup's `Core`, and this "
            "declaration's modules leave it out"
        )
        raise ProjectError(message)

    none: list[str] = []

    def cycle(module: type[Module], trail: list[type[Module]]) -> list[str]:
        if module in trail:
            return [each.name for each in trail[trail.index(module) :]] + [module.name]
        return next(
            (
                found
                for required in module.requires
                if (found := cycle(required, [*trail, module]))
            ),
            none,
        )

    looped = next(
        (found for module in modules if (found := cycle(type(module), []))), none
    )
    if looped:
        around = " requires ".join(f"`{name}`" for name in looped)
        message = f"Modules can't require each other in a cycle: {around}"
        raise ProjectError(message)
    names = [module.name for module in modules]
    missing = [
        f"`{module.name}` requires `{required.name}`, which isn't selected"
        for module in modules
        for required in module.requires
        if required.name not in names
    ]
    if missing:
        message = (
            f"{'; '.join(missing)}. Add each, or drop what requires it too: lup "
            "never adds or drops a module behind the declaration's back"
        )
        raise ProjectError(message)
    return modules


def resolve(project: Project) -> Resolved:
    """Resolve `project`'s declaration, or raise `ProjectError` saying what's wrong.

    Its modules are a layer on lup's default ones, `Project`'s own default, as
    each module is a layer on its own defaults (`Modules.placed`), so
    `Modules()` there starts from lup's.
    """
    selection = project.modules.over(Project().modules)
    modules = checked(selection.ordered(selection.resolve(default(), shipped())))

    def role(name: str) -> list[str]:
        patterns = [
            pattern
            for part in parts(modules, Paths)
            for pattern in part.value.resolve(part.default or Paths())[name]
        ]
        return list(dict.fromkeys(patterns))

    runners = parts(modules, Runner)
    if len(runners) > 1:
        holding = listed([part.module for part in runners])
        message = f"{holding} each give a runner, and a project runs its tools one way"
        raise ProjectError(message)
    runner = runners[0].value if runners else Plain()
    needed = [
        Needed(module=module.name, requirement=requirement)
        for module in modules
        for requirement in module.requirements
    ]
    brought = [
        Needed(module=part.module, requirement=requirement)
        for part in runners
        for requirement in part.value.requirements
    ]
    requirements = [*needed, *brought]
    found = served(modules)
    return Resolved(
        modules=modules,
        paths=PathRoles.model_validate({name: role(name) for name in Paths.roles()}),
        gate=held(Gate(), parts(modules, Gate), "The gate's steps"),
        rules=[
            Selected(
                module=part.module,
                rules=part.value,
                default=part.default if part.default is not None else Rules(),
            )
            for part in parts(modules, Rules)
        ],
        exempt=held(
            Exemptions(), parts(modules, Exemptions), "Exemptions", shared=False
        ),
        tests=held(TestRoots(), parts(modules, TestRoots), "Test roots"),
        conditions=[
            module.conditions for module in modules if module.conditions is not None
        ],
        runner=runner,
        requirements=requirements,
        packages=image(modules, requirements),
        session=settled(parts(modules, Session)),
        package_age=next(
            module.package_age for module in modules if isinstance(module, Core)
        ),
        limits=limited(parts(modules, Credentials)),
        guidance=held(Guidance(), parts(modules, Guidance), "Guidance"),
        repositories=neighbours(modules),
        held=project.held,
        flagged=project.flagged,
        profile=project.profile,
        served=found,
        looks=looked(modules, found),
        shared=[
            Shared(
                module=part.module,
                read_only=part.value.read_only,
                always=part.value.always,
            )
            for part in parts(modules, Mounted)
        ],
        pyright_source=next(
            (part.value for part in parts(modules, PyrightSource)), None
        ),
    )


class Declaration(Model):
    """A declaration as judging reads it: its file, and plain values resolved from it.

    `Resolved` holds the selected modules and the runner, which may be a project's
    own subclasses, so it can't be read back from JSON. This holds only what the
    roles, the judge and `lup-dev rules check` read, all of it plain data, the
    runner kept as its commands, so the last declaration that loaded is kept as
    JSON and stands in for one that can't (`docs/judging-writes.md`, *A
    declaration that can't load has a stand-in*).
    """

    source: Path | None = None
    """The declaration's file, relative to the root, which is always protected;
    none for the defaults."""
    paths: PathRoles
    tests: list[Pytest] | None
    """The test roots the declaration names; none where they're lup's default,
    and pytest's configuration says where tests are."""
    exempt: list[Exemption]
    conditions: list[str]
    """The Python modules declaring the conditions a `defer` waits on, by name."""
    rules: list[Selected]
    """Each module's rule selection, as recorded, for the engine to resolve."""
    runner: Prefixed
    """The project's runner, kept as the commands it puts before a tool, its
    environment's directory and its files: the engine reads that environment."""
    held: list[str] = Project().held
    """What a change waits for the operator's answer on, by name."""
    flagged: list[str] = Project().flagged
    """What a change lands with, flagged, by name."""
    modules: list[str] = []
    """The modules it selects, by name, in order."""

    @classmethod
    def of(cls, project: Project, source: Path | None = None) -> Declaration:
        """Resolve `project`, read from `source`, and keep what judging reads.

        Raise `ProjectError` where it doesn't resolve.

        >>> Declaration.of(Project()).tests is None
        True
        """
        resolved = resolve(project)
        named = resolved.tests != resolve(Project()).tests
        return cls(
            source=source,
            paths=resolved.paths,
            tests=resolved.tests if named else None,
            exempt=resolved.exempt,
            conditions=resolved.conditions,
            rules=resolved.rules,
            runner=Prefixed.of(resolved.runner),
            held=resolved.held,
            flagged=resolved.flagged,
            modules=[module.name for module in resolved.modules],
        )

    @classmethod
    def read(cls, root: Path) -> Declaration:
        """Load the declaration at `root` and resolve it, or raise `ProjectError`."""
        declared = load(root)
        return cls.of(declared.project, declared.source)
