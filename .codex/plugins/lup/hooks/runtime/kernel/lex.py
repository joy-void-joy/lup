# lup: ignore[empty-collection]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Shell lexing: tokens, redirections, heredocs, and segment grouping."""

import posixpath
from typing import Literal, TypedDict

from .decision import (
    BACKTICK_REASON,
    KernelDecision,
    SUBSTITUTION_REASON,
    SUBSTITUTION_SENTINEL,
    unjudged,
)
from .archives import archive_write
from .roles import path_role, spells_its_path
from .rows import PathRoleRow, PathRuleRow
from .words import (
    SCRATCH_VERB_FLAGS,
    effective_command,
    git_restore_operands,
    path_verb_operands,
    protected_write_target,
    refuses_generated_plugin_target,
    uv_run_words,
)


class Scan(TypedDict):
    """A balanced scan's inner text, and the position just past its close.

    ``text`` is ``None`` when the construct never closed. Every caller turns
    that into an unjudged verdict rather than guessing at the remainder, so
    the position still says how far the scan got.
    """

    text: str | None
    end: int


class Lexeme(TypedDict):
    """One lexed operator or expansion, and the position just past it."""

    text: str
    end: int


class Heredoc(TypedDict):
    """A delimiter awaiting its body, and whether quoting made the body literal."""

    delimiter: str
    quoted: bool


class Redirection(TypedDict):
    """What classifying one redirection decided, and where to resume.

    ``decision`` of ``None`` means the redirection is safe and consumed;
    ``resume`` is the token index the caller continues from either way.
    """

    decision: KernelDecision | None
    resume: int


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


def read_process_substitution(command: str, position: int) -> Scan:
    """Scan a balanced ``<(...)`` body, honoring quotes, returning its inner text."""
    start = position
    depth = 1
    length = len(command)
    while position < length:
        character = command[position]
        if character == "'":
            closing = command.find("'", position + 1)
            if closing == -1:
                return Scan(text=None, end=position)
            position = closing + 1
            continue
        if character == '"':
            position += 1
            while position < length and command[position] != '"':
                position += 2 if command[position] == "\\" else 1
            if position >= length:
                return Scan(text=None, end=position)
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
                return Scan(text=command[start:position], end=position + 1)
        position += 1
    return Scan(text=None, end=position)


def read_command_substitution(command: str, position: int) -> Scan:
    """Scan a balanced ``$(...)`` expansion, returning its inner text.

    ``position`` sits on the ``$``; the returned end position follows the
    closing parenthesis, so ``command[position:end]`` is the raw expansion
    the enclosing word keeps as its opaque spelling.
    """
    return read_process_substitution(command, position + 2)


def read_redirection(command: str, position: int) -> Lexeme:
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
    return Lexeme(text=command[start:position], end=position)


def read_control(command: str, position: int) -> Lexeme:
    """Read a maximal control operator, returning its text and end position."""
    character = command[position]
    length = len(command)
    if character == "&":
        if position + 1 < length and command[position + 1] == "&":
            return Lexeme(text="&&", end=position + 2)
        return Lexeme(text="&", end=position + 1)
    if character == "|":
        if position + 1 < length and command[position + 1] == "|":
            return Lexeme(text="||", end=position + 2)
        if position + 1 < length and command[position + 1] == "&":
            return Lexeme(text="|&", end=position + 2)
        return Lexeme(text="|", end=position + 1)
    if character == ";":
        if command[position : position + 3] == ";;&":
            return Lexeme(text=";;&", end=position + 3)
        if command[position : position + 2] in (";;", ";&"):
            return Lexeme(text=command[position : position + 2], end=position + 2)
        return Lexeme(text=";", end=position + 1)
    return Lexeme(text=character, end=position + 1)


def read_arithmetic(command: str, position: int) -> Scan:
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
            return Scan(text=None, end=cursor)
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return Scan(text=command[position : cursor + 1], end=cursor + 1)
        cursor += 1
    return Scan(text=None, end=cursor)


