# lup: ignore[string-split]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""What an interpreter invocation hands the interpreter to run.

One criterion decides every interpreter form: an invocation is refused when
it leaves no reviewable artifact behind. Inline code leaves nothing to read,
an interpreter handed nothing runs whatever arrives on its input, and a
program fetched from elsewhere is read by nobody here. A script file is
openable, diffable and runnable again, so it is none of those.

Applying that needs the interpreter's own grammar, because the program sits
where the options stop: `bash -o pipefail x.sh` runs `x.sh`, and reading
`pipefail` as the script would judge a word that is only an option's value.
So each interpreter's options are listed as what they are -- carrying the
program, consuming the next word, or consuming nothing -- and an option no
list names is unread rather than guessed at, because a guess is exactly how
a value would come to be read as the script.
"""

import posixpath
from typing import Literal, TypedDict

from .decision import SUBSTITUTION_SENTINEL, KernelDecision

type ProgramKind = Literal[
    "script", "inline", "bare", "unread", "remote", "module", "subcommand"
]
"""What an invocation turned out to hand its interpreter.

``module`` and ``subcommand`` are not answers but hand-offs: a module is
judged by whether this project declares its root, and a subcommand by the
vocabulary row of the tool that owns it."""


class InterpreterGrammar(TypedDict):
    """How one interpreter's command line names the program it runs.

    Every list is the interpreter's own spelling, a fact about the tool
    rather than a preference about it: a spelling missing from ``inline`` is
    a hole, and one missing from the others only makes a real invocation
    unread.
    """

    inline: list[str]
    """Options that carry the program itself, or have it read from stdin."""

    valued: list[str]
    """Options consuming the following word, or a value attached with ``=``."""

    flags: list[str]
    """Options consuming nothing."""

    families: list[str]
    """Prefixes of long options that consume nothing, such as ``--no-``."""

    module: str
    """The option naming a module to run in place of a file, or empty."""

    runner: str
    """The subcommand that runs a file, or empty where the first operand is it."""

    evaluator: str
    """The subcommand that runs its operand as code, or empty."""

    suffixes: list[str]
    """What an operand ends in to be read as a script rather than a subcommand.

    Empty where every operand is a script. Set for a tool whose first operand
    may equally be one of its own subcommands, and whose subcommands never
    carry a path separator or a suffix."""


class ProgramReading(TypedDict):
    """What one invocation hands its interpreter, and the word that says so."""

    kind: ProgramKind
    subject: str


def grammar(
    inline: tuple[str, ...] = (),
    valued: tuple[str, ...] = (),
    flags: tuple[str, ...] = (),
    families: tuple[str, ...] = (),
    module: str = "",
    runner: str = "",
    evaluator: str = "",
    suffixes: tuple[str, ...] = (),
) -> InterpreterGrammar:
    """One grammar row, with every list it does not name empty."""
    return InterpreterGrammar(
        inline=list(inline),
        valued=list(valued),
        flags=list(flags),
        families=list(families),
        module=module,
        runner=runner,
        evaluator=evaluator,
        suffixes=list(suffixes),
    )


SHELL_GRAMMAR = grammar(
    inline=("-c", "-s"),
    valued=("-o", "+o", "-O", "+O", "--rcfile", "--init-file", "--emulate"),
    flags=(
        *(f"{sign}{letter}" for sign in "-+" for letter in "abefhkmnptuvxBCEHPT"),
        *(f"-{letter}" for letter in "ilrD"),
        "--debug",
        "--debugger",
        "--dump-po-strings",
        "--dump-strings",
        "--help",
        "--login",
        "--noediting",
        "--noprofile",
        "--norc",
        "--posix",
        "--pretty-print",
        "--restricted",
        "--verbose",
        "--version",
    ),
)
"""The POSIX shells' shared invocation grammar, as bash spells its superset.

`-c` hands over a command string and `-s` reads commands from stdin, so both
carry the program. `-o` and `-O` name a setting, which is the value a script
position would otherwise be mistaken for."""

PYTHON_GRAMMAR = grammar(
    inline=("-c",),
    valued=("-W", "-X", "--check-hash-based-pycs"),
    flags=(
        *(f"-{letter}" for letter in "bBdEhiIOPqsSuvVx"),
        "--help",
        "--help-env",
        "--help-xoptions",
        "--help-all",
        "--version",
    ),
    module="-m",
)
"""Python's invocation grammar, read where `uv run` hands it a program."""

