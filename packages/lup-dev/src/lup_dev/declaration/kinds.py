"""The kinds a module fills, each a selection of its own entries, or a `Layer` of them.

Every collection in a module is one of these, so a layer changes it by operations
on what's below rather than restating it (`docs/declaration.md`, *The verbs on
modules*). A model holding several, `Paths` or `Session`, is a `Layer`, which a
layer changes field by field. `Modules`, the selection of modules, is with
`Module`. The rest of the kinds (commands, rooms, skills, doctests) arrive with
the pieces that read them.
"""

from pathlib import Path
from typing import Self, override

from lup.types import Model
from lup_dev.catalog.gate import Step
from lup_dev.catalog.room import CacheLifetime, SessionDefaults
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.grammar import Layer, Named, listed


class Rules(Named[str]):
    """Which of lup's code rules run, by id.

    Python only composes and records a rule selection: the engine, which holds the
    rule tables, resolves it, and refuses an id it doesn't hold
    (`docs/declaration.md`, *Selecting them*).

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
        """Resolve each role's patterns, `defaults` being the module's own."""

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
