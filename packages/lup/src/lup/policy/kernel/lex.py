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
from .effects import EffectEvidence, declare, verdict_for
from .roles import spells_its_path
from .rows import PathRoleRow, PathRuleRow, ShellRuleRow
from .words import (
    PROGRAM_CARRYING_COMMANDS,
    SCRATCH_VERB_FLAGS,
    effective_command,
    flag_write_targets,
    git_apply_patches,
    git_restore_operands,
    opaque_argument,
    path_verb_operands,
    program_carrying_operands,
    protected_write_target,
    refuses_generated_plugin_target,
    uv_run_words,
    write_checkpoint,
    write_scope,
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
    """A delimiter awaiting its body, and whether quoting made the body literal.

    ``token`` is where the delimiter word landed, because the body arrives a
    line later and has to be put back somewhere a reader of the segment can
    find it. An index rather than the delimiter text, since one line may open
    two heredocs under the same word.
    """

    delimiter: str
    quoted: bool
    token: int


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
    body: str
    """The literal text a heredoc delimiter introduced, on that token alone.

    Empty everywhere else, and empty for an unquoted delimiter: the shell
    substitutes inside that body, so what is written here is not what lands.
    Kept because a heredoc is one of the two ways a command carries the
    content it is about to write, and content the command carries is content
    the edit gates can read before it lands rather than after.
    """

    def __init__(
        self,
        kind: Literal["word", "op", "procsub", "cmdsub"],
        text: str,
        quoted: bool = False,
        body: str = "",
    ) -> None:
        self.kind = kind
        self.quoted = quoted
        self.text = text
        self.body = body


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
    command: str,
    position: int,
    pending: list[Heredoc],
    tokens: list[ShellToken] | None = None,
) -> int | KernelDecision:
    """Consume heredoc bodies after a newline, gating unquoted expansion.

    A quoted delimiter makes the body literal data. An unquoted one lets the
    shell substitute inside the body, so any substitution syntax there is
    refused with the quoting recipe.

    A literal body is put back on its delimiter token rather than discarded.
    It was discarded here for as long as the only question asked of it was
    whether it substitutes; the other question — what this command is about
    to write — is answerable from the same lines, and only from them, since
    the redirection that names the target is resolved a pass later.
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
        body = "".join(f"{line}\n" for line in lines)
        if not is_quoted:
            if "`" in body or "$(" in body:
                return KernelDecision(
                    "deny",
                    "an unquoted heredoc substitutes commands — quote the"
                    " delimiter (<<'EOF') to make the body literal",
                )
            continue
        # A trailing newline per line, because that is what the shell feeds:
        # the delimiter line ends the body and is not part of it, and a body
        # compared against a file has to agree with the file about its last
        # byte or every such write reads as having changed the final line.
        if tokens is not None and 0 <= heredoc["token"] < len(tokens):
            tokens[heredoc["token"]].body = body
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
                pending_heredocs.append(
                    Heredoc(
                        delimiter="".join(word),
                        quoted=quoted,
                        token=len(tokens) - 1,
                    )
                )
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
                consumed = read_heredoc_bodies(
                    command, position, pending_heredocs, tokens
                )
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


class AuthoredWrite(TypedDict):
    """One file a command writes, and the bytes the command itself carries.

    The pair an edit is judged on. A shell write is answered by its path
    alone, on the argument that a redirection produces its content by running
    and there is nothing to read in advance — which is true of `dev render >
    docs/api.md` and false of `cat > f <<'EOF'`, where the bytes are sitting
    in the command. What separates them is exactly this: whether the content
    is here.
    """

    path: str
    content: str
    append: bool


class TeeWrite(TypedDict):
    """The files a `tee` writes through its operands, and how it opens them.

    `tee` is the everyday write that names its files as operands instead of
    through a redirection, so the walk that finds every other authored write
    cannot see it at all. Append is a flag rather than the `>>` that walk
    reads, which is the same fact spelled the utility's own way.
    """

    paths: list[str]
    append: bool


def tee_operands(words: list[str]) -> TeeWrite | None:
    """Where a `tee` puts what it is handed, or ``None`` where it is unmodelled.

    Only the flags that leave the operands meaning what they say are read.
    Anything else returns ``None`` -- `--output-error` and every spelling this
    does not name, and a bare `-`, which is a file called `-` to `tee` and a
    stream to whoever wrote it.
    """
    if not words or posixpath.basename(words[0]) != "tee":
        return None
    paths: list[str] = []
    append = False
    for word in words[1:]:
        if word in ("--", "--ignore-interrupts"):
            continue
        if word == "--append":
            append = True
            continue
        if word.startswith("--") or word == "-":
            return None
        if word.startswith("-") and len(word) > 1:
            if any(letter not in "aip" for letter in word[1:]):
                return None
            append = append or "a" in word
            continue
        paths.append(word)
    return TeeWrite(
        paths=[path for path in paths if not writes_to_a_stream(path)], append=append
    )


# lup: ignore[library-default] — printf's own escape table, spelled the way
# printf spells it; no adopter has a different `\n` to declare here
PRINTF_ESCAPES = {
    "\\": "\\",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
"""The escapes a format may carry and this reader can state exactly.

