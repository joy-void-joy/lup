"""Move a module between the two halves, and repoint every import of it.

Deciding a utility belongs in the library rather than the application is a
one-line judgement and a hundred-line consequence: the module moves, and
every site that named it has to say the new name. Doing that by hand is
where the judgement gets abandoned, so the mechanical half is a command.

Both halves, and that is the correction. Repointing importers while leaving
the file where it was is a tree in which nothing resolves, reported as a
success — the type check names it a step later, as an unresolved import,
detached from the command that produced it.

Tokens decide, text applies. ``tokenize`` reports every token with its exact
position, so a dotted module path in an import statement is located by
grammar rather than by pattern; the replacement is then spliced over that one
span, leaving the spacing, the parenthesized continuation, and the comment
beside it byte for byte untouched. Splicing a span rather than swapping token
for token is what lets a path change depth — a flat module moving under a
subpackage is the ordinary relocation, and three names do not fit where two
were. A module path appearing anywhere else — a log line, a docstring naming
the old home, a path in a comment — is not a module run in an import
statement and is never matched; :func:`surviving_mentions` reports those for
a human to read instead.

One form is deliberately left alone: ``from package import submodule`` is the
same tokens as importing a name from that package, and rewriting it would
mean guessing which. The repository's conventions ask for
``from module import symbol`` anyway, so the guess is not worth the reach —
such a site fails the type check with an unresolved import rather than
passing quietly, which is the outcome that gets it fixed. It is named among
the surviving mentions as well, found by the grammar: the dotted path is
never written whole there, so the text search that finds prose cannot see it.
"""

import ast
import io
import tokenize
from collections.abc import Collection, Iterator
from pathlib import Path

import sh
from pydantic import BaseModel

from lup.execution.shell import git

SOURCE_SUFFIXES = (".py", ".pyi")
"""Which files a sweep reads, for a caller that does not say.

The rewrite itself is Python's grammar and only ever will be, but what a
repository wants swept is a wider question than that: a tree carrying its
module paths in generated stubs or a sibling language passes the suffixes it
means rather than accepting these two.
"""


def dotted_parts(node: ast.expr) -> list[str] | None:
    """The names an attribute chain spells, outermost last."""
    match node:
        case ast.Name(id=name):
            return [name]
        case ast.Attribute(value=inner, attr=attribute):
            head = dotted_parts(inner)
            return None if head is None else [*head, attribute]
        case _:
            return None


def name_parts(dotted: str) -> list[str] | None:
    """The name tokens a dotted module path is made of, or None if it is not one.

    A module path is an expression in Python's own grammar — a name, or an
    attribute chain over one — so parsing it as that is both how the parts
    are read and how a typo is caught before it is used to rewrite a file.
    """
    try:
        return dotted_parts(ast.parse(dotted, mode="eval").body)
    except SyntaxError:
        return None


class Relocation(BaseModel, frozen=True):
    """One module path that moved, and where it moved to, as name tokens.

    Held as parts rather than as dotted text because that is what the rewrite
    splices: a run of ``NAME`` tokens replaces a run of ``NAME`` tokens, and
    the reading that turns a path into names happens once, at the boundary
    where somebody typed one.
    """

    old: list[str]
    new: list[str]


def destination(named: list[str], moves: list[Relocation]) -> list[str] | None:
    """Where a module path lands, if one of the moves carries it.

    A move carries the module it names and every module beneath it, so
    relocating a package takes its submodules without each being declared.
    Where two moves match, the longer one decides: a module declared on its own
    has its file carried to the name that move spells, and following its
    package's move instead would point the import at a module that is not
    there. The result may be longer or shorter than what it replaces — a move
    into or out of a subpackage changes the path's depth.
    """
    carrying = [move for move in moves if named[: len(move.old)] == move.old]
    if not carrying:
        return None
    move = max(carrying, key=lambda move: len(move.old))
    return [*move.new, *named[len(move.old) :]]


class ModuleRun(BaseModel, frozen=True):
    """The token span naming one module path, as indexes into the token list."""

    start: int
    end: int

    def named(self, tokens: list[tokenize.TokenInfo]) -> list[str]:
        """The names this run spells, without the dots between them."""
        return [
            token.string
            for token in tokens[self.start : self.end + 1]
            if token.string != "."
        ]


class ModuleEdit(BaseModel, frozen=True):
    """One module path to respell, as a span on one line of the source."""

    row: int
    start: int
    end: int
    text: str


class RelocationEdit(BaseModel, frozen=True):
    """One file the rewrite changed, and how many imports it repointed."""

    path: Path
    imports: int


def dotted_run(tokens: list[tokenize.TokenInfo], start: int) -> int:
    """The index of the last token in the ``a.b.c`` run beginning at ``start``."""
    position = start
    while position + 2 < len(tokens):
        following = tokens[position + 1]
        if following.type != tokenize.OP or following.string != ".":
            break
        if tokens[position + 2].type != tokenize.NAME:
            break
        position += 2
    return position


