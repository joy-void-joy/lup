"""The kinds a module fills, each a selection of its own entries, or a `Layer` of them.

Every collection in a module is one of these, so a layer changes it by operations
on what's below rather than restating it (`docs/declaration.md`, *The verbs on
modules*). A model holding several, `Paths`, `Session` or `Credentials`, is a
`Layer`, which a layer changes field by field. `Modules`, the selection of
modules, is with `Module`. The rest of the kinds (commands, rooms, skills,
doctests) arrive with the pieces that read them.
"""

from functools import reduce
from pathlib import Path
from typing import Self, override

from pydantic import model_validator

from lup.types import Model
from lup_dev.catalog.credentials import CredentialDefaults, Withheld
from lup_dev.catalog.gate import Step
from lup_dev.catalog.room import CacheLifetime, SessionDefaults
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import (
    Add,
    All,
    Below,
    Default,
    Drop,
    Edit,
    Layer,
    Named,
    Of,
    Only,
    Replace,
    listed,
)
from lup_dev.declaration.serving import ModuleHandler, ModuleHooks, ModuleTools
from lup_dev.host.protocol import GitHubRepository, Limits, actions


class Rules(Named[str]):
    """Which of lup's code rules run, by id.

    Python only composes and records a rule selection: the engine, which holds the
    rule tables, resolves it, and refuses an id it doesn't hold
    (`docs/declaration.md`, *Selecting the rules*).

    >>> mine = Rules().drop("tuple-shape").over(Rules.default().drop("regex"))
    >>> mine.start.kind, [operation.names for operation in mine.operations]
    ('default', [['regex'], ['tuple-shape']])
    """


class Patterns(Named[str]):
    """One path role's patterns, from the root; a pattern is its own name.

    Patterns are matched whole, `**` spanning any number of directories
    (`PurePath.full_match`).
    """


class Paths(Layer, extra="forbid"):
    """Each path role's patterns, a selection per role.

    Its verbs take roles as keywords: `Paths.of(protected=[…])` gives a module's
    own, `.add(protected=[…])` and `.drop(data=["*.yaml"], why=…)` change the
    value below, role by role. The same pattern from two modules is one pattern.
    How each role is used, and in which order, is `lup_dev.policy.roles`'s.

    >>> Paths.of(data=["episodes/**"]).add(data=["takes/**"]).data.operations[0].entries
    ['takes/**']
    >>> Paths.of(dta=["episodes/**"])
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: `Paths` has no role `dta`; its roles are `protected`, `operator_documents`, `excluded`, `scratch`, `docs`, `data`, `source_trees`, `python` and `conftest`
    """

    protected: Patterns = Patterns()
    """Every write to these asks the operator."""
    operator_documents: Patterns = Patterns()
    """The operator's documents: changing one is a design decision, so it asks."""
    excluded: Patterns = Patterns()
    """Paths held to nothing: no rules and no findings, and writes allowed. A path
    both protected and excluded still asks."""
    scratch: Patterns = Patterns()
    """Scratch work: allowed at any size."""
    docs: Patterns = Patterns()
    """Documentation: allowed at any size."""
    data: Patterns = Patterns()
    """Data formats, by file name: allowed outside a source tree, production inside."""
    source_trees: Patterns = Patterns()
    """Where code lives: a data file here ships with it, so it's production."""
    python: Patterns = Patterns()
    """Python modules, by file name: what lup's rules and the engine read."""
    conftest: Patterns = Patterns()
    """The modules pytest reads beside a suite's tests, by file name, which count
    as tests."""

    @classmethod
    def roles(cls) -> list[str]:
        """List the roles, in the order they're declared."""
        return list(cls.model_fields)

    @classmethod
    def known(cls, roles: list[str]) -> None:
        """Raise `ProjectError` where `roles` names one that isn't a role."""
        unknown = [role for role in roles if role not in cls.model_fields]
        if unknown:
            message = (
                f"`Paths` has no role {listed(unknown)}; "
                f"its roles are {listed(cls.roles())}"
            )
            raise ProjectError(message)

    @classmethod
    def default(cls) -> Self:
        """Start every role from the module's own default patterns."""
        return cls.model_validate({role: Patterns.default() for role in cls.roles()})

    @classmethod
    def of(cls, **roles: list[str]) -> Self:
        """Start every role over, from these patterns: a module's own."""
        cls.known(list(roles))
        return cls.model_validate(
            {role: Patterns.of(*roles.get(role, [])) for role in cls.roles()}
        )

    def role(self, role: str) -> Patterns:
        """Return one role's selection."""
        return getattr(self, role)

    def add(self, **roles: list[str]) -> Self:
        """Add patterns to the roles named, beside the ones below."""
        self.known(list(roles))
        return self.model_copy(
            update={
                role: self.role(role).add(*patterns) for role, patterns in roles.items()
            }
        )

    def drop(self, *, why: str | None = None, **roles: list[str]) -> Self:
        """Leave these patterns out of the roles named."""
        self.known(list(roles))
        return self.model_copy(
            update={
                role: self.role(role).drop(*patterns, why=why)
                for role, patterns in roles.items()
            }
        )

    def resolve(self, defaults: Paths) -> dict[str, list[str]]:
        """Resolve each role's patterns, `defaults` being the module's own.

        A role starting from `Patterns.default()` starts from the module's own,
        resolved, and one from `Patterns()` from nothing beneath it, so a default
        written `Paths().add(…)` adds its patterns once.
        """

        def resolved(role: str) -> list[str]:
            own = [each.entry for each in defaults.role(role).resolve([], [])]
            return [each.entry for each in self.role(role).resolve(own, own)]

        return {role: resolved(role) for role in self.roles()}