def arithmetic_token(command: str, position: int) -> Lexeme | KernelDecision:
    """Read one ``$((...))`` expansion or explain why it cannot join a word."""
    scan = read_arithmetic(command, position)
    expansion = scan["text"]
    end = scan["end"]
    if expansion is not None:
        return Lexeme(text=expansion, end=end)
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
    command: str, position: int, pending: list[Heredoc]
) -> int | KernelDecision:
    """Consume heredoc bodies after a newline, gating unquoted expansion.

    A quoted delimiter makes the body literal data. An unquoted one lets the
    shell substitute inside the body, so any substitution syntax there is
    refused with the quoting recipe.
    """
    for heredoc in pending:
        delimiter = heredoc["delimiter"]
        is_quoted = heredoc["quoted"]
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
    pending_heredocs: list[Heredoc] = []
    length = len(command)
    position = 0

    def flush() -> None:
        nonlocal started, quoted, heredoc_expected
        if started:
            tokens.append(ShellToken("word", "".join(word), quoted))
            if heredoc_expected:
                pending_heredocs.append(Heredoc(delimiter="".join(word), quoted=quoted))
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
                    position = outcome["end"]
                    word.append(outcome["text"])
                    continue
                if inner == "`":
                    return KernelDecision("deny", BACKTICK_REASON)
                if (
                    inner == "$"
                    and position + 1 < length
                    and command[position + 1] == "("
                ):
                    substitution = read_command_substitution(command, position)
                    body = substitution["text"]
                    if body is None:
                        return unjudged("command substitution does not parse")
                    tokens.append(ShellToken("cmdsub", body))
                    word.append(SUBSTITUTION_SENTINEL)
                    position = substitution["end"]
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
            position = outcome["end"]
            word.append(outcome["text"])
            started = True
            continue
        if character == "`":
            return KernelDecision("deny", BACKTICK_REASON)
        if character == "$" and position + 1 < length and command[position + 1] == "(":
            substitution = read_command_substitution(command, position)
            body = substitution["text"]
            if body is None:
                return unjudged("command substitution does not parse")
            tokens.append(ShellToken("cmdsub", body))
            word.append(SUBSTITUTION_SENTINEL)
            started = True
            position = substitution["end"]
            continue
        if character == ">" and position + 1 < length and command[position + 1] == "(":
            return KernelDecision(
                "ask", "writing process substitution is never auto-allowed"
            )
        if character == "<" and position + 1 < length and command[position + 1] == "(":
            if started:
                return unjudged("process substitution inside a word is not classified")
            substitution = read_process_substitution(command, position + 2)
            inner = substitution["text"]
            if inner is None:
                return unjudged("process substitution does not parse")
            tokens.append(ShellToken("procsub", inner))
            position = substitution["end"]
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
            redirection = read_redirection(command, position)
            operator = redirection["text"]
            position = redirection["end"]
            tokens.append(ShellToken("op", fd + operator))
            if "<<" in operator and "<<<" not in operator:
                heredoc_expected = True
            continue
        if character in ";&|\n":
            flush()
            control = read_control(command, position)
            operator = control["text"]
            position = control["end"]
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


# lup: ignore[library-default] — POSIX shell grammar operators
SENTINEL_OPS = ("(", ")", ";;", ";&", ";;&")


def is_control_operator(text: str) -> bool:
    """Return whether an operator token separates command segments."""
    return text in (";", "&", "&&", "||", "|", "|&", "\n")


STREAM_WRITE_TARGETS = (
    "/dev/null",
    "/dev/zero",
    "/dev/full",
    "/dev/stdout",
    "/dev/stderr",
    "/dev/fd/1",
    "/dev/fd/2",
    "/dev/tty",
)
"""Write targets that reach a stream or a sink rather than the filesystem.

Named one by one rather than matched by their directory, because `/dev` is
not a safe prefix and never was: `> /dev/sda` overwrites a disk, `>
/dev/urandom` seeds the kernel's entropy pool, and `> /dev/mem` is worse than
either. Every entry here either discards what it is given or hands it to a
descriptor the process already holds.
"""


