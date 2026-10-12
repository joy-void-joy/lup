"""The kinds a module fills, each a selection of its own entries.

Every collection in a module is one of these, so a layer changes it by operations
on what's below rather than restating it (`docs/declaration.md`, *The verbs on
modules*). `Modules`, the selection of modules, is with `Module`. The rest of the
kinds (commands, rooms, skills, guidance, doctests) arrive with the pieces that
read them.
"""

from pathlib import Path
from typing import Self, override

from lup.types import Model
from lup_dev.catalog.gate import Step
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