class Gate(Named[Step]):
    """The gate's steps, each named, placed `before=` or `after=` another's name.

    A step goes after one of another module's, `after="pytest"`, though pytest is
    `Python`'s; steps with neither keep the order of their modules.
    """

    @override
    def named(self, entry: Step) -> str:
        return entry.name


class Exemption(Model, extra="forbid"):
    """A rule lifted from some paths, with the reason the operator approved."""

    rule: str
    """The rule's id, as `lup-dev rules list` names it."""
    paths: list[str]
    """Where it's lifted, as patterns from the root, matched as `protected` is."""
    why: str
    """Why the rule doesn't hold there."""


class Exemptions(Named[Exemption]):
    """Rules lifted from whole files, each with its reason, named by its rule.

    An `ignore` keeps one finding out, on its line; an exemption keeps one rule's
    findings out of every file its patterns match. Every other rule still holds
    there.
    """

    @override
    def named(self, entry: Exemption) -> str:
        return entry.rule


class Pytest(Model, extra="forbid"):
    """A root pytest collects tests from, and the file names it collects there."""

    root: Path
    """The directory, relative to the worktree's root."""
    files: list[str] = ["test_*.py", "*_test.py"]
    """pytest's `python_files` patterns, its defaults unless the project says."""


class TestRoots(Named[Pytest]):
    """The test roots: the test role, and what pytest's `testpaths` must cover."""

    __test__ = False
    """Not a suite for pytest to collect, though its name starts with `Test`."""

    @override
    def named(self, entry: Pytest) -> str:
        return entry.root.as_posix()


class Package(Model, extra="forbid"):
    """A package of the room's image, and why it's there."""

    name: str
    """Its name in Arch Linux's repositories, the room's image being Arch's."""
    why: str
    """What it's there for."""


class Packages(Named[Package]):
    """The packages a module puts in the room's image, each named by its name.

    The same package from two modules, or from a module and a requirement naming
    it, is one package.
    """

    @override
    def named(self, entry: Package) -> str:
        return entry.name


class RemovedTools(Named[str]):
    """A runtime's built-in tools removed from a session's context, by name."""


