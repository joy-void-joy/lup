"""Repoint every import of a module that moved between the two halves.

Deciding a utility belongs in the library rather than the application is a
one-line judgement and a hundred-line consequence: the module moves, and
every site that named it has to say the new name. Doing that by hand is
where the judgement gets abandoned, so the mechanical half is a command.

The rewrite is token surgery, not text surgery. ``tokenize`` reports every
token with its exact position and ``untokenize`` puts the untouched ones back
byte for byte, so a dotted module path in an import statement is replaced
while the spacing, the parenthesized continuation, and the comment beside it
survive unexamined. A module path appearing anywhere else — a log line, a
docstring naming the old home, a path in a comment — is not a token run in an
import statement and is never matched; :func:`surviving_mentions` reports
those for a human to read instead.

One form is deliberately left alone: ``from package import submodule`` is the
same tokens as importing a name from that package, and rewriting it would
mean guessing which. The repository's conventions ask for
``from module import symbol`` anyway, so the guess is not worth the reach —
such a site fails the type check with an unresolved import rather than
passing quietly, which is the outcome that gets it fixed.
"""

import ast
import io
import tokenize
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict

SOURCE_SUFFIXES = (".py", ".pyi")


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


class Relocation(BaseModel):
    """One module path that moved, and where it moved to, as name tokens.

    Held as parts rather than as dotted text because that is what the rewrite
    splices: a run of ``NAME`` tokens replaces a run of ``NAME`` tokens, and
    the reading that turns a path into names happens once, at the boundary
    where somebody typed one.
    """

    model_config = ConfigDict(frozen=True)

    old: list[str]
    new: list[str]


class ModuleRun(BaseModel):
    """The token span naming one module path, as indexes into the token list."""

    model_config = ConfigDict(frozen=True)

    start: int
    end: int


class RelocationEdit(BaseModel):
    """One file the rewrite changed, and how many imports it repointed."""

    model_config = ConfigDict(frozen=True)

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
    ``import`` where no ``from`` preceded it on that logical line. Names after
    an ``import`` that follows a ``from`` are the imported symbols, which are
    not module paths and must not be rewritten.
    """

    def found() -> Iterator[ModuleRun]:
        from_seen = False
        for index, token in enumerate(tokens):
            if token.type in (tokenize.NEWLINE, tokenize.NL):
                from_seen = False
                continue
            if token.type != tokenize.NAME:
                continue
            if token.string == "from":
                from_seen = True
            elif token.string != "import" or from_seen:
                continue
            if index + 1 < len(tokens) and tokens[index + 1].type == tokenize.NAME:
                yield ModuleRun(start=index + 1, end=dotted_run(tokens, index + 1))

    return list(found())


def renamed_run(
    tokens: list[tokenize.TokenInfo], run: ModuleRun, moves: list[Relocation]
) -> list[str] | None:
    """The replacement name tokens for one module run, if it moved.

    A move matches the module it names and every module beneath it, so
    relocating a package carries its submodules without each being declared.
    """
    named = [
        token.string for token in tokens[run.start : run.end + 1] if token.string != "."
    ]
    for move in moves:
        if named[: len(move.old)] == move.old:
            return [*move.new, *named[len(move.old) :]]
    return None


def relocate_in_file(path: Path, moves: list[Relocation]) -> RelocationEdit | None:
    """Repoint every import in one file, or report that none named a mover."""
    text = path.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    rewritten = list(tokens)
    repointed = 0
    for run in module_runs(tokens):
        renamed = renamed_run(tokens, run, moves)
        names = [
            index
            for index in range(run.start, run.end + 1)
            if tokens[index].type == tokenize.NAME
        ]
        # A rename that changes the path's depth cannot be spliced token for
        # token, so it is declined rather than half-applied.
        if renamed is None or len(renamed) != len(names):
            continue
        for index, replacement in zip(names, renamed, strict=True):
            rewritten[index] = rewritten[index]._replace(string=replacement)
        repointed += 1
    if not repointed:
        return None
    path.write_text(tokenize.untokenize(rewritten), encoding="utf-8")
    return RelocationEdit(path=path, imports=repointed)


def source_files(roots: list[Path]) -> list[Path]:
    """Every Python source file beneath the given roots, in a stable order."""
    return sorted(
        path
        for root in roots
        for path in root.rglob("*")
        if path.suffix in SOURCE_SUFFIXES and "__pycache__" not in path.parts
    )


def relocate(roots: list[Path], moves: list[Relocation]) -> list[RelocationEdit]:
    """Repoint every import beneath ``roots``, reporting each file changed."""
    edits = [relocate_in_file(path, moves) for path in source_files(roots)]
    return [edit for edit in edits if edit is not None]


def surviving_mentions(roots: list[Path], moves: list[Relocation]) -> list[str]:
    """Every remaining mention of a moved module, wherever it is not an import.

    Not necessarily wrong — prose about where something used to live is a
    legitimate thing to write — so this reports and the reader decides.
    """
    return [
        f"{path}:{number}: {line.strip()}"
        for path in source_files(roots)
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if any(".".join(move.old) in line for move in moves)
    ]
