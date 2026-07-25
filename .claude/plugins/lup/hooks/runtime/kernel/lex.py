# lup: ignore[empty-collection, tuple-shape]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Shell lexing: tokens, redirections, heredocs, and segment grouping."""

import posixpath
from typing import Literal

from .decision import (
    BACKTICK_REASON,
    KernelDecision,
    SUBSTITUTION_REASON,
    SUBSTITUTION_SENTINEL,
    unjudged,
)
from .words import is_repository_tmp_script, is_session_scratch_target


class ShellToken:
    """One lexed shell token: a word, an operator, or a substituted command.

    ``procsub`` carries a ``<(...)`` inner command and ``cmdsub`` a ``$(...)``
    one; both are classified recursively. ``quoted`` records whether any part
    of a word came from quotes or escapes, which decides whether a heredoc
    delimiter suppresses body expansion.
    """

    kind: Literal["word", "op", "procsub", "cmdsub"]
    text: str
    quoted: bool

    def __init__(
        self,
        kind: Literal["word", "op", "procsub", "cmdsub"],
        text: str,
        quoted: bool = False,
    ) -> None:
        self.kind = kind
        self.quoted = quoted
        self.text = text


def read_process_substitution(command: str, position: int) -> tuple[str | None, int]:
    """Scan a balanced ``<(...)`` body, honoring quotes, returning its inner text."""
    start = position
    depth = 1
    length = len(command)
    while position < length:
        character = command[position]
        if character == "'":
            closing = command.find("'", position + 1)
            if closing == -1:
                return None, position
            position = closing + 1
            continue
        if character == '"':
            position += 1
            while position < length and command[position] != '"':
                position += 2 if command[position] == "\\" else 1
            if position >= length:
                return None, position
            position += 1
            continue
        if character == "\\":
            position += 2
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return command[start:position], position + 1
        position += 1
    return None, position


def read_command_substitution(command: str, position: int) -> tuple[str | None, int]:
    """Scan a balanced ``$(...)`` expansion, returning its inner text.

    ``position`` sits on the ``$``; the returned end position follows the
    closing parenthesis, so ``command[position:end]`` is the raw expansion
    the enclosing word keeps as its opaque spelling.
    """
    return read_process_substitution(command, position + 2)


def read_redirection(command: str, position: int) -> tuple[str, int]:
    """Read a maximal redirection operator, returning its text and end position."""
    start = position
    length = len(command)
    if command[position] == "&":
        position += 1
    core = command[position]
    position += 1
    if position < length and command[position] == core:
        position += 1
        if core == "<" and position < length and command[position] == "<":
            position += 1
        elif core == "<" and position < length and command[position] == "-":
            position += 1
    if position < length and command[position] == "&":
        position += 1
        while position < length and (
            command[position].isdigit() or command[position] == "-"
        ):
            position += 1
    return command[start:position], position


def read_control(command: str, position: int) -> tuple[str, int]:
    """Read a maximal control operator, returning its text and end position."""
    character = command[position]
    length = len(command)
    if character == "&":
        if position + 1 < length and command[position + 1] == "&":
            return "&&", position + 2
        return "&", position + 1
    if character == "|":
        if position + 1 < length and command[position + 1] == "|":
            return "||", position + 2
        if position + 1 < length and command[position + 1] == "&":
            return "|&", position + 2
        return "|", position + 1
    if character == ";":
        if command[position : position + 3] == ";;&":
            return ";;&", position + 3
        if command[position : position + 2] in (";;", ";&"):
            return command[position : position + 2], position + 2
        return ";", position + 1
    return character, position + 1


def read_arithmetic(command: str, position: int) -> tuple[str | None, int]:
    """Scan a balanced ``$((...))`` expansion whose interior is pure data.

    ``position`` sits on the ``$``. Arithmetic cannot run commands, so the
    expansion joins its word verbatim — unless the interior nests a command
    substitution, in which case the scan stops on it and returns ``None``.
    """
    depth = 2
    cursor = position + 3
    length = len(command)
    while cursor < length:
        character = command[cursor]
        if character == "`" or command[cursor : cursor + 2] == "$(":
            return None, cursor
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return command[position : cursor + 1], cursor + 1
        cursor += 1
    return None, cursor


def arithmetic_token(command: str, position: int) -> tuple[str, int] | KernelDecision:
    """Read one ``$((...))`` expansion or explain why it cannot join a word."""
    expansion, end = read_arithmetic(command, position)
    if expansion is not None:
        return expansion, end
    if command[end : end + 2] == "$(" or command[end : end + 1] == "`":
        return KernelDecision("deny", SUBSTITUTION_REASON)
    return unjudged("arithmetic expansion does not parse")


