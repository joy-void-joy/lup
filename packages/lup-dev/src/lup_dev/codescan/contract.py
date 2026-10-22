"""What the judge asks the typed engine about a set of files, and what comes back.

The engine is pyright's own tree with lup's rules on it (`docs/judging-writes.md`,
*The engine*): a long-lived process per worktree, which checks files on disk or as
the content an edit would give them. This module holds the shapes both sides agree
on, and the interface the judge calls, so the judge can be tested against a fake
engine and the engine changed without touching the judge.

The engine reports lup's findings and pyright's type errors in one list, told apart
by their owner. ruff's findings take the same shape, though the judge gets them from
ruff itself. The `# lup: ignore` directives are applied by the judge, to every
owner's findings alike, so the engine reports findings as it finds them.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from lup.types import Model
from lup_dev.codescan.directives import Directive

if TYPE_CHECKING:
    from lup_dev.declaration.resolve import Selected
    from lup_dev.declaration.runner import Runner


class Position(Model):
    """A place in a file: its line and its column, both counted from 1."""

    line: int
    column: int


class Span(Model):
    """Where a finding sits, from its first character to just past its last."""

    start: Position
    end: Position


class Finding(Model):
    """One thing a checker reports in a file."""

    path: Path
    span: Span
    owner: Literal["lup", "pyright", "ruff"]
    rule: str
    """The rule's id.

    lup's (`tuple-shape`), pyright's (`reportOptionalMemberAccess`), or ruff's code
    (`E501`).
    """
    message: str
    """What's wrong here, whole.

    For a lup rule, what its check saw followed by the mistake the rule prevents. For
    pyright, its own message, which may run over several lines.
    """
    steer: str = ""
    """Where a lup rule steers instead; empty for pyright's and ruff's findings."""
    fixable: bool = False
    """Whether `ruff check --fix` fixes it, ruff's fix for it being safe.

    The agent never hears of such a finding: the session landing the work applies
    the fix (`lup-dev check --fix`).
    """
    reminder: bool = False
    """Whether it's work that came due rather than something wrong with the
    code: a deferral whose issue closed or whose condition holds, or an
    `ignore` whose issue closed. The gate lists
    it without failing, so its verdict depends on the files alone, and a
    session is told it at its start."""


class Due(Model):
    """The deferred work a repository's gate last found due: each reminder, where it is and what came due.

    `lup-dev rules check` over every file writes it, where it could ask about
    every issue a `# lup:` comment waits on; a session's start tells it (`GitDirectoryLayout.due`).
    """

    reminders: list[Finding] = []

    def told(self) -> str:
        """Say the reminders to a session, or nothing where there are none."""
        if not self.reminders:
            return ""
        heading = (
            "Work deferred in this repository came due, as the gate last found it "
            "(it doesn't fail the gate):"
        )
        lines = [
            f"- {each.path}:{each.span.start.line}: {each.message}; {each.steer}"
            for each in self.reminders
        ]
        return "\n".join([heading, *lines])


type Named = Literal["export", "class", "function"]
"""Which of a surface's names one is: an export, a class, or a function or
method."""


class Placed(Model):
    """Where one name of a file's surface is written: the line its name is on."""

    kind: Named
    name: str
    line: int
    """Counted from 1: an export's entry in `__all__` or its binding, a class's
    `class`, a function's or method's `def`."""