INTERPRETER_GRAMMARS: dict[str, InterpreterGrammar] = {
    **{shell: SHELL_GRAMMAR for shell in ("sh", "bash", "zsh", "dash", "ksh")},
    "fish": grammar(
        inline=("-c", "--command", "-C", "--init-command"),
        flags=("-i", "--interactive", "-l", "--login", "-n", "--no-execute", "-N"),
    ),
    "python": PYTHON_GRAMMAR,
    "python3": PYTHON_GRAMMAR,
    "node": grammar(
        inline=("-e", "--eval", "-p", "--print", "-i", "--interactive"),
        valued=(
            "-r",
            "--require",
            "--import",
            "--loader",
            "--experimental-loader",
            "-C",
            "--conditions",
            "--input-type",
            "--env-file",
            "--env-file-if-exists",
            "--run",
            "--title",
            "--inspect-port",
            "--redirect-warnings",
            "--report-dir",
            "--report-directory",
            "--report-filename",
            "--diagnostic-dir",
            "--cpu-prof-dir",
            "--cpu-prof-name",
            "--heap-prof-dir",
            "--heap-prof-name",
            "--watch-path",
            "--test-reporter",
            "--test-reporter-destination",
            "--test-name-pattern",
            "--test-skip-pattern",
            "--unhandled-rejections",
            "--disable-warning",
            "--dns-result-order",
            "--icu-data-dir",
            "--openssl-config",
        ),
        flags=(
            "-c",
            "--check",
            "-v",
            "--version",
            "-h",
            "--help",
            "--inspect",
            "--inspect-brk",
            "--inspect-wait",
            "--watch",
            "--watch-preserve-output",
            "--test",
            "--enable-source-maps",
            "--preserve-symlinks",
            "--preserve-symlinks-main",
            "--abort-on-uncaught-exception",
            "--expose-gc",
            "--frozen-intrinsics",
            "--pending-deprecation",
            "--throw-deprecation",
            "--zero-fill-buffers",
            "--cpu-prof",
            "--heap-prof",
            "--prof",
            "--permission",
            "--jitless",
        ),
        families=("--no-", "--experimental-", "--trace-", "--allow-", "--test-"),
    ),
    "bun": grammar(
        inline=("-e", "--eval", "-p", "--print"),
        valued=(
            "-r",
            "--preload",
            "--require",
            "--import",
            "-d",
            "--define",
            "-l",
            "--loader",
            "-c",
            "--config",
            "--cwd",
            "--env-file",
            "--tsconfig-override",
            "--main-fields",
            "--extension-order",
            "--jsx-factory",
            "--jsx-fragment",
            "--jsx-import-source",
            "--jsx-runtime",
            "--conditions",
            "--port",
            "-F",
            "--filter",
            "--console-depth",
            "--title",
        ),
        flags=(
            "--watch",
            "--hot",
            "--smol",
            "-b",
            "--bun",
            "--silent",
            "-i",
            "--prefer-offline",
            "--prefer-latest",
            "--inspect",
            "--inspect-wait",
            "--inspect-brk",
            "--if-present",
            "--expose-gc",
            "--zero-fill-buffers",
            "--throw-deprecation",
            "-v",
            "--version",
            "--revision",
            "-h",
            "--help",
        ),
        families=("--no-",),
        suffixes=(".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"),
    ),
    "deno": grammar(
        valued=(
            "-c",
            "--config",
            "--import-map",
            "--cert",
            "--location",
            "--seed",
            "--ext",
            "--preload",
            "--conditions",
            "-L",
            "--log-level",
        ),
        flags=(
            "-A",
            "--allow-all",
            "-P",
            "--permission-set",
            "-q",
            "--quiet",
            "-r",
            "--reload",
            "--check",
            "--cached-only",
            "--lock",
            "--frozen",
            "--env-file",
            "--node-modules-dir",
            "--vendor",
            "--inspect",
            "--inspect-brk",
            "--inspect-wait",
            "--v8-flags",
            "--watch",
            "--watch-hmr",
            "--watch-exclude",
            "--coverage",
            "--unstable",
            "--unsafely-ignore-certificate-errors",
        ),
        families=("--allow-", "--deny-", "--no-", "--unstable-"),
        runner="run",
        evaluator="eval",
    ),
    "perl": grammar(inline=("-e", "-E")),
    "ruby": grammar(inline=("-e",)),
    "php": grammar(inline=("-r", "-a")),
}
"""Every interpreter's invocation grammar, keyed by executable name.

Each interpreter the kernel refuses bare has a row, so a form handed to one
through `uv run` is read by the same grammar; a row naming only ``inline``
reads every other option as unread, which refuses rather than guesses."""

SCRIPT_INTERPRETERS = ("bash", "sh", "zsh", "node", "bun", "deno")
"""The interpreters this policy lets run a named script file directly.

Python is absent on purpose: it runs through `uv run python <script>`, in
this project's environment, and the bare spelling keeps pointing there."""