def without_leading_tabs(line: str) -> str:
    """The line with its ``<<-``-style leading tab indentation removed."""
    first = next(
        (index for index, character in enumerate(line) if character != "\t"),
        len(line),
    )
    return line[first:]


def read_heredoc_bodies(
    command: str, position: int, pending: list[tuple[str, bool]]
) -> int | KernelDecision:
    """Consume heredoc bodies after a newline, gating unquoted expansion.

    A quoted delimiter makes the body literal data. An unquoted one lets the
    shell substitute inside the body, so any substitution syntax there is
    refused with the quoting recipe.
    """
    for delimiter, is_quoted in pending:
        lines: list[str] = []
        terminated = False
        while position <= len(command):
            newline = command.find("\n", position)
            end = len(command) if newline == -1 else newline
            line = command[position:end]
            position = end + 1
            if line == delimiter or without_leading_tabs(line) == delimiter:
                terminated = True
                break
            lines.append(line)
            if newline == -1:
                break
        if not terminated:
            return unjudged("heredoc does not terminate")
        if not is_quoted:
            body = "\n".join(lines)
            if "`" in body or "$(" in body:
                return KernelDecision(
                    "deny",
                    "an unquoted heredoc substitutes commands — quote the"
                    " delimiter (<<'EOF') to make the body literal",
                )
    return position


def tokenize_shell(command: str) -> list[ShellToken] | KernelDecision:
    """Lex a command into words and operators, refusing opaque or unsafe syntax.

    Heredoc bodies are consumed here: a delimiter registered by a ``<<``
    redirection queues until the next newline, where the body lines are
    skipped as data (quoted delimiter) or gated on substitution syntax
    (unquoted delimiter).
    """
    tokens: list[ShellToken] = []
    word: list[str] = []
    started = False
    quoted = False
    heredoc_expected = False
    pending_heredocs: list[tuple[str, bool]] = []
    length = len(command)
    position = 0

    def flush() -> None:
        nonlocal started, quoted, heredoc_expected
        if started:
            tokens.append(ShellToken("word", "".join(word), quoted))
            if heredoc_expected:
                pending_heredocs.append(("".join(word), quoted))
                heredoc_expected = False
            word.clear()
            started = False
            quoted = False

    while position < length:
        character = command[position]
        if character == "'":
            closing = command.find("'", position + 1)
            if closing == -1:
                return unjudged("shell quoting does not parse")
            word.extend(command[position + 1 : closing])
            started = True
            quoted = True
            position = closing + 1
            continue
        if character == '"':
            position += 1
            quoted = True
            while position < length and command[position] != '"':
                inner = command[position]
                if inner == "\\" and position + 1 < length:
                    word.append(command[position + 1])
                    position += 2
                    continue
                if inner == "$" and command[position + 1 : position + 3] == "((":
                    outcome = arithmetic_token(command, position)
                    if isinstance(outcome, KernelDecision):
                        return outcome
                    expansion, position = outcome
                    word.append(expansion)
                    continue
                if inner == "`":
                    return KernelDecision("deny", BACKTICK_REASON)
                if (
                    inner == "$"
                    and position + 1 < length
                    and command[position + 1] == "("
                ):
                    body, end = read_command_substitution(command, position)
                    if body is None:
                        return unjudged("command substitution does not parse")
                    tokens.append(ShellToken("cmdsub", body))
                    word.append(SUBSTITUTION_SENTINEL)
                    position = end
                    continue
                word.append(inner)
                position += 1
            if position >= length:
                return unjudged("shell quoting does not parse")
            started = True
            position += 1
            continue
        if character == "\\":
            if position + 1 < length and command[position + 1] != "\n":
                word.append(command[position + 1])
                started = True
                quoted = True
            position += 2
            continue
        if character in " \t\r":
            flush()
            position += 1
            continue
        if character == "$" and command[position + 1 : position + 3] == "((":
            outcome = arithmetic_token(command, position)
            if isinstance(outcome, KernelDecision):
                return outcome
            expansion, position = outcome
            word.append(expansion)
            started = True
            continue
        if character == "`":
            return KernelDecision("deny", BACKTICK_REASON)
        if character == "$" and position + 1 < length and command[position + 1] == "(":
            body, end = read_command_substitution(command, position)
            if body is None:
                return unjudged("command substitution does not parse")
            tokens.append(ShellToken("cmdsub", body))
            word.append(SUBSTITUTION_SENTINEL)
            started = True
            position = end
            continue
        if character == ">" and position + 1 < length and command[position + 1] == "(":
            return KernelDecision(
                "ask", "writing process substitution is never auto-allowed"
            )
        if character == "<" and position + 1 < length and command[position + 1] == "(":
            if started:
                return unjudged("process substitution inside a word is not classified")
            inner, end = read_process_substitution(command, position + 2)
            if inner is None:
                return unjudged("process substitution does not parse")
            tokens.append(ShellToken("procsub", inner))
            position = end
            continue
        if character == "#" and not started:
            newline = command.find("\n", position)
            if newline == -1:
                break
            position = newline
            continue
        if character in "<>" or (
            character == "&" and position + 1 < length and command[position + 1] == ">"
        ):
            fd = ""
            if started and word and all(digit.isdigit() for digit in word):
                fd = "".join(word)
                word.clear()
                started = False
                quoted = False
            else:
                flush()
            operator, position = read_redirection(command, position)
            tokens.append(ShellToken("op", fd + operator))
            if "<<" in operator and "<<<" not in operator:
                heredoc_expected = True
            continue
        if character in ";&|\n":
            flush()
            operator, position = read_control(command, position)
            tokens.append(ShellToken("op", operator))
            if operator == "\n" and pending_heredocs:
                consumed = read_heredoc_bodies(command, position, pending_heredocs)
                if isinstance(consumed, KernelDecision):
                    return consumed
                position = consumed
                pending_heredocs.clear()
            continue
        if character == "(":
            if started:
                return unjudged(
                    "shell arrays and function definitions are not classified"
                )
            tokens.append(ShellToken("op", "("))
            position += 1
            continue
        if character == ")":
            flush()
            tokens.append(ShellToken("op", ")"))
            position += 1
            continue
        word.append(character)
        started = True
        position += 1
    flush()
    if heredoc_expected:
        return unjudged("heredoc has no delimiter")
    if pending_heredocs:
        return unjudged("heredoc does not terminate")
    return tokens