def writes_to_a_stream(
    word: str, streams: tuple[str, ...] = STREAM_WRITE_TARGETS
) -> bool:
    """Whether a redirection into this target can destroy nothing.

    Read before the rows that ask, because a stream has no prior contents to
    lose and so raises no question for anybody to answer -- and, before this,
    every one of these but `/dev/null` reached the fallback and was retired by
    the recovery row instead, which told the reader that "the affected paths
    are captured and restorable" about a terminal.

    Only descriptors 1 and 2 are named, and `/dev/fd/<n>` is deliberately not
    matched by shape. A higher descriptor is one the shell opened onto a file
    -- `exec 3>notes.txt` makes `> /dev/fd/3` a write to `notes.txt` -- and
    `/dev/stdin` is worse, since a command run with `< notes.txt` truncates it.
    Those reach the filesystem and belong to the rows that ask about it.
    """
    return posixpath.normpath(word) in streams


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


def python_script_targets(command: str, interpreters: tuple[str, ...]) -> list[str]:
    """Name every script an interpreter segment of this command would run.

    The ladder allows a script where it refuses inline code, on the grounds
    that a file can be read afterwards. That makes "which file" a fact worth
    having: a caller that can reach the filesystem counts how often each one
    is run, and a script being run over and over is one that stopped being
    the one-off the rung was for.

    Judged from the lexed segments rather than from the raw string, so a
    script named inside a pipeline or after a redirection is still found, and
    a command that does not lex yields nothing.
    """
    segments = parse_shell_words(command)
    if not isinstance(segments, list):
        return []
    named: list[str] = []
    for words in segments:
        run = uv_run_words(words) if words[:2] == ["uv", "run"] else words
        if not run or posixpath.basename(run[0]) not in interpreters:
            continue
        rest = run[1:]
        # `-c` and `-m` take their program as the next word, so a plain
        # "not a flag" filter reads that word as a filename and counts a
        # script that does not exist. Neither form names a file at all, and
        # both are refused anyway, so the segment contributes nothing.
        if any(word in ("-c", "-m") for word in rest):
            continue
        named.extend(word for word in rest if not word.startswith("-"))
    return named