def option_width(
    word: str, following: list[str], rules: InterpreterGrammar
) -> int | ProgramReading:
    """How many words one option consumes, or what it hands the interpreter.

    A single-dash word is read letter by letter, the way these interpreters
    read a cluster: `-ec` sets `-e` and then carries `-c`, and `-Wignore`
    attaches its value. A value that is itself a `data:` URL is a program
    spelled inline wherever it appears.
    """

    def valued(value: str | None, width: int) -> int | ProgramReading:
        if value is None:
            return ProgramReading(kind="unread", subject=word)
        if value.startswith("data:"):
            return ProgramReading(kind="inline", subject=word)
        return width

    name, equals, attached = word.partition("=")
    if name in rules["inline"]:
        return ProgramReading(kind="inline", subject=word)
    if name in rules["valued"]:
        return valued(
            attached if equals else following[0] if following else None,
            1 if equals else 2,
        )
    if name in rules["flags"] or (
        word.startswith("--")
        and any(name.startswith(family) for family in rules["families"])
    ):
        return 1
    if word.startswith("--"):
        # An attached value cannot move the script, and no name here carries
        # code; one with nothing attached may consume the next word.
        return 1 if equals else ProgramReading(kind="unread", subject=word)
    sign = word[0]
    for index, letter in enumerate(word[1:], start=1):
        option = sign + letter
        if option in rules["inline"]:
            return ProgramReading(kind="inline", subject=word)
        if option in rules["valued"]:
            rest = word[index + 1 :]
            return valued(
                rest if rest else following[0] if following else None,
                1 if rest else 2,
            )
        if option not in rules["flags"]:
            return ProgramReading(kind="unread", subject=word)
    return 1


def operand_reading(word: str, rules: InterpreterGrammar) -> ProgramReading:
    """What the first operand hands the interpreter.

    A stream alias reads the program from a descriptor, not a file anybody
    can open afterwards, so it is inline. A URL or package specifier is
    fetched from elsewhere. A word this reading cannot see into is unread.
    """
    if "$" in word or "`" in word or SUBSTITUTION_SENTINEL in word:
        return ProgramReading(kind="unread", subject=word)
    if "://" in word or word.startswith(("data:", "npm:", "jsr:", "node:")):
        return ProgramReading(kind="remote", subject=word)
    if word == "-" or word.startswith(("/dev/", "/proc/")):
        return ProgramReading(kind="inline", subject=word)
    if (
        rules["suffixes"]
        and "/" not in word
        and not word.endswith(tuple(rules["suffixes"]))
    ):
        return ProgramReading(kind="subcommand", subject=word)
    return ProgramReading(kind="script", subject=word)


def read_program(
    words: list[str],
    grammars: dict[str, InterpreterGrammar] = INTERPRETER_GRAMMARS,
) -> ProgramReading:
    """Read what one interpreter invocation hands the interpreter to run.

    Options are consumed until the first operand, which is the program; the
    words after it are the program's own arguments and are never read as the
    interpreter's. A tool with a runner subcommand has it first, and its
    evaluating subcommand carries code the way `-c` does.
    """
    executable = posixpath.basename(words[0])
    rules = grammars[executable] if executable in grammars else grammar()
    signed = any(
        option.startswith("+") for option in [*rules["valued"], *rules["flags"]]
    )
    awaiting_runner = bool(rules["runner"])

    def found(reading: ProgramReading) -> ProgramReading:
        """The reading, spelled from the runner on where one was consumed."""
        if awaiting_runner or not rules["runner"]:
            return reading
        spelled = f"{rules['runner']} {reading['subject']}".rstrip()
        return ProgramReading(kind=reading["kind"], subject=spelled)

    position = 1
    while position < len(words):
        word = words[position]
        following = words[position + 1 :]
        if word == "--":
            return found(
                operand_reading(following[0], rules)
                if following and not awaiting_runner
                else ProgramReading(kind="bare", subject=word)
            )
        if rules["module"] and word == rules["module"]:
            return ProgramReading(
                kind="module" if following else "bare",
                subject=following[0] if following else word,
            )
        if len(word) > 1 and (word.startswith("-") or (signed and word[0] == "+")):
            width = option_width(word, following, rules)
            if not isinstance(width, int):
                return found(width)
            position += width
            continue
        if awaiting_runner:
            if word == rules["runner"]:
                awaiting_runner = False
                position += 1
                continue
            kind: ProgramKind = "inline" if word == rules["evaluator"] else "subcommand"
            return ProgramReading(kind=kind, subject=word)
        return found(operand_reading(word, rules))
    return found(ProgramReading(kind="bare", subject=""))


def program_verdict(spelled: str, reading: ProgramReading) -> KernelDecision | None:
    """What one reading earns, spelled as the command that reached it.

    ``None`` for the two hand-offs, a module or a subcommand, which the
    caller judges by what it declares rather than by this criterion.
    """
    subject = reading["subject"]
    match reading["kind"]:
        case "script":
            return KernelDecision(
                "allow", "a script file can be read, where inline code cannot"
            )
        case "inline":
            return KernelDecision(
                "deny",
                f"{spelled} {subject}: inline code leaves nothing behind to review",
                recovery="Write the code to a named script file, which can be"
                " reviewed and run again.",
            )
        case "bare":
            return KernelDecision(
                "deny",
                f"{spelled} with no script file runs whatever it is fed, and"
                " leaves nothing behind to review",
                recovery="Name a script file.",
            )
        case "unread":
            return KernelDecision(
                "deny",
                f"{spelled} {subject}: an option this policy does not read, so"
                " the script it would run is unread",
                recovery="Spell the option's value with `=`, or run the script"
                " without it.",
            )
        case "remote":
            return KernelDecision(
                "deny",
                f"{spelled} {subject}: a program fetched from elsewhere leaves"
                " nothing here to review",
                recovery="Save the script to a file in this checkout, read it,"
                " and run that.",
            )
    return None