SENTINEL_OPS = ("(", ")", ";;", ";&", ";;&")


def is_control_operator(text: str) -> bool:
    """Return whether an operator token separates command segments."""
    return text in (";", "&", "&&", "||", "|", "|&", "\n")


def literal_target(word: str) -> bool:
    """Whether a redirection target names exactly the path it spells.

    Existence is established against the word as written, so a target
    carrying an unexpanded parameter, a substitution, or a tilde names a
    different file at run time than the one that was stat'd. Such a target
    never qualifies for the create-versus-overwrite relaxation, and keeps
    the strict verdict the operator alone earns.
    """
    return not any(marker in word for marker in ("$", "~", "`", SUBSTITUTION_SENTINEL))


def redirection_writes(operator: str) -> bool:
    """Whether one redirection operator opens its target for writing.

    Every writing form spells ``>``, which also separates them from the
    control operators that carry a following word of their own.
    """
    if ">" not in operator:
        return False
    if "<<" in operator and "<<<" not in operator:
        return False
    return not ("&" in operator and (operator[-1].isdigit() or operator[-1] == "-"))


def shell_write_targets(command: str, depth: int = 0) -> list[str]:
    """Name every path this command's redirections would open for writing.

    A caller that can reach the filesystem stats these and hands back the
    ones that already exist, so the kernel can tell creating a file from
    overwriting one without ever reading the filesystem itself. A command
    that does not lex yields nothing and keeps its unjudged verdict.
    """
    tokens = tokenize_shell(command)
    if isinstance(tokens, KernelDecision):
        return []
    targets: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind in ("cmdsub", "procsub"):
            if depth < 2:
                targets.extend(shell_write_targets(token.text, depth + 1))
            index += 1
            continue
        if token.kind != "op" or not redirection_writes(token.text):
            index += 1
            continue
        following = index + 1
        if following < len(tokens) and tokens[following].kind == "word":
            targets.append(tokens[following].text)
            index = following + 1
            continue
        index += 1
    return targets


