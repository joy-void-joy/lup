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
from typing import Literal

from lup.types import Model
from lup_dev.directives import Directive


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
    """What's wrong here, in one line."""
    steer: str = ""
    """Where a lup rule steers instead; empty for pyright's and ruff's findings."""


class Parameter(Model):
    """One parameter of a function or method, as callers see it."""

    name: str
    kind: Literal[
        "positional-only",
        "positional-or-keyword",
        "variadic",
        "keyword-only",
        "variadic-keyword",
    ]
    annotation: str
    """The declared type as pyright prints it: compared whole, never taken apart."""
    has_default: bool


class Signature(Model):
    """A function's or method's signature.

    Named by its dotted name inside its module: `submit`, `Claude.ask`.
    """

    name: str
    parameters: list[Parameter]
    returns: str
    """The declared return type as pyright prints it."""


class Surface(Model):
    """What other code can depend on in one file.

    The judge compares it before and after a change, for the public-API ask.
    """

    exported: list[str] = []
    """The names a package's root (`__init__.py`) binds; empty elsewhere."""
    classes: list[str] = []
    """Every class the module defines, by its dotted name inside the module."""
    signatures: list[Signature] = []


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


class Checker(ABC):
    """A typed engine the judge asks about the files of one project."""

    @abstractmethod
    def check(self, root: Path, sources: list[Source]) -> list[FileReport]:
        """Check the given files of the project at `root`, one report per file.

        Each report holds lup's findings and pyright's type errors, the file's
        directives, its public surface and its imports.
        """

    @abstractmethod
    def importers(self, root: Path, changed: list[Path]) -> list[FileReport]:
        """Re-check, for type errors only, the files that import any of `changed`."""