def shell_write_targets(command: str, depth: int = 0) -> list[str]:
    """Name every path this command's redirections would open for writing.

    A caller that can reach the filesystem stats these and hands back the
    ones that already exist, so the kernel can tell creating a file from
    overwriting one without ever reading the filesystem itself. A command
    that does not lex yields nothing and keeps its unjudged verdict.

    A stream sink is not among them. :func:`writes_to_a_stream` already holds
    that a redirection into one destroys nothing, and every caller asks a
    filesystem question of what this hands back -- whether the target exists,
    whether a capture holds it, whether the lease covers it. ``/dev/null``
    answers all three the wrong way: it exists, no capture holds it, and no
    writable root contains it, so naming it here puts an approval question in
    front of every ``2>/dev/null``.
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
            targets.append(
                resolved_target(
                    tokens[following].text, assigned_literals(tokens, index)
                )
            )
            index = following + 1
            continue
        index += 1
    return [target for target in targets if not writes_to_a_stream(target)]


# lup: ignore[dict-str-payload] -- shell variable names, owned by the command
# being judged rather than by this repository, so no closed set enumerates
# them; the kernel is hermetic, which puts StringMap out of reach here
def assigned_literals(tokens: list[ShellToken], before: int) -> dict[str, str]:
    """Every name a standalone assignment gave a literal value, before an index.

    Only a *standalone* assignment is read, and the segment the index falls in
    is never read at all. `VAR=x cmd > $VAR` sets `VAR` for that one command's
    environment, and the shell expands the redirection from the value it
    already held -- so reading `x` as the target would judge a path the command
    never writes, and judge it in the permissive direction.

    Anything a segment holds that is not an assignment poisons that segment
    rather than being skipped: a command word means the assignments beside it
    were its environment, and a substitution means a value nothing here can
    read. Later assignments to one name win, because the shell's do.
    """
    # lup: ignore[dict-str-payload] -- as above, shell variable names
    literals: dict[str, str] = {}
    # lup: ignore[dict-str-payload] -- as above, shell variable names
    pending: dict[str, str] = {}
    poisoned = False
    for token in tokens[:before]:
        if token.kind == "op" and is_control_operator(token.text):
            if not poisoned:
                literals.update(pending)
            pending, poisoned = {}, False
            continue
        if poisoned:
            continue
        if token.kind != "word":
            poisoned = True
            continue
        # lup: ignore[string-split] -- the shell's own assignment grammar, on a
        # word the lexer has already separated; no parser here models it
        name, separator, value = token.text.partition("=")
        if not separator or not name.isidentifier() or not spells_its_path(value):
            poisoned = True
            continue
        pending[name] = value
    return literals


# lup: ignore[dict-str-payload] -- as above, shell variable names
def resolved_target(word: str, literals: dict[str, str]) -> str:
    """The path a target spells once a known literal stands in for it.

    Only a whole-word parameter is substituted -- `$NAME` or `${NAME}` and
    nothing else. A word mixing an expansion with other text names a path this
    cannot reconstruct, and half a substitution is worse than none: it would
    hand the rows below a path that reads as resolved and is not.

    Both readers of the redirection target need this and must not derive it
    apart. :func:`shell_write_targets` decides which paths the caller tests for
    existence and recoverability, and :func:`resolve_redirection` judges them;
    resolving in one alone would let a resolved path that already exists reach
    the create-versus-overwrite relaxation as though it were new.
    """
    name = word.removeprefix("$")
    if name == word:
        return word
    if name.startswith("{") and name.endswith("}"):
        name = name.removeprefix("{").removesuffix("}")
    return literals[name] if name.isidentifier() and name in literals else word


def resolve_redirection(
    tokens: list[ShellToken],
    index: int,
    existing_targets: list[str] | None = None,
    path_roles: list[PathRoleRow] | None = None,
    path_rules: list[PathRuleRow] | None = None,
    recoverable_targets: list[str] | None = None,
) -> Redirection:
    """Classify one redirection, consuming its target and stripping safe forms.

    What a write costs decides it, exactly as it decides for ``rm`` and
    ``cp``. Creating a file destroys nothing, so it passes once the caller
    has established the target is not there. Replacing one Git can restore
    byte for byte costs a checkout rather than any information, so it passes
    too. Anything else overwrites something no one can bring back, and asks.
    ``existing_targets`` of ``None`` means no caller established anything,
    and every target is treated as already there.

    The shape of the writing command is deliberately not consulted. A heredoc
    body and an ``echo`` argument author identical content, and the create
    case already admits both — so gating one of them on an existing path drew
    the line where the cost was lowest rather than where the risk was. What
    the edit gate reads is content, and that gate is reached through Edit and
    Write, not by re-deriving a weaker copy of it here.

    A generated plugin tree is refused ahead of every relaxation, including
    the create case: authoring a file there by hand is editing a build
    product, whether or not one is already sitting at that path.
    """
    operator = tokens[index].text
    if "<<" in operator and "<<<" not in operator:
        target = index + 1
        if target >= len(tokens) or tokens[target].kind != "word":
            return Redirection(
                decision=unjudged("heredoc has no delimiter"), resume=index + 1
            )
        return Redirection(decision=None, resume=target + 1)
    if "&" in operator and (operator[-1].isdigit() or operator[-1] == "-"):
        return Redirection(decision=None, resume=index + 1)
    target = index + 1
    if target >= len(tokens) or tokens[target].kind != "word":
        return Redirection(
            decision=KernelDecision("ask", "file redirection is never auto-allowed"),
            resume=index + 1,
        )
    if "<" in operator:
        return Redirection(decision=None, resume=target + 1)
    spelled = resolved_target(tokens[target].text, assigned_literals(tokens, index))
    if writes_to_a_stream(spelled):
        return Redirection(decision=None, resume=target + 1)
    refused = refuses_generated_plugin_target(spelled)
    if refused is not None:
        return Redirection(decision=refused, resume=target + 1)
    protected = protected_write_target(
        [spelled],
        path_rules or [],
        existing_targets is None or spelled in existing_targets,
    )
    if protected is not None:
        return Redirection(decision=protected, resume=target + 1)
    if path_role(spelled, path_roles or []) == "scratch":
        return Redirection(decision=None, resume=target + 1)
    if (
        existing_targets is not None
        and spells_its_path(spelled)
        and spelled not in existing_targets
    ):
        return Redirection(decision=None, resume=target + 1)
    if spelled in (recoverable_targets or []):
        return Redirection(decision=None, resume=target + 1)
    return Redirection(
        decision=KernelDecision(
            "ask",
            "file redirection is never auto-allowed",
            checkpoint="targeted",
            purpose="unrecovered_local_mutation",
        ),
        resume=target + 1,
    )


def parse_shell_words(
    command: str,
    depth: int = 0,
    existing_targets: list[str] | None = None,
    path_roles: list[PathRoleRow] | None = None,
    path_rules: list[PathRuleRow] | None = None,
    recoverable_targets: list[str] | None = None,
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

    recoverable = recoverable_targets or []

    def substituted_segments(text: str) -> list[list[str]] | KernelDecision:
        if depth >= 2:
            return unjudged("command substitution nests too deeply")
        return parse_shell_words(
            text, depth + 1, existing_targets, path_roles, path_rules, recoverable
        )

    segments: list[list[str]] = []
    current: list[str] = []
    # A substitution's own command, held until the segment being built closes.
    # Spliced the moment it is read, it lands ahead of the words around it —
    # between a `for` header and its `do`, where the loop reader takes it for
    # a condition and refuses a construct that parsed fine. It cannot simply
    # flush the partial segment either: the tokenizer leaves a sentinel in the
    # word where the substitution stood, and cutting the segment there strands
    # that sentinel as a command of its own.
    pending: list[list[str]] = []

    def close_segment() -> None:
        """End the segment being built, then place what it substituted."""
        nonlocal current
        if current:
            segments.append(current)
            current = []
        segments.extend(pending)
        pending.clear()

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
            close_segment()
            segments.append([token.text])
            index += 1
            continue
        if token.kind == "procsub":
            if depth >= 2:
                return unjudged("process substitution nests too deeply")
            inner = parse_shell_words(
                token.text,
                depth + 1,
                existing_targets,
                path_roles,
                path_rules,
                recoverable,
            )
            if isinstance(inner, KernelDecision):
                return inner
            pending.extend(inner)
            current.append("/dev/fd/63")
            index += 1
            continue
        if token.kind == "cmdsub":
            spliced = substituted_segments(token.text)
            if isinstance(spliced, KernelDecision):
                return spliced
            pending.extend(spliced)
            index += 1
            continue
        if is_control_operator(token.text):
            close_segment()
            index += 1
            continue
        redirection = resolve_redirection(
            tokens, index, existing_targets, path_roles, path_rules, recoverable
        )
        index = redirection["resume"]
        verdict = redirection["decision"]
        if verdict is not None:
            return verdict
    close_segment()
    if not segments:
        return unjudged("shell command has no executable segment")
    return segments


def shell_path_verb_targets(command: str) -> list[str]:
    """Name every operand a path-writing verb in this command acts on.

    ``git restore`` is one of them: it rewrites the paths it names from the
    index, so whether that costs anything is the same filesystem question the
    delete verbs ask.

    A caller that can reach the filesystem resolves facts about these — which
    are directories, which Git could restore — and hands them back, so the
    kernel decides from primitive data without ever reading a disk. Naming
    only these operands keeps that resolution proportional to the command: a
    session running ``ls`` pays for none of it.

    Over-naming is safe and under-naming is merely conservative, because the
    answers are consulted as a table of facts rather than trusted as a target
    list — the kernel decides for itself which words a verb writes. A command
    that does not lex yields nothing and keeps its unjudged verdict.
    """
    segments = parse_shell_words(command, 0)
    if isinstance(segments, KernelDecision):
        return []
    targets: list[str] = []
    for segment in segments:
        words = effective_command(segment)["words"]
        if not words:
            continue
        restore = git_restore_operands(words)
        if restore is not None:
            targets.extend(restore["paths"])
            continue
        archived = archive_write(words)
        if archived is not None:
            targets.extend([*archived["authored"], *archived["consumed"]])
            if archived["directory"] is not None:
                targets.append(archived["directory"])
            continue
        if posixpath.basename(words[0]) == "sed":
            # Every literal word, the script included. Over-naming is exactly
            # what this docstring says is safe: a script is not a file, so
            # nothing will be reported about it, and which words a rewrite
            # actually writes stays the kernel's own reading.
            targets.extend(word for word in words[1:] if not word.startswith("-"))
            continue
        if posixpath.basename(words[0]) not in SCRATCH_VERB_FLAGS:
            continue
        operands = path_verb_operands(words)["operands"]
        targets.extend(operands)
    return targets
