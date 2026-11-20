"""What the engine answers about a file and its rules, as models: each mirrors the engine's own shape field for field (`engine/src/protocol.ts`), so a field renamed there fails here at once."""

from typing import Literal

from lup import Model
from lup_code_rules.directives import Directive

type Category = Literal["design", "spelling", "heuristic"]
"""When a finding is told, and whether the gate fails on it:
- `design`, a choice others build on: told right after the write that makes
  it, and failing the gate;
- `spelling`, how a correct thing is written: listed at the gate alone, and
  failing it;
- `heuristic`, a guess over prose: listed at the gate alone, never failing it.

pyright's and ruff's findings are design's."""

type Owner = Literal["lup", "pyright", "ruff"]
"""Who found it: lup's rules, pyright's checks, or ruff's."""


class Position(Model):
    """A place in a file: its line and column, each counted from 1."""

    line: int
    column: int


class Span(Model):
    """Where a finding is, from its start to its end."""

    start: Position
    end: Position


class Finding(Model):
    """Something one of lup's rules, pyright or ruff found in a file."""

    path: str
    """The file, from the worktree's root."""
    span: Span
    owner: Owner
    rule: str
    """lup's rule, pyright's rule (`reportUnknownMemberType`) or ruff's code
    (`SLF001`): what an `ignore` names to keep it."""
    message: str
    """For lup's rules, what the check saw, then the rule's mistake; for
    pyright's and ruff's, their message."""
    steer: str = ""
    """For lup's rules, where the rule steers instead; empty for the others."""
    detail: str = ""
    """For lup's rules, what the check saw alone, which a report tells in place
    of the message once it has told the rule's mistake and steer; empty for the
    others."""
    category: Category = "design"
    """When it's told, and whether the gate fails on it: its rule's, filled in
    from the table for lup's rules."""
    fixable: bool = False
    """Whether a safe fix resolves it, which the gate's `--fix` applies: never
    told, since the fix changes nothing a reader decides."""


class Placed(Model):
    """Where one name of a file's public surface is written: the line its name is on."""

    kind: Literal["export", "class", "function"]
    name: str
    line: int


class Surface(Model):
    """What other code can depend on in one file: a package root's names, and the public classes, functions and methods it defines."""

    exported: list[str] = []
    classes: list[str] = []
    functions: list[str] = []
    places: list[Placed] = []


class FileReport(Model):
    """Everything the engine reports about one file: its findings, its `# lup:` comments, its public surface and its imports."""

    path: str
    findings: list[Finding] = []
    directives: list[Directive] = []
    surface: Surface = Surface()
    imports: list[str] = []


class Flagged(Model):
    """Code a rule flags, with the same code written the steer's way."""

    code: str
    rewritten: str


class Examples(Model):
    """A rule's specification: what it flags, each rewritten, and near misses it leaves alone."""

    flags: list[Flagged] = []
    passes: list[str] = []


class RuleInfo(Model):
    """One of lup's rules, as the engine's table holds it."""

    id: str
    mistake: str
    """The mistake it prevents, a sentence standing alone."""
    steer: str
    """Where it steers instead, a sentence standing alone."""
    category: Category
    examples: Examples