An octal `\\ddd` and the output-stopping `\\c` are absent rather than
approximated. Both change what lands, and a document the command never wrote
is worse to hand a gate than no document at all.
"""


def printf_template(text: str) -> list[str] | None:
    """A printf format's literal pieces, split where each `%s` stands.

    The format is printf's whole difficulty, and the reason it was left
    unread: it carries escapes, conversions and an argument cycle, so a
    reading of it that was wrong would hand the gates a document the command
    never writes. What that argues for is a stated grammar rather than an
    absence -- `%s`, `%%`, the escapes :data:`PRINTF_ESCAPES` names, and
    literal text -- and a refusal of everything outside it.

    ``None`` for every other conversion, every escape not named there, and a
    trailing backslash or `%`. Each leaves the write judged by its path, which
    is the answer it had before this read anything.
    """
    pieces = [""]
    index = 0
    while index < len(text):
        character = text[index]
        if character not in ("\\", "%"):
            pieces[-1] += character
            index += 1
            continue
        if index + 1 == len(text):
            return None
        following = text[index + 1]
        match (character, following):
            case ("\\", _) if following in PRINTF_ESCAPES:
                pieces[-1] += PRINTF_ESCAPES[following]
            case ("%", "%"):
                pieces[-1] += "%"
            case ("%", "s"):
                pieces.append("")
            case _:
                return None
        index += 2
    return pieces


def printf_text(arguments: list[str]) -> str | None:
    """The bytes a `printf` writes, where its format states them exactly.

    printf reuses its format until the operands run out, filling a conversion
    with nothing where nothing is left, so what lands is the whole cycle
    rather than one pass. A format carrying no conversion is written once, and
    an operand beside it is simply unread -- which printf's own specification
    leaves unstated, so an operand there is ``None`` rather than a guess.

    A leading `-` is ``None`` for the same reason: `-v` assigns to a variable
    and writes nothing at all, and `--` ends the options without saying which
    word became the format.
    """
    if not arguments or arguments[0].startswith("-"):
        return None
    pieces = printf_template(arguments[0])
    if pieces is None:
        return None
    slots = len(pieces) - 1
    operands = arguments[1:]
    if not slots:
        return pieces[0] if not operands else None
    cycles = max(1, (len(operands) + slots - 1) // slots)
    filled = [*operands, *[""] * (cycles * slots - len(operands))]
    return "".join(
        "".join(
            piece + filled[cycle * slots + position]
            for position, piece in enumerate(pieces[:-1])
        )
        + pieces[-1]
        for cycle in range(cycles)
    )


def carried_text(
    words: list[str], bodies: list[str], incoming: str | None = None
) -> str | None:
    """The bytes a segment's own words carry, or ``None`` where it makes them.

    Four shapes. `cat` handed nothing but a quoted heredoc emits that body;
    `echo` handed literal words emits them; `printf` emits whatever
    :func:`printf_text` can render of its format; and `tee` emits what it was
    handed, since a `tee` copies its input to every file it names.

    ``incoming`` is what the segment before this one piped in -- its standard
    output, where it carried its own bytes and redirected none of them
    elsewhere. `echo 'x = 1' | tee f` is the everyday spelling of the shape
    `tee` is read for, and a segment read on its own is handed nothing.

    ``None`` everywhere the reading is not certain: an unquoted heredoc the
    shell substitutes into, a word carrying an expansion, an `echo` flag that
    changes what the words mean, a printf conversion this cannot render. Each
    of those leaves the write answered by its path, which is the answer it had
    before this existed.
    """
    if not words:
        return None
    if any(opaque_argument(word) or "$" in word or "`" in word for word in words):
        return None

    def stdin_text() -> str | None:
        """What this segment reads, taking a heredoc over a pipe as the shell does."""
        if not bodies:
            return incoming
        return bodies[0] if len(bodies) == 1 and bodies[0] else None

    match posixpath.basename(words[0]):
        case "cat":
            return stdin_text() if len(words) == 1 else None
        case "printf":
            return None if bodies else printf_text(words[1:])
        case "tee":
            return None if tee_operands(words) is None else stdin_text()
        case "echo":
            if bodies:
                return None
            arguments = words[1:]
            trailing = "\n"
            if arguments and arguments[0] == "-n":
                arguments = arguments[1:]
                trailing = ""
            # Every remaining flag changes what the words mean -- `-e` reads
            # escapes, `-E` stops reading them, and a cluster does both -- so
            # a word still shaped like one is a reading this cannot make.
            if any(word.startswith("-") for word in arguments):
                return None
            return " ".join(arguments) + trailing
        case _:
            return None


def authored_writes(command: str) -> list[AuthoredWrite]:
    """Every write this command carries the content of, path and bytes together.

    What it is for: a redirection is judged by its path, because a command
    produces its output by running and nothing could read it first. Where the
    command carries the bytes, that premise is simply untrue, and the gates an
    edit is judged by -- the anti-pattern audit, the review-note gate, the size
    budget -- can read exactly what an `Edit` would have shown them. Measured
    before this: `cat > packages/lup/src/lup/seams.py <<'EOF'` replaced a
    tracked library module with one line, allowed and unprompted, because the
    write row was told the route is reviewed.

    Read per segment, and a segment yields nothing unless the whole of it is
    legible: no substitution, at most one redirection target, and a content
    shape :func:`carried_text` can state. Everything else keeps the answer it
    had.

    Two routes reach a file rather than one. A redirection names its target in
    the operator that follows the command, and `tee` names its targets as
    operands -- one utility, but the everyday one, and what it is handed comes
    down a pipe as often as from a heredoc. So the walk carries the segment's
    standard output forward across a `|`, which is what lets `echo 'x = 1' |
    tee packages/lup/src/lup/seams.py` be read as the module replacement it is.
    """
    tokens = tokenize_shell(command)
    if isinstance(tokens, KernelDecision):
        return []
    authored: list[AuthoredWrite] = []
    words: list[str] = []
    bodies: list[str] = []
    targets: list[str] = []
    appends: list[bool] = []
    legible = True
    incoming: str | None = None

    def close(piping: bool = False) -> None:
        """End the segment being read, emitting what it authors.

        ``piping`` says a `|` ended it, which makes what this segment wrote to
        standard output the next segment's input -- unless a redirection took
        that output somewhere else, where what reaches the pipe is no longer
        what this read.
        """
        nonlocal legible, incoming
        content = carried_text(words, bodies, incoming) if legible else None
        piped = tee_operands(words)
        landings = [
            *(
                []
                if piped is None
                else [(path, piped["append"]) for path in piped["paths"]]
            ),
            *([(targets[0], appends[0])] if len(targets) == 1 else []),
        ]
        if content is not None:
            authored.extend(
                AuthoredWrite(path=path, content=content, append=append)
                for path, append in landings
            )
        incoming = content if piping and not targets else None
        words.clear()
        bodies.clear()
        targets.clear()
        appends.clear()
        legible = True

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind in ("cmdsub", "procsub"):
            legible = False
            index += 1
            continue
        if token.kind != "op":
            words.append(token.text)
            index += 1
            continue
        operator = token.text
        if is_control_operator(operator) or operator in SENTINEL_OPS:
            close(operator == "|")
            index += 1
            continue
        following = index + 1
        carries = following < len(tokens) and tokens[following].kind == "word"
        if "<<" in operator and "<<<" not in operator:
            if not carries:
                legible = False
                index += 1
                continue
            bodies.append(tokens[following].body)
            index = following + 1
            continue
        if "&" in operator and (operator[-1].isdigit() or operator[-1] == "-"):
            index += 1
            continue
        if not carries:
            legible = False
            index += 1
            continue
        spelled = resolved_target(
            tokens[following].text, assigned_literals(tokens, index)
        )
        # A stream sink is not a target here for the reason it is not one in
        # `shell_write_targets`: nothing is destroyed and no gate has anything
        # to read. Dropped as it is met rather than at the end, or a
        # `2>/dev/null` beside the write would count as a second target and
        # take the whole segment out of reach.
        if redirection_writes(operator) and not writes_to_a_stream(spelled):
            targets.append(spelled)
            appends.append(">>" in operator)
        index = following + 1
    close()
    return authored


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
    contained: bool = False,
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
    scope = write_scope(spelled, path_roles or [])
    # A target still carrying an expansion names no path to scope, so what a
    # reviewer would be shown is `$B` and where that lands is the question.
    # Asked after the scope is read rather than before it, because a declared
    # root is one of the things a role recognizes *through* the variable that
    # names it: `$TMPDIR/out.txt` spells no path and is still scratch.
    if scope != "scratch" and not spells_its_path(spelled):
        return Redirection(
            decision=KernelDecision(
                "ask",
                "file redirection is never auto-allowed",
                checkpoint="targeted",
                purpose="unrecovered_local_mutation",
            ),
            resume=target + 1,
        )
    existing = existing_targets is None or spelled in existing_targets
    decided = verdict_for(
        [
            declare(
                "writes_path",
                scope=scope,
                write="overwrite" if existing else "create",
                # Reviewed, because the gates do read what this wrote --
                # afterwards, against the file itself. That is the whole of
                # what stops the row refusing here: a redirection produces its
                # content by running, so nothing could read it in advance, and
                # a refusal on the strength of "nobody read this" would be
                # refusing the only writes for which that is unavoidable.
                reviewed=True,
            )
        ],
        EffectEvidence(existing=existing),
        "inside" if contained else "ambient",
    )
    if decided == "allow":
        return Redirection(decision=None, resume=target + 1)
    return Redirection(
        decision=KernelDecision(
            decided,
            "file redirection is never auto-allowed",
            checkpoint=write_checkpoint(scope),
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
    contained: bool = False,
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
            text,
            depth + 1,
            existing_targets,
            path_roles,
            path_rules,
            recoverable,
            contained,
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
                contained,
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
            tokens,
            index,
            existing_targets,
            path_roles,
            path_rules,
            recoverable,
            contained,
        )
        index = redirection["resume"]
        verdict = redirection["decision"]
        if verdict is not None:
            return verdict
    close_segment()
    if not segments:
        return unjudged("shell command has no executable segment")
    return segments


def shell_flag_write_targets(command: str, rows: list[ShellRuleRow]) -> list[str]:
    """Name every path a declared write flag in this command lands a file at.

    The third way a command names something it writes, beside a redirection
    and a path verb's operand, and the one that needs the table: `-o` is a
    path for `sort` and nothing at all for `rg`, so which words are files is
    a fact about the rule rather than about the shell.

    Every row that could match the executable contributes its flags, rather
    than the one row that will: which subcommand and operation a command
    resolves to is the matcher's own walk, and repeating it here would be a
    second copy of it to keep in step. Gathering wide costs nothing *provided
    what reads this only relaxes* -- a path named for a flag the matched row
    does not guard is a fact nobody consults.

    That proviso is the whole of why these stay out of the lease's target
    list. Naming a word the command does not write is how `sed`'s script came
    to be reported as a write outside the lease, and the lease is the one
    reader that escalates on what it is handed.
    """
    segments = parse_shell_words(command, 0)
    if isinstance(segments, KernelDecision):
        return []
    targets: list[str] = []
    for segment in segments:
        words = effective_command(segment)["words"]
        if not words:
            continue
        executable = posixpath.basename(words[0])
        declared = [
            flag
            for row in rows
            if row["command"] == executable
            for flag in row["write_flags"]
        ]
        targets.extend(flag_write_targets(words, declared))
    return targets


def shell_patch_operands(command: str) -> list[str]:
    """Name every patch file this command hands to something that applies one.

    The fourth way a command names what it writes, and the only one that names
    it indirectly: the operand is a description of the write rather than its
    target. What reads this turns each into the paths the patch touches by
    asking Git, so the two steps stay on the side of the boundary that can do
    them -- the words here, the file's contents there.

    A command that does not lex yields nothing, on the same terms as every
    reader beside it: an unparseable line keeps whatever verdict it already
    earned rather than gaining a relaxation from a reading that failed.
    """
    segments = parse_shell_words(command, 0)
    if isinstance(segments, KernelDecision):
        return []
    return [
        patch
        for segment in segments
        for words in [effective_command(segment)["words"]]
        if words
        for patch in git_apply_patches(words)
    ]


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

    Under-naming is conservative, because the answers are consulted as a table
    of facts rather than trusted as a target list — the kernel decides for
    itself which words a verb writes. Over-naming is *not* the same kind of
    safe, though it reads that way: two of the three questions asked of these
    stat the path and drop whatever is not on disk, and the third resolves the
    string and asks whether it sits under a writable root. A word that is not
    a path at all still answers that one, and answers it wrongly.

    So a command carrying a program names its paths by
    :data:`~lup.policy.kernel.words.PROGRAM_CARRYING_COMMANDS` rather than by
    taking every non-flag word. A command that does not lex yields nothing and
    keeps its unjudged verdict.
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
        grammar = PROGRAM_CARRYING_COMMANDS.get(posixpath.basename(words[0]))
        if grammar is not None:
            targets.extend(program_carrying_operands(words, grammar))
            continue
        if posixpath.basename(words[0]) not in SCRATCH_VERB_FLAGS:
            continue
        operands = path_verb_operands(words)["operands"]
        targets.extend(operands)
    return targets