class Session(Layer, extra="forbid"):
    """How every session of the project runs, in neutral terms each adapter spells.

    A layer on it changes only the fields it sets: a project turning auto memory
    on keeps lup's removed tools, and `RemovedTools().add(…)` or `.drop(…)` changes
    them where they stand. A field some layer sets is imposed over the person's
    own runtime settings; one none sets is lup's default, which theirs outrank.

    >>> mine = Session(auto_memory=True).over(Session())
    >>> mine.auto_memory, mine.removed_tools == Session().removed_tools
    (True, True)
    """

    subagent_cache: CacheLifetime = SessionDefaults().subagent_cache
    """How long the prompt cache of a session's subagents lasts: `"1h"`, or the
    API's other lifetime, `"5m"`."""
    auto_memory: bool = SessionDefaults().auto_memory
    """Whether a runtime keeps its own memory across sessions."""
    idle_compaction: bool = SessionDefaults().idle_compaction
    """Whether a runtime compacts a long conversation while the session sits
    idle, where it can: off unless the person's own settings or the project
    turn it on. Compaction when the context fills is the runtime's own."""
    removed_tools: RemovedTools = RemovedTools.of(*SessionDefaults().removed_tools)
    """A runtime's built-in tools removed from a session's context, by name:
    lup's (`lup_dev.catalog.room`), unless the project says."""
    account_connectors: bool = SessionDefaults().account_connectors
    """Whether a session fetches the connectors the operator's account brings
    with its login, which reach their mail and files: off unless the person's
    own settings or the project turn them on."""


def mentioned(selection: Named[str]) -> list[str]:
    """List the names a selection writes, in order: those it starts from, adds, drops or puts in another's place.

    >>> mentioned(Refs.of("refs/heads/main").add("refs/tags/*").drop("refs/heads/main"))
    ['refs/heads/main', 'refs/tags/*', 'refs/heads/main']
    """

    def named(
        step: Below
        | Default
        | All
        | Only
        | Of[str]
        | Add[str]
        | Drop
        | Replace[str]
        | Edit[str],
    ) -> list[str]:
        match step:
            case Only(names=names) | Drop(names=names):
                return names
            case Of(entries=entries) | Add(entries=entries):
                return entries
            case Replace(name=name, entry=entry):
                return [name, entry]
            case Edit(entry=entry):
                return [entry]
            case Below() | Default() | All():
                return []

    return [
        name
        for step in [selection.start, *selection.operations]
        for name in named(step)
    ]


class Actions(Named[str]):
    """What the host does with the operator's credentials without asking, each by its name.

    Each is a handler lup carries out (`lup_dev.host.protocol`, `Action`):
    `Actions.all()` is every one, and lup's default leaves out those
    `lup_dev.catalog.credentials` withholds, each with its reason. A name that
    isn't an action is refused where it's written, naming those that are.

    >>> Actions().add("forse-push")
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: `Actions` has no action `forse-push`; its actions are `fetch`, `push`, `force-push`, `delete-ref`, `read-issues`, `file-issue`, `comment` and `draft-pull-request`
    """

    @model_validator(mode="after")
    def known(self) -> Self:
        """Refuse a name that isn't an action, naming those that are."""
        every: list[str] = [*actions()]
        unknown = [name for name in mentioned(self) if name not in every]
        if unknown:
            message = (
                f"`Actions` has no action {listed(unknown)}; "
                f"its actions are {listed(every)}"
            )
            raise ProjectError(message)
        return self


def lup_actions() -> Actions:
    """Return lup's default actions: every one but those the catalog withholds.

    Each one withheld is a drop with its reason, so the overview shows why, and
    an action a later release adds is allowed unless the catalog withholds it too.

    >>> [operation.names for operation in lup_actions().operations]
    [['force-push'], ['delete-ref']]
    """

    def without(chosen: Actions, withheld: Withheld) -> Actions:
        return chosen.drop(withheld.action, why=withheld.why)

    return reduce(without, CredentialDefaults().withheld, Actions.all())