def module_runs(tokens: list[tokenize.TokenInfo]) -> list[ModuleRun]:
    """Every token span naming a module in an import statement.

    A module path is named in exactly two places: after ``from``, and after
    ``import`` where no ``from`` preceded it on that logical line — including
    after each comma in that form, because ``import a.b, c.d`` names two.
    Names after an ``import`` that follows a ``from`` are the imported
    symbols, which are not module paths and must not be rewritten.
    """

    def run_at(index: int) -> Iterator[ModuleRun]:
        """The module run starting just past ``index``, if a name is there."""
        if index + 1 < len(tokens) and tokens[index + 1].type == tokenize.NAME:
            yield ModuleRun(start=index + 1, end=dotted_run(tokens, index + 1))

    def found() -> Iterator[ModuleRun]:
        from_seen = False
        listing = False
        for index, token in enumerate(tokens):
            match (token.type, token.string):
                case (tokenize.NEWLINE | tokenize.NL, _):
                    from_seen = listing = False
                case (tokenize.OP, ",") if listing:
                    yield from run_at(index)
                case (tokenize.NAME, "from"):
                    from_seen = True
                    yield from run_at(index)
                case (tokenize.NAME, "import") if not from_seen:
                    listing = True
                    yield from run_at(index)

    return list(found())


def module_edits(
    tokens: list[tokenize.TokenInfo], moves: list[Relocation]
) -> list[ModuleEdit]:
    """Every module path in an import statement that one of the moves renames.

    A run continued across lines is declined rather than half-applied: the
    splice is a span on one line, and a path broken over two is rare enough
    that reporting it as a surviving mention beats guessing at the join.
    """

    def found() -> Iterator[ModuleEdit]:
        for run in module_runs(tokens):
            renamed = destination(run.named(tokens), moves)
            start, end = tokens[run.start].start, tokens[run.end].end
            if renamed is None or start[0] != end[0]:
                continue
            yield ModuleEdit(
                row=start[0], start=start[1], end=end[1], text=".".join(renamed)
            )

    return list(found())


def apply_edits(text: str, edits: list[ModuleEdit]) -> str:
    """Splice every respelled module path into the source that named it.

    Rightmost first, so an edit's recorded columns still address the line it
    was read from when two imports share one.
    """
    lines = text.splitlines(keepends=True)
    for edit in sorted(edits, key=lambda edit: edit.start, reverse=True):
        line = lines[edit.row - 1]
        lines[edit.row - 1] = f"{line[: edit.start]}{edit.text}{line[edit.end :]}"
    return "".join(lines)


def relocate_in_file(path: Path, moves: list[Relocation]) -> RelocationEdit | None:
    """Repoint every import in one file, or report that none named a mover."""
    text = path.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    edits = module_edits(tokens, moves)
    if not edits:
        return None
    path.write_text(apply_edits(text, edits), encoding="utf-8")
    return RelocationEdit(path=path, imports=len(edits))


def source_files(
    roots: list[Path], suffixes: Collection[str] = SOURCE_SUFFIXES
) -> list[Path]:
    """Every source file beneath the given roots, once each, in a stable order.

    Once each because the roots may nest: a package root a module path
    resolves against sits inside the sweep root that covers the whole
    workspace, and a file reached through both would be read, rewritten and
    reported twice — the second pass finding nothing, and the count telling a
    reader the file had two imports where it had one.
    """
    return sorted(
        {
            path
            for root in roots
            for path in root.rglob("*")
            if path.suffix in suffixes and "__pycache__" not in path.parts
        }
    )


class MovedModule(BaseModel, frozen=True):
    """One module file the relocation carried, and where it landed."""

    old: Path
    new: Path


def planned_move(roots: list[Path], move: Relocation) -> MovedModule | None:
    """Where the module's file is, and where its new name puts it, before either moves.

    ``None`` where no root holds the module, which is a caller who moved the
    file first and is repointing imports after.
    """

    def destination(source_root: Path) -> Path:
        """The root the new name belongs under, which need not be the old one.

        A module crossing packages — an application's becoming the library's —
        spells a top-level name another root already holds, and resolving its
        destination against the root it came from writes a second tree beside
        the first: `src/lup/devtools/...` next to the application, where
        `packages/lup/src/lup/` is the package that owns the name. The root
        declaring the new top-level name is the one that takes it, and a name
        no root declares stays where it was, which is every move within one
        package.

        Declaring it means holding it as a package, which is what the import
        the move rewrites resolves against. A root is also a sweep's, named
        wide so every importer is found — `packages/` holds a directory
        called `lup` that no import has ever reached, and matching the name
        alone would land the module in it.
        """
        return next(
            (root for root in roots if (root / move.new[0] / "__init__.py").is_file()),
            source_root,
        )

    return next(
        (
            MovedModule(
                old=source, new=destination(root).joinpath(*move.new).with_suffix(".py")
            )
            for root in roots
            if (source := root.joinpath(*move.old).with_suffix(".py")).is_file()
        ),
        None,
    )


