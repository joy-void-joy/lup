# lup: ignore[empty-collection, string-split]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Shell variable bindings: which literal a name holds, and how it expands.

Every reader of a command asks what its words become once the shell expands
them, and each one answering it apart is how `S=f.py; sed -i … $S` came to be
judged against `f.py` by the classifier and against `$S` by the host that
produces the rewritten document -- two readings of one line, and the ask that
fell between them. These are the primitives the one binding pass over a
command's tokens is built from, so there is nothing left for a reader to
re-derive.
"""

import posixpath
from typing import TypedDict

from .roles import spells_its_path


class ShellBinding(TypedDict):
    """One frozen variable binding: a name, and its literal value or None.

    ``value`` is ``None`` where the word could not be read as a literal, which
    is what makes the binding opaque to every later substitution.
    """

    name: str
    value: str | None


def bind_name(
    bindings: tuple[ShellBinding, ...], name: str, value: str | None
) -> tuple[ShellBinding, ...]:
    """Rebind one name immutably, shadowing any earlier binding of it."""
    kept = tuple(pair for pair in bindings if pair["name"] != name)
    return (*kept, ShellBinding(name=name, value=value))


def literal_loop_word(word: str) -> bool:
    """A word whose runtime expansion is exactly its lexed text."""
    return not word.startswith(("~", "/dev/fd/")) and not any(
        character in "$*?[" for character in word
    )


def literal_value(word: str) -> bool:
    """Whether an assigned value is the string the shell stores.

    Both halves are needed: a glob character is stored unexpanded by an
    assignment but expanded again wherever the name is referenced, and a
    backtick or substitution sentinel is a value nobody here ran.
    """
    return literal_loop_word(word) and spells_its_path(word)


def pure_assignment_names(segment: list[str]) -> list[ShellBinding] | None:
    """The bindings of an assignment-only segment."""
    pairs: list[ShellBinding] = []
    for word in segment:
        name, separator, value = word.partition("=")
        if not separator or not name.isidentifier():
            return None
        pairs.append(
            ShellBinding(name=name, value=value if literal_value(value) else None)
        )
    return pairs


def variable_reference_end(word: str, position: int, name: str) -> int | None:
    """The index just past a ``$name``/``${name}`` reference at ``position``."""
    rest = word[position + 1 :]
    if rest.startswith("{" + name + "}"):
        return position + len(name) + 3
    if rest.startswith(name):
        follow = position + 1 + len(name)
        if follow >= len(word) or not (word[follow].isalnum() or word[follow] == "_"):
            return follow
    return None


def references_variable(word: str, name: str) -> bool:
    """Detect a live ``$name`` or ``${name}`` reference inside one shell word."""
    return any(
        character == "$" and variable_reference_end(word, position, name) is not None
        for position, character in enumerate(word)
    )


def substitute_variable(word: str, name: str, value: str) -> str:
    """Replace every ``$name``/``${name}`` reference in one word with ``value``."""
    pieces: list[str] = []
    position = 0
    while True:
        found = word.find("$", position)
        if found == -1:
            pieces.append(word[position:])
            return "".join(pieces)
        end = variable_reference_end(word, found, name)
        if end is None:
            pieces.append(word[position : found + 1])
            position = found + 1
            continue
        pieces.append(word[position:found])
        pieces.append(value)
        position = end


def bound_word(word: str, bindings: tuple[ShellBinding, ...]) -> str:
    """One word with every literal binding in scope expanded into it.

    An opaque binding is left as the reference it is, so a word that still
    carries a ``$`` afterwards is exactly a word nothing here could expand.
    """
    for binding in bindings:
        value = binding["value"]
        if value is not None:
            word = substitute_variable(word, binding["name"], value)
    return word


def assigning_operands(words: list[str]) -> list[str]:
    """The names a builtin could assign, read from its operands.

    Over-reads on purpose: `printf -v NAME` and `getopts spec NAME` are named
    by position, and taking every identifier-shaped operand costs only a
    substitution that did not happen, where missing one resolves a reference
    to a value the name no longer holds.
    """
    names: list[str] = []
    for word in words[1:]:
        name = word.partition("=")[0].removesuffix("+").partition("[")[0]
        if name.isidentifier():
            names.append(name)
    return names


# lup: ignore[library-default] — bash's own builtins that assign a named variable
ASSIGNING_BUILTINS = (
    "declare",
    "export",
    "getopts",
    "let",
    "local",
    "mapfile",
    "printf",
    "read",
    "readarray",
    "readonly",
    "typeset",
    "unset",
)
# lup: ignore[library-default] — the shell's builtins that run text as commands
EVALUATING_BUILTINS = ("eval", "source", ".")


def unsettled_assignments(
    words: list[str], executable: list[str], standing: bool
) -> list[str] | None:
    """Names one simple command assigns that a later reference cannot rely on.

    ``words`` is the command with its structure keywords stripped,
    ``executable`` what runs once leading assignments and wrappers are
    skipped, and ``standing`` whether a plain assignment here holds for every
    later word -- not inside a construct or subshell, not beside a pipe, and
    carrying no redirection. ``None`` means an ``eval`` or ``source`` could
    assign any name at all.
    """
    command = posixpath.basename(executable[0]) if executable else ""
    if command in EVALUATING_BUILTINS:
        return None
    names = [name for word in words for name in defaulted_names(word)]
    if words[0] in ("for", "select") and len(words) > 1:
        names.append(words[1])
    if command in ASSIGNING_BUILTINS:
        names.extend(assigning_operands(executable))
    names.extend(assigning_operands(["", *[word for word in words if "+=" in word]]))
    plain = pure_assignment_names(words)
    if plain is not None and not standing:
        names.extend(pair["name"] for pair in plain)
    return names


def defaulted_names(word: str) -> list[str]:
    """Names a ``${NAME:=value}`` or ``${NAME=value}`` expansion assigns."""
    names: list[str] = []
    for piece in word.split("${")[1:]:
        head = piece.partition("}")[0]
        name = head.partition("=")[0].removesuffix(":")
        if name != head and name.isidentifier():
            names.append(name)
    return names