class Refs(Named[str]):
    """Patterns over full ref names, such as `refs/heads/main` or `refs/tags/*`.

    A pattern that isn't over full ref names, a branch's short name such as
    `main`, would match no ref, so it's refused where it's written.

    >>> Refs().add("main")
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: `Refs` names `main`, which isn't over full ref names: a pattern starts with `refs/`, as `refs/heads/main` does
    """

    @model_validator(mode="after")
    def full(self) -> Self:
        """Refuse a pattern that doesn't start with `refs/`."""
        short = [name for name in mentioned(self) if not name.startswith("refs/")]
        if short:
            message = (
                f"`Refs` names {listed(short)}, which isn't over full ref names: "
                "a pattern starts with `refs/`, as `refs/heads/main` does"
            )
            raise ProjectError(message)
        return self


class Credentials(Layer, extra="forbid"):
    """What the host does with the operator's credentials for a launched session without asking, and the refs no push updates.

    A layer on it changes only the fields it sets, as on `Session`: a project
    allowing force pushes keeps lup's protected refs, and `Refs().add(…)` adds
    to them where they stand. A launch sends them, resolved, to the host
    service, whose handlers hold each action to them (`docs/host-tools.md`,
    *What the declaration allows*).

    >>> mine = Credentials(actions=Actions().add("force-push")).over(Credentials())
    >>> limits = mine.resolve(Credentials())
    >>> "force-push" in limits.actions, limits.protected
    (True, ['refs/heads/main', 'refs/tags/*'])
    """

    actions: Actions = lup_actions()
    """What the host does with the operator's credentials without asking: every
    action lup carries out but those `lup_dev.catalog.credentials` withholds,
    unless the project says."""
    protected: Refs = Refs.of(*CredentialDefaults().protected)
    """The refs no push updates, as patterns over full ref names: `main` and
    every tag (`lup_dev.catalog.credentials`), unless the project says."""
    gated: Refs = Refs.of(*CredentialDefaults().gated)
    """The refs a push from a room updates only once the gate passed on its
    commit, as patterns over full ref names: the integration branch, `dev`
    (`lup_dev.catalog.credentials`), unless the project says."""

    def resolve(self, defaults: Credentials) -> Limits:
        """Resolve the actions allowed, the refs protected and the refs gated, `defaults` being the module's own.

        The actions come in the order `Action` names them, whatever order the
        layers gave them in.
        """
        every: list[str] = [*actions()]
        own = [each.entry for each in defaults.actions.resolve([], every)]
        allowed = [each.entry for each in self.actions.resolve(own, every)]
        lups = [each.entry for each in defaults.protected.resolve([], [])]
        gates = [each.entry for each in defaults.gated.resolve([], [])]
        return Limits(
            actions=[action for action in actions() if action in allowed],
            protected=Refs().ordered(self.protected.resolve(lups, lups)),
            gated=Refs().ordered(self.gated.resolve(gates, gates)),
        )


class Section(Model, extra="forbid"):
    """One section of the guidance every session reads, and where its text is.

    >>> Section(name="lup", path=Path("AGENTS.md")).package is None
    True
    """

    name: str
    """How `Guidance`'s verbs name it: `.replace("core", …)`."""
    path: Path
    """The file holding its text: from the project's root, or inside `package`
    where one is given."""
    package: str | None = None
    """The Python package shipping the file, by its dotted name, for a section a
    package brings (lup's modules', or a shared base's); none for a file of the
    project's own."""


class Guidance(Named[Section]):
    """The sections of guidance a module brings, each named by its name.

    Rendered into one text at launch. Sections go in the order of their modules,
    but where one is placed `before=` or `after=` another's name, whichever
    module holds it.
    """

    @override
    def named(self, entry: Section) -> str:
        return entry.name