def occupied(roots: list[Path], moves: list[Relocation]) -> list[MovedModule]:
    """Every move whose module is here to carry and whose destination is taken.

    Asked of every move before anything is touched, because the file and its
    importers are one relocation: a module that cannot land has no business
    having its imports repointed. Doing that anyway -- carrying nothing and
    rewriting everything -- aimed every importer at the module already there,
    and a caller who reads the moved-and-repointed report as done learns
    otherwise from a tree that resolves the old names against the wrong file.
    """
    return [
        plan
        for move in moves
        if (plan := planned_move(roots, move)) is not None and plan.new.exists()
    ]


def carry_module(roots: list[Path], move: Relocation) -> MovedModule | None:
    """Move the module's own file to the path its new name spells.

    The half a caller should never have been left holding. Repointing every
    importer and leaving the file where it was produces a tree where nothing
    resolves -- which the type check does catch, but only after this command
    reported success, so the failure arrives detached from what caused it.

    Moved through ``git`` where the file is tracked, so the history follows
    the module instead of reading as a delete beside an unrelated add. An
    untracked file is renamed plainly.

    Two cases are deliberately quiet here. A source that is not there is a
    caller doing the same relocation in the other order -- file first,
    imports after -- and refusing that would punish the tidier sequence. A
    destination that already exists is left alone, because overwriting one
    module with another is not a relocation; the command refuses that case
    whole, through :func:`occupied`, before this or any import rewrite runs.
    """

    def tracked(path: Path) -> bool:
        """Whether git is keeping this file's history, and can be asked to move it.

        A tree that is not a repository at all answers the same way a file git
        has never seen does — plainly rename it — so the exit code and the
        empty listing collapse into one answer here rather than becoming two
        branches at the call.
        """
        try:
            return bool(git.lines("-C", str(path.parent), "ls-files", "--", path.name))
        except sh.ErrorReturnCode:
            return False

    plan = planned_move(roots, move)
    if plan is None or plan.new.exists():
        return None
    plan.new.parent.mkdir(parents=True, exist_ok=True)
    if tracked(plan.old):
        # Asked of the repository holding the file, with both operands
        # resolved: a root is wherever a module path happens to resolve
        # against and need be no repository at all, so `-C <root>` with
        # operands spelled from the caller's directory reads each of them
        # twice — `packages/lup/src/packages/lup/src/...`, which git
        # reports as a bad source rather than as a path it built.
        top = git.out("-C", str(plan.old.parent), "rev-parse", "--show-toplevel")
        git.out("-C", top, "mv", str(plan.old.resolve()), str(plan.new.resolve()))
    else:
        plan.old.rename(plan.new)
    return plan


def relocate(
    roots: list[Path],
    moves: list[Relocation],
    suffixes: Collection[str] = SOURCE_SUFFIXES,
) -> list[RelocationEdit]:
    """Repoint every import beneath ``roots``, reporting each file changed."""
    edits = [relocate_in_file(path, moves) for path in source_files(roots, suffixes)]
    return [edit for edit in edits if edit is not None]


def surviving_mentions(
    roots: list[Path],
    moves: list[Relocation],
    suffixes: Collection[str] = SOURCE_SUFFIXES,
) -> list[str]:
    """Every remaining mention of a moved module, wherever it is not an import.

    Not necessarily wrong — prose about where something used to live is a
    legitimate thing to write — so this reports and the reader decides. A
    moved module imported by name from its package is reported too, though
    it is always wrong: the rewrite leaves that spelling alone, and it is the
    one a search for the dotted path cannot find.
    """

    def mentions(path: Path) -> Iterator[str]:
        text = path.read_text(encoding="utf-8")
        declined = {number for number in submodule_imports(text, moves)}
        for number, line in enumerate(text.splitlines(), start=1):
            if number in declined or any(".".join(move.old) in line for move in moves):
                yield f"{path}:{number}: {line.strip()}"

    return [
        mention for path in source_files(roots, suffixes) for mention in mentions(path)
    ]


def submodule_imports(text: str, moves: list[Relocation]) -> list[int]:
    """The lines importing a moved module by name from the package holding it.

    ``from package import submodule`` never writes the module's dotted path
    whole, so it is read by the grammar: an imported name that, joined to the
    package it is imported from, spells a moved module. A source that does
    not parse names nothing here, and its text mentions still are.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    moved = [move.old for move in moves]

    def named(node: ast.AST) -> Iterator[int]:
        match node:
            case ast.ImportFrom(module=str(module), names=names, level=0):
                package = name_parts(module) or []
                yield from (
                    alias.lineno for alias in names if [*package, alias.name] in moved
                )
            case _:
                return

    return sorted(line for node in ast.walk(tree) for line in named(node))