def resolve_redirection(
    tokens: list[ShellToken],
    index: int,
    heredoc_fed: bool = False,
    existing_targets: list[str] | None = None,
) -> tuple[KernelDecision | None, int]:
    """Classify one redirection, consuming its target and stripping safe forms.

    A write that would overwrite an existing file is the destructive case: a
    heredoc-fed one denies toward the Edit tool and tmp/*.py scripts, and any
    other asks. Creating a file destroys nothing, so it passes once the
    caller has established the target does not exist. ``existing_targets`` of
    ``None`` means no caller established anything, and every target is
    treated as already there.
    """
    operator = tokens[index].text
    if "<<" in operator and "<<<" not in operator:
        target = index + 1
        if target >= len(tokens) or tokens[target].kind != "word":
            return unjudged("heredoc has no delimiter"), index + 1
        return None, target + 1
    if "&" in operator and (operator[-1].isdigit() or operator[-1] == "-"):
        return None, index + 1
    target = index + 1
    if target >= len(tokens) or tokens[target].kind != "word":
        return (
            KernelDecision("ask", "file redirection is never auto-allowed"),
            index + 1,
        )
    if "<" in operator:
        return None, target + 1
    if posixpath.normpath(tokens[target].text) == "/dev/null":
        return None, target + 1
    if is_repository_tmp_script(tokens[target].text):
        return None, target + 1
    if is_session_scratch_target(tokens[target].text):
        return None, target + 1
    if (
        existing_targets is not None
        and literal_target(tokens[target].text)
        and tokens[target].text not in existing_targets
    ):
        return None, target + 1
    if heredoc_fed:
        return (
            KernelDecision(
                "deny",
                "authoring a file through a heredoc bypasses the edit policy"
                " — write a tmp/*.py script or use the Edit tool",
            ),
            target + 1,
        )
    return (
        KernelDecision("ask", "file redirection is never auto-allowed"),
        target + 1,
    )


def parse_shell_words(
    command: str, depth: int = 0, existing_targets: list[str] | None = None
) -> list[list[str]] | KernelDecision:
    """Group lexed tokens into command segments, resolving safe redirections.

    A read-side process substitution contributes a ``/dev/fd`` placeholder to
    its enclosing segment and its inner command joins the segment list, so the
    caller classifies it exactly like a piped command. Grouping parentheses
    and case terminators become single-word sentinel segments the segment
    walker interprets, and ``[[ ... ]]`` folds into one read-only test word.
    """
    tokens = tokenize_shell(command)
    if isinstance(tokens, KernelDecision):
        return tokens

    def substituted_segments(text: str) -> list[list[str]] | KernelDecision:
        if depth >= 2:
            return unjudged("command substitution nests too deeply")
        return parse_shell_words(text, depth + 1, existing_targets)

    heredoc_fed = any(
        token.kind == "op" and "<<" in token.text and "<<<" not in token.text
        for token in tokens
    )
    segments: list[list[str]] = []
    current: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "word" and token.text == "[[" and not token.quoted:
            fold = index + 1
            while fold < len(tokens) and not (
                tokens[fold].kind == "word" and tokens[fold].text == "]]"
            ):
                if tokens[fold].kind == "procsub":
                    return unjudged(
                        "process substitution inside [[ ]] is not classified"
                    )
                if tokens[fold].kind == "cmdsub":
                    folded = substituted_segments(tokens[fold].text)
                    if isinstance(folded, KernelDecision):
                        return folded
                    segments.extend(folded)
                fold += 1
            if fold >= len(tokens):
                return unjudged("test expression does not parse")
            current.append("[[")
            index = fold + 1
            continue
        if token.kind == "word":
            current.append(token.text)
            index += 1
            continue
        if (
            token.kind == "op"
            and token.text == "("
            and current
            and current[-1] not in ("then", "else", "elif", "do", "if", "in", "!")
        ):
            return unjudged("shell function definitions are not classified")
        if token.kind == "op" and token.text in SENTINEL_OPS:
            if current:
                segments.append(current)
                current = []
            segments.append([token.text])
            index += 1
            continue
        if token.kind == "procsub":
            if depth >= 2:
                return unjudged("process substitution nests too deeply")
            inner = parse_shell_words(token.text, depth + 1, existing_targets)
            if isinstance(inner, KernelDecision):
                return inner
            segments.extend(inner)
            current.append("/dev/fd/63")
            index += 1
            continue
        if token.kind == "cmdsub":
            spliced = substituted_segments(token.text)
            if isinstance(spliced, KernelDecision):
                return spliced
            segments.extend(spliced)
            index += 1
            continue
        if is_control_operator(token.text):
            if current:
                segments.append(current)
                current = []
            index += 1
            continue
        verdict, index = resolve_redirection(
            tokens, index, heredoc_fed, existing_targets
        )
        if verdict is not None:
            return verdict
    if current:
        segments.append(current)
    if not segments:
        return unjudged("shell command has no executable segment")
    return segments