class Repository(Model, extra="forbid"):
    """Another repository the project's sessions may read, where it is on the host, and what it is.

    A launched room mounts it whole and read-only at its host path, and the
    guidance lists it (`docs/related-repositories.md`). A name, a path, an
    `about` and a GitHub identity that's `owner/name` where one is given, or
    the load fails, naming the entry.

    >>> Repository(name="atlas", path=Path("atlas.git"), about="a made-up neighbour").github is None
    True
    >>> Repository(name="atlas", path=Path("atlas.git"), about="x", github="atlas")
    Traceback (most recent call last):
    ...
    lup_dev.declaration.errors.ProjectError: `Repository` `atlas` gives its GitHub repository as `atlas`: a repository on GitHub is `owner/name`, not 'atlas'
    """

    name: str
    """How sessions and the guidance call it."""
    path: Path
    """The repository on the host: a bare repository's git directory, with its
    worktrees under it, or a clone's working tree, with its `.git`. Relative to
    the directory holding the project's own repository (`atlas.git` beside
    `project.git`), or absolute; a leading `~` is the operator's home."""
    about: str
    """One line on what it is, and what it's for here."""
    github: str | None = None
    """Its `owner/name` on GitHub, where it has one, which the guidance gives so
    a session reads its issues through lup's GitHub tools."""

    def on_host(self, holding: Path) -> Path:
        """Return where it is on the host: its path from `holding`, the directory holding the project's own repository, or absolute, a leading `~` the operator's home, resolved.

        >>> Repository(name="atlas", path=Path("atlas.git"), about="x").on_host(Path("/r"))
        PosixPath('/r/atlas.git')
        """
        return (holding / self.path.expanduser()).resolve()

    @model_validator(mode="after")
    def written(self) -> Self:
        """Refuse an entry without a name, a path or an `about`, or with a GitHub identity that isn't `owner/name`."""
        if not self.name.strip():
            message = f"A `Repository` at `{self.path}` has no name"
            raise ProjectError(message)
        if self.path == Path():
            message = f"`Repository` `{self.name}` names no path"
            raise ProjectError(message)
        if not self.about.strip():
            message = (
                f"`Repository` `{self.name}` says nothing `about` what it is, "
                "which its sessions read"
            )
            raise ProjectError(message)
        if self.github is not None:
            try:
                GitHubRepository.read(self.github)
            except ValueError as malformed:
                message = (
                    f"`Repository` `{self.name}` gives its GitHub repository as "
                    f"`{self.github}`: {malformed}"
                )
                raise ProjectError(message) from malformed
        return self


class Repositories(Named[Repository]):
    """Other repositories for the project's sessions to read, each named by its name.

    Any module may hold one; `Core` holds none. Which repositories a person
    relates, and what each is, are theirs, so they go in a module of their own
    layer, `lup_project.local.py`, never in a committed declaration
    (`docs/related-repositories.md`, *A person's own layer*). One name from two modules is
    one repository, the first's, where both give it the same path; with
    different paths, the load fails naming both.
    """

    @override
    def named(self, entry: Repository) -> str:
        return entry.name


class Toolsets(Named[type[ModuleTools]]):
    """The classes of tools a module serves a launched session, each named by its class's name.

    `Toolsets.of(GitHubTools)`; a module may hold several, and a project drops
    one by its class's name. Each is made with the module holding it, so its class
    narrows `module` to that module's class.
    """

    @override
    def named(self, entry: type[ModuleTools]) -> str:
        return entry.__name__


class Handlers(Named[type[ModuleHandler]]):
    """A module's answers to its launch's room's requests, each named by its class's name."""

    @override
    def named(self, entry: type[ModuleHandler]) -> str:
        return entry.__name__


class Hooks(Named[type[ModuleHooks]]):
    """What a module does at lup's moments, each class named by its name."""

    @override
    def named(self, entry: type[ModuleHooks]) -> str:
        return entry.__name__


class Mounted(Model, extra="forbid"):
    """The module's own data directory for the repository, mounted into its rooms.

    At its host path, read-only unless it says, so a session reads what the
    module keeps (`Transcripts`' copies of past sessions); the guidance says
    where. In every room where `always`; otherwise in a launch that lends it by
    the module's name (`lup-dev launch <runtime> --mount transcripts`).
    """

    read_only: bool = True
    always: bool = False
    """Whether every room mounts it; otherwise only a launch lending it."""