class Surface(Model):
    """What other code can depend on in one file.

    The judge compares it before and after a change, for the public-API ask. A
    name with a leading underscore isn't listed, a dunder's aside, nor is a
    member of such a class; a function nested in another never is.
    """

    exported: list[str] = []
    """The names a package's root (`__init__.py`) binds; empty elsewhere."""
    classes: list[str] = []
    """Every public class the module defines, by its dotted name inside the
    module: `Outer`, `Outer.Inner`."""
    functions: list[str] = []
    """Every public function and method, by its dotted name inside the module:
    `submit`, `Agent.ask`."""
    places: list[Placed] = []
    """Where each of the names above is written, which the review marks; a name
    `__all__` takes from another module's has none."""

    def names(self, kind: Named) -> list[str]:
        """Return the names of `kind`: the exports, the classes, or the functions and methods.

        >>> Surface(classes=["Client"], functions=["Client.ask"]).names("function")
        ['Client.ask']
        """
        match kind:
            case "export":
                return self.exported
            case "class":
                return self.classes
            case "function":
                return self.functions

    def place(self, kind: Named, name: str) -> int | None:
        """Return the line `name`, of `kind`, is written on; none where it isn't placed.

        >>> Surface(places=[Placed(kind="class", name="Client", line=4)]).place(
        ...     "class", "Client"
        ... )
        4
        """
        return next(
            (
                each.line
                for each in self.places
                if each.kind == kind and each.name == name
            ),
            None,
        )


class Source(Model):
    """A file to check: as it is on disk, or as the content an edit would give it."""

    path: Path
    content: str | None = None
    """The would-be content; none means the file as it stands on disk."""


class FileReport(Model):
    """Everything the engine reports about one file."""

    path: Path
    findings: list[Finding] = []
    """lup's findings and pyright's type errors, as found: no `ignore` applied yet."""
    directives: list[Directive] = []
    surface: Surface = Surface()
    imports: list[str] = []
    """Every module the file imports, by its full name, for the import contracts."""


class Flagged(Model):
    """Code a rule flags, and the same code done the way the rule steers."""

    code: str
    rewritten: str


class Examples(Model):
    """A rule's specification: code it flags, and near misses it must not flag."""

    flags: list[Flagged]
    passes: list[str] = []


class Rule(Model):
    """One of lup's rules, as the engine lists them from its table.

    The table (`lup_dev/catalog/rules.ts`) is where rules are declared; Python learns
    them only from the engine (`docs/judging-writes.md`, *How a rule is declared*).
    """

    id: str
    mistake: str
    """The mistake the rule prevents, as a sentence that stands alone."""
    steer: str
    """Where it steers instead, as a sentence that stands alone."""
    examples: Examples


class Checker(ABC):
    """A typed engine the judge asks about the files of one project."""

    @abstractmethod
    def rules(self, selected: list[Selected] | None = None) -> list[Rule]:
        """List lup's rules: those `selected` chooses, or every rule of the table, which a project's selection and `ignore`s name.

        `selected` is each module's selection, as the project's declaration
        records it, which the engine resolves as it does for a check, refusing
        what it would refuse there; the rules come in the table's order. With
        none, the whole table; an empty list chooses none.
        """

    @abstractmethod
    def check(
        self,
        root: Path,
        sources: list[Source],
        selected: list[Selected],
        runner: Runner,
    ) -> list[FileReport]:
        """Check the given files of the project at `root`, one report per file.

        The rules run are those `selected` chooses: each module's selection, as
        the project's declaration records it, which the engine resolves. Types
        are read in the environment the project's `runner` gives the worktree.
        Each report holds their findings and pyright's type errors, the file's
        directives, its public surface and its imports.
        """

    @abstractmethod
    def importers(
        self, root: Path, changed: list[Path], runner: Runner
    ) -> list[FileReport]:
        """Re-check, for type errors only, the files that import any of `changed`.

        Types are read in the environment the project's `runner` gives the
        worktree.
        """


class Parser(ABC):
    """What reads files from their parse alone, with no types: the engine's, for a first reading of a change a type check would hold up."""

    @abstractmethod
    def parsed(self, root: Path, sources: list[Source]) -> list[FileReport]:
        """Read the given files of the project at `root` from their parse alone, one report per source, in order.

        No project is loaded and no type is read, so it costs a parse: each
        report holds the file's directives and its public surface, and no
        finding or import. A package root's names are the ones it binds itself,
        no import being resolved. The same path may come more than once, each
        time with other content.
        """
