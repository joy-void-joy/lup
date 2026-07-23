# lup: ignore[empty-collection, import-re, re-call, set-shape, string-split, tuple-shape]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Hermetic decision core: shell, fetch, and edit verdicts over primitive rows.

The one place permission logic lives. :mod:`lup.policy.rules` delegates every
library-side verdict here. The canonical source is
``packages/lup/src/lup/policy/kernel.py``; :mod:`lup.policy.bundle` reads it
verbatim so harness generation can ship it as ``hooks/runtime/kernel.py`` in
each native plugin. Generated dispatchers call it without lup installed, and
both homes decide identically because both run this source. To stay copyable
it imports only a pinned stdlib set and no other lup module.
"""

import ast
import io
import posixpath
import re
import tokenize
import urllib.parse
from typing import Literal, TypedDict

type DecisionEffect = Literal["allow", "ask", "deny", "defer"]
type PathRuleKind = Literal[
    "exact",
    "subtree",
    "name_prefix",
    "new_subtree",
    "contains_part",
    "new_devtools",
]
type UrlScopeRow = tuple[str, str, int | None, str, str]
type PathRuleRow = tuple[PathRuleKind, str, str, bool]
type AntiPatternRow = tuple[str, str, str, str]


class ShellRuleRow(TypedDict):
    """One erased shell-command rule the kernel matches by executable name.

    ``subcommand`` and ``operation`` are ``""`` at the levels a rule does not
    constrain; ``ask_flags`` downgrades an ``allow`` to ``ask`` when one of the
    named flags appears among the command's remaining words. On the
    command-level row of a subcommand-gated command, ``ask_flags`` guard the
    global options before the subcommand and ``value_flags`` name globals that
    consume the following word (``git -C <path>``), so a flag value is never
    read as the subcommand.
    """

    command: str
    subcommand: str
    operation: str
    effect: DecisionEffect
    ask_flags: list[str]
    value_flags: list[str]
    reason: str


KERNEL_IMPORT_ALLOWLIST = (
    "ast",
    "io",
    "posixpath",
    "re",
    "tokenize",
    "typing",
    "urllib.parse",
)
PASS_THROUGH_WORDS = (
    "env",
    "command",
    "exec",
    "time",
    "nohup",
    "setsid",
    "stdbuf",
)
DANGEROUS_ENV_NAMES = (
    "PATH",
    "IFS",
    "ENV",
    "BASH_ENV",
    "CDPATH",
    "SHELL",
    "HOME",
    "XDG_CONFIG_HOME",
    "PAGER",
    "EDITOR",
    "VISUAL",
    "NODE_OPTIONS",
    "PERL5LIB",
    "PERL5OPT",
    "RUBYLIB",
    "RUBYOPT",
)
DANGEROUS_ENV_PREFIXES = ("LD_", "DYLD_", "PYTHON", "GIT_", "BASH_FUNC_")
SED_SAFE_SHORT_FLAGS = "nErsuz"
SED_SAFE_LONG_OPTIONS = (
    "--quiet",
    "--silent",
    "--regexp-extended",
    "--separate",
    "--null-data",
)
SED_SUBSTITUTE_FLAG_CHARS = "0123456789gpiImM"
INTERPRETERS = (
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "deno",
    "bun",
    "php",
    "sh",
    "bash",
    "zsh",
    "dash",
    "ksh",
    "fish",
)
MARKER_RE = re.compile(r"(#|//)\s*lup\s*:", re.IGNORECASE)
IGNORE_RE = re.compile(
    r"(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?",
    re.IGNORECASE,
)
FILE_IGNORE_RE = re.compile(
    r"^\s*(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?\s*$",
    re.IGNORECASE,
)
ESCALATE_RE = re.compile(
    r"^\s*#[ \t]*lup[ \t]*:[ \t]*escalate\b[ \t]*:?[ \t]*(?P<why>[^\n]*)(?:\n|$)",
    re.IGNORECASE,
)
ESCALATE_HINT = (
    " — reshape the command into the allowed vocabulary, or resubmit with a"
    " leading '# lup: escalate: <why>' line to request approval"
)
SUBSTITUTION_REASON = (
    "command substitution is denied — run the inner command in its own call"
    " and splice its literal output, or read it through <(...) or a pipe"
)


class KernelDecision:
    """Dependency-free allow, ask, deny, or defer result."""

    effect: DecisionEffect
    reason: str

    def __init__(self, effect: DecisionEffect, reason: str = "") -> None:
        if effect not in ("allow", "ask", "deny", "defer"):
            raise ValueError(f"invalid kernel decision effect {effect!r}")
        self.effect = effect
        self.reason = reason


def unjudged(reason: str) -> KernelDecision:
    """One machinery bail-out: the kernel cannot judge, so it defers.

    The shell boundary decides what no-judgment means: a sandboxed
    execution runs confined by the OS, an unsandboxed one converts to a
    deny naming the escalation recipe.
    """
    return KernelDecision("defer", reason)


def timeout_payload(segment: list[str], position: int) -> int:
    """Skip timeout's own options and duration to its wrapped command."""
    value_options = ("-k", "--kill-after", "-s", "--signal")
    while position < len(segment) and segment[position].startswith("-"):
        option = segment[position]
        position += 2 if option in value_options else 1
    return position + 1


def nice_payload(segment: list[str], position: int) -> int:
    """Skip nice's adjustment options to its wrapped command."""
    while position < len(segment) and segment[position].startswith("-"):
        option = segment[position]
        position += 2 if option == "-n" else 1
    return position


def effective_command(segment: list[str]) -> tuple[list[str], bool]:
    """Skip assignments and transparent wrappers, noting dangerous assignments.

    Wrappers that take values (``timeout 5``, ``nice -n 10``) consume them, so
    the returned words start at the command the shell finally executes. A bare
    ``env`` with nothing to wrap is itself the command.
    """
    dangerous = False
    position = 0
    while position < len(segment):
        word = segment[position]
        name, separator, _value = word.partition("=")
        if separator and name.isidentifier():
            dangerous = dangerous or dangerous_env_name(name)
            position += 1
            continue
        executable = posixpath.basename(word)
        if executable == "env" and position + 1 == len(segment):
            return segment[position:], dangerous
        if executable in PASS_THROUGH_WORDS:
            position += 1
            continue
        if executable == "timeout":
            position = timeout_payload(segment, position + 1)
            continue
        if executable == "nice":
            position = nice_payload(segment, position + 1)
            continue
        return segment[position:], dangerous
    return [], dangerous


def command_words(words: list[str]) -> list[str]:
    """Skip assignments and transparent wrappers to the effective command."""
    return effective_command(words)[0]


def uv_run_words(words: list[str]) -> list[str]:
    """Return the executable portion of a ``uv run`` invocation."""
    position = 2
    value_options = (
        "--directory",
        "--package",
        "--project",
        "--with",
        "--with-editable",
    )
    while position < len(words) and words[position].startswith("-"):
        option = words[position]
        if option in ("-c", "-m", "--script"):
            return words[position:]
        position += 2 if option in value_options else 1
    return words[position:]


def is_repository_tmp_script(word: str) -> bool:
    """Recognize only a script beneath the repository-relative ``tmp`` root."""
    normalized = posixpath.normpath(word)
    return not normalized.startswith("/") and normalized.split("/")[0] == "tmp"


def dangerous_env_name(name: str) -> bool:
    """Recognize an environment variable that can redirect a command's execution."""
    return name in DANGEROUS_ENV_NAMES or any(
        name.startswith(prefix) for prefix in DANGEROUS_ENV_PREFIXES
    )


def flag_matches(word: str, flags: list[str]) -> bool:
    """Match a word against a rule's ask-flags, allowing clusters and ``=`` forms."""
    for flag in flags:
        if word == flag:
            return True
        if flag.startswith("--") and word.startswith(flag + "="):
            return True
        if (
            len(flag) == 2
            and flag.startswith("-")
            and word.startswith("-")
            and not word.startswith("--")
            and flag[1] in word[1:]
        ):
            return True
    return False


def opaque_argument(word: str) -> bool:
    """A word whose runtime expansion could inject a guarded flag."""
    if word.startswith("$"):
        return True
    return "}" in word and ("{-" in word or ",-" in word)


def apply_command_row(row: ShellRuleRow, arguments: list[str]) -> KernelDecision:
    """Return a row's effect, downgrading an allow to ask on a guarded flag.

    On a flag-guarded row an unresolved expansion could become the guarded
    flag at runtime, so opaque words deny toward an explicit literal binding.
    """
    if row["effect"] == "allow" and row["ask_flags"]:
        opaque = next(
            (word for word in arguments if opaque_argument(word)),
            None,
        )
        if opaque is not None:
            return unjudged(
                f"argument {opaque!r} could expand into a guarded flag — bind"
                " it to a literal value first"
            )
        guarded = next(
            (word for word in arguments if flag_matches(word, row["ask_flags"])),
            None,
        )
        if guarded is not None:
            return KernelDecision(
                "ask", row["reason"] or f"{guarded} requires approval"
            )
    return KernelDecision(row["effect"], row["reason"])


def split_subcommand(
    executable: str, arguments: list[str], default: ShellRuleRow | None
) -> tuple[str, list[str]] | KernelDecision:
    """Find the subcommand word, honoring global value-taking and guarded flags."""
    ask_flags = default["ask_flags"] if default else []
    value_flags = default["value_flags"] if default else []
    position = 0
    while position < len(arguments):
        word = arguments[position]
        if not word.startswith("-"):
            return word, arguments[position + 1 :]
        if flag_matches(word, ask_flags):
            return KernelDecision(
                "ask", f"{executable} global flag {word} requires approval"
            )
        position += 2 if word in value_flags else 1
    return "", []


def decide_command_rows(words: list[str], rows: list[ShellRuleRow]) -> KernelDecision:
    """Classify a command against the erased vocabulary rows by name and depth."""
    executable = posixpath.basename(words[0])
    matches = [row for row in rows if row["command"] == executable]
    if not matches:
        return unjudged(f"command {executable!r} is not classified")
    arguments = words[1:]
    if not any(row["subcommand"] for row in matches):
        return apply_command_row(
            next(row for row in matches if not row["subcommand"]), arguments
        )
    default = next((row for row in matches if not row["subcommand"]), None)
    split = split_subcommand(executable, arguments, default)
    if isinstance(split, KernelDecision):
        return split
    subword, remainder = split
    subrows = [row for row in matches if subword and row["subcommand"] == subword]
    if not subrows:
        if default is None:
            return unjudged(f"{executable} {subword} is not classified")
        return apply_command_row(default, arguments)
    if any(row["operation"] for row in subrows):
        opword = next((word for word in remainder if not word.startswith("-")), "")
        oprows = [row for row in subrows if opword and row["operation"] == opword]
        if oprows:
            return apply_command_row(oprows[0], remainder)
        subdefault = next((row for row in subrows if not row["operation"]), None)
        if subdefault is not None:
            return apply_command_row(subdefault, remainder)
        return unjudged(f"{executable} {subword} {opword} is not classified")
    return apply_command_row(subrows[0], remainder)


def scan_sed_delimited(script: str, position: int, parts: int) -> int | None:
    """Scan ``parts`` sections after the delimiter at ``position``.

    The delimiter is whatever character sits at ``position``; backslash
    escapes are honored inside sections.
    """
    if position >= len(script):
        return None
    delimiter = script[position]
    if delimiter.isalnum() or delimiter in " \t\n;\\":
        return None
    cursor = position + 1
    seen = 0
    while cursor < len(script) and seen < parts:
        character = script[cursor]
        if character == "\\":
            cursor += 2
            continue
        if character == delimiter:
            seen += 1
        cursor += 1
    return cursor if seen == parts else None


def scan_sed_address(script: str, position: int) -> int | None:
    """Scan one address: a line-number form, ``$``, or a regex form."""
    character = script[position]
    if character == "$":
        return position + 1
    if character.isdigit():
        cursor = position + 1
        while cursor < len(script) and script[cursor].isdigit():
            cursor += 1
        if cursor < len(script) and script[cursor] == "~":
            cursor += 1
            while cursor < len(script) and script[cursor].isdigit():
                cursor += 1
        return cursor
    if character == "+":
        cursor = position + 1
        while cursor < len(script) and script[cursor].isdigit():
            cursor += 1
        return cursor if cursor > position + 1 else None
    end = (
        scan_sed_delimited(script, position, 1)
        if character == "/"
        else scan_sed_delimited(script, position + 1, 1)
        if character == "\\" and position + 1 < len(script)
        else None
    )
    if end is None:
        return None
    while end < len(script) and script[end] in "IM":
        end += 1
    return end


def scan_sed_command(script: str, position: int) -> int | None:
    """Scan one address-guarded command, returning the position after it.

    Accepted commands read the input and write standard output only: print,
    delete, hold-space, branching, labels, blocks, line numbering, text
    insertion, file reading, transliteration, and flag-screened substitution.
    The write and execute forms (``w``, ``W``, ``e``, ``s///e``, ``s///w``)
    fall out as unrecognized trailing characters.
    """
    length = len(script)
    address = scan_sed_address(script, position)
    if address is not None:
        position = address
        while position < length and script[position] in " \t":
            position += 1
        if position < length and script[position] == ",":
            position += 1
            while position < length and script[position] in " \t":
                position += 1
            if position >= length:
                return None
            second = scan_sed_address(script, position)
            if second is None:
                return None
            position = second
    while position < length and script[position] in " \t!":
        position += 1
    if position >= length:
        return None
    command = script[position]
    if command in "pPdDnNgGhHxz=F{}":
        return position + 1
    if command in "qQl":
        cursor = position + 1
        while cursor < length and (script[cursor].isdigit() or script[cursor] == " "):
            cursor += 1
        return cursor
    if command in "btT:":
        cursor = position + 1
        while cursor < length and script[cursor] in " \t":
            cursor += 1
        while cursor < length and (script[cursor].isalnum() or script[cursor] == "_"):
            cursor += 1
        return cursor
    if command in "aicrR":
        newline = script.find("\n", position)
        return length if newline == -1 else newline
    if command == "s":
        end = scan_sed_delimited(script, position + 1, 2)
        if end is None:
            return None
        while end < length and script[end] in SED_SUBSTITUTE_FLAG_CHARS:
            end += 1
        return end
    if command == "y":
        return scan_sed_delimited(script, position + 1, 2)
    return None


def safe_sed_script(script: str) -> bool:
    """Accept only scripts whose every command reads input and prints output."""
    length = len(script)
    position = 0
    while position < length:
        if script[position] in " \t\n;":
            position += 1
            continue
        end = scan_sed_command(script, position)
        if end is None:
            return False
        position = end
    return True


def decide_sed_words(words: list[str]) -> KernelDecision:
    """Allow only read-only sed: safe flags plus a safe script grammar.

    ``--sandbox`` makes sed itself reject the write and execute commands, so
    the script screen is skipped under it; in-place editing and script files
    stay denied toward the Edit tool and inline scripts.
    """
    scripts: list[str] = []
    positional: list[str] = []
    script_expected = False
    script_from_options = False
    sandbox = False
    for word in words[1:]:
        if script_expected:
            scripts.append(word)
            script_expected = False
            continue
        if word.startswith("--"):
            name, separator, value = word.partition("=")
            if name in ("--in-place", "--inplace"):
                return KernelDecision(
                    "deny", "in-place sed bypasses the edit policy — use Edit"
                )
            if name == "--file":
                return KernelDecision(
                    "deny", "sed script files are not screened — inline the script"
                )
            if name == "--sandbox" and not separator:
                sandbox = True
                continue
            if name == "--expression":
                if separator:
                    scripts.append(value)
                script_expected = not separator
                script_from_options = True
                continue
            if name in SED_SAFE_LONG_OPTIONS and not separator:
                continue
            return unjudged(f"sed option {name!r} is not classified")
        if word.startswith("-") and len(word) > 1:
            flags = word[1:]
            if "i" in flags:
                return KernelDecision(
                    "deny", "in-place sed bypasses the edit policy — use Edit"
                )
            if "f" in flags:
                return KernelDecision(
                    "deny", "sed script files are not screened — inline the script"
                )
            if flags.endswith("e"):
                script_expected = True
                script_from_options = True
                flags = flags[:-1]
            if any(flag not in SED_SAFE_SHORT_FLAGS for flag in flags):
                return unjudged(f"sed option {word!r} is not classified")
            continue
        positional.append(word)
    if script_expected:
        return unjudged("sed expression flag has no script")
    if not script_from_options and positional:
        scripts.append(positional.pop(0))
    if not sandbox and not all(safe_sed_script(script) for script in scripts):
        return unjudged("sed script is not classified as read-only")
    return KernelDecision("allow", "read-only sed script")


def safe_awk_program(program: str) -> bool:
    """Accept only awk programs with no exec, command input, or write path.

    ``system`` and ``getline`` reach commands and files, ``@`` covers gawk's
    include/load directives and indirect calls, and a pipe that is not ``||``
    feeds or reads a command. A bare ``>`` (not ``>=``) only writes when the
    program can also ``print``; without a print there is no write path, so
    comparison-only programs like ``$3 > 5`` stay read-only.
    """
    if any(token in program for token in ("system", "getline", "@")):
        return False
    if re.search(r"(?<!\|)\|(?!\|)", program) is not None:
        return False
    redirects = re.search(r">(?!=)", program) is not None
    return not (redirects and "print" in program)


def decide_awk_words(words: list[str]) -> KernelDecision:
    """Allow only read-only awk: separator and variable flags plus a safe program."""
    positional: list[str] = []
    value_expected = False
    options_ended = False
    for word in words[1:]:
        if value_expected:
            value_expected = False
            continue
        if options_ended or not word.startswith("-") or word == "-":
            positional.append(word)
            options_ended = True
            continue
        if word == "--":
            options_ended = True
            continue
        if word in ("-F", "-v"):
            value_expected = True
            continue
        if word.startswith(("-F", "-v")) and not word.startswith("--"):
            continue
        return unjudged(f"awk option {word!r} is not classified")
    if value_expected:
        return unjudged("awk option flag has no value")
    if not positional:
        return unjudged("awk has no program")
    if not safe_awk_program(positional[0]):
        return unjudged("awk program is not classified as read-only")
    return KernelDecision("allow", "read-only awk program")


def decide_find_words(
    words: list[str],
    rows: list[ShellRuleRow],
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> KernelDecision:
    """Classify find, recursing into -exec payloads with {} as a path word.

    Expansions of ``{}`` inherit find's ``./``-prefixed paths, so the payload
    is judged with a literal path word in each placeholder position. The
    interactive ``-ok`` forms would hang a non-interactive shell.
    """
    remaining = [words[0]]
    position = 1
    while position < len(words):
        word = words[position]
        if word in ("-ok", "-okdir"):
            return KernelDecision(
                "deny", "find -ok prompts on a tty — use -exec instead"
            )
        if word in ("-exec", "-execdir"):
            terminator = next(
                (
                    index
                    for index in range(position + 1, len(words))
                    if words[index] in (";", "+")
                ),
                None,
            )
            if terminator is None:
                return unjudged("find -exec payload does not terminate")
            payload = [
                "./x" if piece == "{}" else piece
                for piece in words[position + 1 : terminator]
            ]
            if not payload:
                return unjudged("find -exec payload is empty")
            verdict = decide_shell_segment(payload, rows, allowed_scopes, denied_scopes)
            if verdict.effect != "allow":
                return verdict
            position = terminator + 1
            continue
        remaining.append(word)
        position += 1
    return decide_command_rows(remaining, rows)


CURL_SAFE_FLAGS = (
    "-s",
    "--silent",
    "-S",
    "--show-error",
    "-f",
    "--fail",
    "--fail-with-body",
    "-i",
    "--include",
    "-I",
    "--head",
    "-v",
    "--verbose",
    "--compressed",
    "--no-progress-meter",
    "-g",
    "--globoff",
    "-4",
    "-6",
)
CURL_VALUE_FLAGS = (
    "-H",
    "--header",
    "-m",
    "--max-time",
    "--connect-timeout",
    "--retry",
    "-A",
    "--user-agent",
    "-e",
    "--referer",
    "-r",
    "--range",
)


def decide_curl_words(
    words: list[str],
    allowed_scopes: list[UrlScopeRow],
    denied_scopes: list[UrlScopeRow],
) -> KernelDecision:
    """Allow only read-method curl against the declared fetch scopes.

    Every positional word must be a URL the fetch policy allows; unlisted
    origins stay an approval question and denied origins deny. Flags that
    write files, send data, or carry credentials are not classified.
    """
    urls: list[str] = []
    expect_value = False
    expect_method = False
    method = "GET"
    for word in words[1:]:
        if expect_value:
            expect_value = False
            continue
        if expect_method:
            method = word
            expect_method = False
            continue
        if word in ("-X", "--request"):
            expect_method = True
            continue
        if word.startswith("--request="):
            method = word.partition("=")[2]
            continue
        if word in CURL_SAFE_FLAGS:
            continue
        if word in CURL_VALUE_FLAGS:
            expect_value = True
            continue
        if (
            word.startswith("--")
            and "=" in word
            and word.partition("=")[0] in CURL_VALUE_FLAGS
        ):
            continue
        if word.startswith("-"):
            return unjudged(f"curl option {word!r} is not classified")
        urls.append(word)
    if expect_value or expect_method:
        return unjudged("curl option has no value")
    if method not in ("GET", "HEAD"):
        return KernelDecision(
            "ask", f"curl {method} can change remote state — requires approval"
        )
    if not urls:
        return unjudged("curl has no URL")
    for url in urls:
        verdict = decide_fetch(url, allowed_scopes, denied_scopes)
        if verdict.effect != "allow":
            return verdict
    return KernelDecision("allow", "read-only curl within declared scopes")


def xargs_payload(words: list[str]) -> list[str]:
    """Return the command xargs would run, skipping only xargs's own options."""
    value_options = ("-I", "-i", "-n", "-d", "-P", "-s", "-L", "-a", "-E", "-e")
    position = 1
    while position < len(words) and words[position].startswith("-"):
        option = words[position]
        if "=" in option or (len(option) > 2 and not option.startswith("--")):
            position += 1
        elif option in value_options:
            position += 2
        else:
            position += 1
    return words[position:]


def decide_uv(words: list[str]) -> KernelDecision:
    """Classify a uv invocation, gating dependency and inline-code forms."""
    subcommand = words[1]
    if subcommand in ("add", "sync"):
        return KernelDecision(
            "ask", "dependency changes fetch and execute external code"
        )
    if subcommand in ("remove", "lock"):
        return KernelDecision("allow")
    if subcommand == "run" and len(words) > 2:
        run_words = uv_run_words(words)
        if not run_words:
            return unjudged("uv run has no command")
        run_command = posixpath.basename(run_words[0])
        bare_target = "/" not in run_words[0]
        script = (
            run_words[1]
            if bare_target and run_command in INTERPRETERS and len(run_words) > 1
            else run_words[0]
        )
        if is_repository_tmp_script(script):
            return KernelDecision("allow", "declared temporary script")
        if run_command in INTERPRETERS or run_command in ("-c", "-m", "--script"):
            return KernelDecision("deny", "inline code is not allowed")
        risky = ("--with", "--with-editable", "--with-requirements", "--env-file")
        if any(
            word == option or word.startswith(option + "=")
            for word in words[2:]
            for option in risky
        ):
            return KernelDecision(
                "ask", "uv run --with fetches and executes external code"
            )
        if bare_target and run_command in ("pyright", "pytest", "ruff", "lup-devtools"):
            return KernelDecision("allow")
        if bare_target and len(run_words) == 2 and run_words[1] == "--help":
            return KernelDecision("allow", "command help is read-only")
    return unjudged(f"uv {words[1]} is not classified")


def decide_shell_segment(
    segment: list[str],
    rows: list[ShellRuleRow],
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> KernelDecision:
    """Classify one parsed shell segment against the vocabulary and handlers."""
    while segment and segment[0] == "!":
        segment = segment[1:]
    if not segment:
        return unjudged("shell segment has no command")
    if segment[0] == "[[":
        return KernelDecision("allow", "test expression is read-only")
    words, dangerous = effective_command(segment)
    if dangerous:
        return KernelDecision(
            "ask", "a security-sensitive environment assignment requires approval"
        )
    if not words:
        return unjudged("shell segment has no command")
    executable = posixpath.basename(words[0])
    if executable in INTERPRETERS:
        return KernelDecision(
            "deny", "bare interpreters and inline code are not allowed"
        )
    if executable == "git" and any("ext::" in word for word in words):
        return KernelDecision(
            "ask", "the git ext transport can execute commands — requires approval"
        )
    if executable == "xargs":
        payload = xargs_payload(words)
        if not payload:
            return unjudged("xargs payload is not classified")
        return decide_shell_segment(payload, rows, allowed_scopes, denied_scopes)
    if executable == "curl":
        return decide_curl_words(words, allowed_scopes or [], denied_scopes or [])
    if executable == "find":
        return decide_find_words(words, rows, allowed_scopes, denied_scopes)
    if executable == "sed":
        return decide_sed_words(words)
    if executable in ("awk", "gawk", "mawk"):
        return decide_awk_words(words)
    if executable == "uvx":
        if len(words) > 1 and posixpath.basename(words[1]) in INTERPRETERS:
            return KernelDecision("deny", "inline code is not allowed")
        return unjudged("uvx command is not classified")
    if executable == "uv" and len(words) > 1:
        return decide_uv(words)
    return decide_command_rows(words, rows)


class ShellToken:
    """One lexed shell token: a word, an operator, or a ``<(...)`` inner command.

    ``quoted`` records whether any part of a word came from quotes or escapes,
    which decides whether a heredoc delimiter suppresses body expansion.
    """

    kind: Literal["word", "op", "procsub"]
    text: str
    quoted: bool

    def __init__(
        self,
        kind: Literal["word", "op", "procsub"],
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
                if inner == "`" or (
                    inner == "$"
                    and position + 1 < length
                    and command[position + 1] == "("
                ):
                    return KernelDecision("deny", SUBSTITUTION_REASON)
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
        if character == "`" or (
            character == "$" and position + 1 < length and command[position + 1] == "("
        ):
            return KernelDecision("deny", SUBSTITUTION_REASON)
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


def resolve_redirection(
    tokens: list[ShellToken], index: int
) -> tuple[KernelDecision | None, int]:
    """Classify one redirection, consuming its target and stripping safe forms."""
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
    return (
        KernelDecision("ask", "file redirection is never auto-allowed"),
        target + 1,
    )


def parse_shell_words(command: str, depth: int = 0) -> list[list[str]] | KernelDecision:
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
            inner = parse_shell_words(token.text, depth + 1)
            if isinstance(inner, KernelDecision):
                return inner
            segments.extend(inner)
            current.append("/dev/fd/63")
            index += 1
            continue
        if is_control_operator(token.text):
            if current:
                segments.append(current)
                current = []
            index += 1
            continue
        verdict, index = resolve_redirection(tokens, index)
        if verdict is not None:
            return verdict
    if current:
        segments.append(current)
    if not segments:
        return unjudged("shell command has no executable segment")
    return segments


def loop_leader(segment: list[str]) -> str:
    """The segment's effective first word, looking through a leading ``do``."""
    if segment and segment[0] == "do" and len(segment) > 1:
        return segment[1]
    return segment[0] if segment else ""


def find_loop_end(segments: list[list[str]], start: int) -> int | None:
    """Locate the bare ``done`` segment closing the loop opened at ``start``."""
    depth = 1
    for index in range(start + 1, len(segments)):
        if segments[index] == ["done"]:
            depth -= 1
            if depth == 0:
                return index
        elif loop_leader(segments[index]) in ("for", "while", "until"):
            depth += 1
    return None


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


def literal_loop_word(word: str) -> bool:
    """A word whose runtime expansion is exactly its lexed text."""
    return not word.startswith(("~", "/dev/fd/")) and not any(
        character in "$*?[" for character in word
    )


def argument_safe_words(words: list[str], rows: list[ShellRuleRow]) -> bool:
    """True when the command's row allows regardless of argument content.

    A loop variable bound to a non-literal word list can expand to any word,
    including a flag-shaped one, so only a single unguarded command-level
    allow row qualifies — flag-guarded rows and the specially parsed
    executables do not.
    """
    executable = posixpath.basename(words[0])
    if executable in INTERPRETERS or executable in ("sed", "git", "uv", "uvx", "xargs"):
        return False
    matches = [row for row in rows if row["command"] == executable]
    return (
        len(matches) == 1
        and not matches[0]["subcommand"]
        and matches[0]["effect"] == "allow"
        and not matches[0]["ask_flags"]
    )


type ShellBinding = tuple[str, str | None]
"""One frozen variable binding: name to literal value, or None when opaque."""


def bind_name(
    bindings: tuple[ShellBinding, ...], name: str, value: str | None
) -> tuple[ShellBinding, ...]:
    """Rebind one name immutably, shadowing any earlier binding of it."""
    kept = tuple(pair for pair in bindings if pair[0] != name)
    return (*kept, (name, value))


def pure_assignment_names(segment: list[str]) -> list[tuple[str, str | None]] | None:
    """The (name, literal value) pairs of an assignment-only segment."""
    pairs: list[tuple[str, str | None]] = []
    for word in segment:
        name, separator, value = word.partition("=")
        if not separator or not name.isidentifier():
            return None
        pairs.append((name, value if literal_loop_word(value) else None))
    return pairs


def read_bindings(
    words: list[str], bindings: tuple[ShellBinding, ...]
) -> tuple[ShellBinding, ...] | KernelDecision:
    """Bindings extended by the read builtin's targets as opaque values."""
    names: list[str] = []
    for word in words[1:]:
        if word == "-r":
            continue
        if word.startswith("-"):
            return unjudged(f"read option {word!r} is not classified")
        if not word.isidentifier():
            return unjudged("read target is not a plain variable")
        names.append(word)
    for name in names or ["REPLY"]:
        if dangerous_env_name(name):
            return KernelDecision(
                "ask", "binding a security-sensitive variable requires approval"
            )
        bindings = bind_name(bindings, name, None)
    return bindings


def resolve_segment_bindings(
    segment: list[str],
    bindings: tuple[ShellBinding, ...],
    rows: list[ShellRuleRow],
    gate_opaque: bool,
) -> list[str] | KernelDecision:
    """Substitute literal bindings and gate opaque ones by argument safety.

    A literal binding instantiates its references exactly, so guarded flags
    are judged as the words they become. An opaque binding (``read``, a
    non-literal assignment) can expand to any word, so a referencing segment
    must name an argument-safe command.
    """
    resolved = segment
    for name, value in bindings:
        if not any(references_variable(word, name) for word in resolved):
            continue
        if value is not None:
            resolved = [substitute_variable(word, name, value) for word in resolved]
            continue
        if not gate_opaque:
            continue
        words = command_words(resolved)
        if not words or not argument_safe_words(words, rows):
            return unjudged("an opaquely bound variable could become a guarded flag")
    return resolved


def decide_for_body(
    name: str,
    loop_words: list[str],
    body: list[list[str]],
    rows: list[ShellRuleRow],
    depth: int,
    bindings: tuple[ShellBinding, ...] = (),
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> list[KernelDecision]:
    """Classify a ``for`` body once per literal loop word, or gated when opaque.

    A literal word list instantiates the body exactly, so a word landing in a
    guarded flag position is judged as the flag it becomes. A non-literal list
    (globs, expansions) can become any word, so every segment referencing the
    variable must name an argument-safe command before one placeholder pass.
    """
    if len(loop_words) > 16:
        return [unjudged("loop word list is too long to instantiate")]

    def instantiations(values: list[str]) -> list[KernelDecision]:
        return [
            decision
            for value in values
            for decision in decide_segment_list(
                [
                    [substitute_variable(word, name, value) for word in segment]
                    for segment in body
                ],
                rows,
                depth + 1,
                bindings,
                allowed_scopes,
                denied_scopes,
            )
        ]

    if all(literal_loop_word(word) for word in loop_words):
        return instantiations(loop_words or ["x"])
    for segment in body:
        if any(references_variable(word, name) for word in segment):
            words = command_words(segment)
            if not words or not argument_safe_words(words, rows):
                return [
                    unjudged(
                        "loop words are not literal, so a variable argument"
                        " could become a guarded flag"
                    )
                ]
    return instantiations(["x"])


def decide_loop(
    segments: list[list[str]],
    start: int,
    rows: list[ShellRuleRow],
    depth: int,
    bindings: tuple[ShellBinding, ...] = (),
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> tuple[list[KernelDecision], int] | KernelDecision:
    """Classify one loop construct, returning its decisions and the next index.

    A while/until condition and body classify as one sequential list, so a
    ``read`` in the condition binds for the body without shared mutation.
    """
    if depth >= 2:
        return unjudged("loops nest too deeply")
    end = find_loop_end(segments, start)
    if end is None:
        return unjudged("loop construct does not parse")
    interior = segments[start + 1 : end]
    do_index = next(
        (position for position, seg in enumerate(interior) if seg[0] == "do"), None
    )
    if do_index is None:
        return unjudged("loop construct does not parse")
    body = [seg for seg in [interior[do_index][1:], *interior[do_index + 1 :]] if seg]
    if not body:
        return unjudged("loop body is empty")
    condition = interior[:do_index]
    match segments[start]:
        case ["for", name, "in", *loop_words] if name.isidentifier():
            if condition:
                return unjudged("loop construct does not parse")
            return (
                decide_for_body(
                    name,
                    loop_words,
                    body,
                    rows,
                    depth,
                    bindings,
                    allowed_scopes,
                    denied_scopes,
                ),
                end + 1,
            )
        case ["for", *_rest]:
            return unjudged("loop form is not classified")
        case [_keyword, *condition_head]:
            conditions = [seg for seg in [condition_head, *condition] if seg]
            if not conditions:
                return unjudged("loop condition is empty")
            decisions = decide_segment_list(
                [*conditions, *body],
                rows,
                depth + 1,
                bindings,
                allowed_scopes,
                denied_scopes,
            )
            return decisions, end + 1
    return unjudged("loop construct does not parse")


CASE_TERMINATORS = (";;", ";&", ";;&")


def strip_structure_keywords(segment: list[str]) -> list[str]:
    """Drop leading conditional keywords — pure structure, never commands."""
    index = 0
    while index < len(segment) and segment[index] in ("then", "else", "elif"):
        index += 1
    return segment[index:]


def find_conditional_end(segments: list[list[str]], start: int) -> int | None:
    """Locate the bare ``fi`` segment closing the conditional at ``start``."""
    depth = 1
    for index in range(start + 1, len(segments)):
        if segments[index] == ["fi"]:
            depth -= 1
            if depth == 0:
                return index
        else:
            stripped = strip_structure_keywords(segments[index])
            if stripped and stripped[0] == "if":
                depth += 1
    return None


def decide_conditional(
    segments: list[list[str]],
    start: int,
    rows: list[ShellRuleRow],
    depth: int,
    bindings: tuple[ShellBinding, ...] = (),
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> tuple[list[KernelDecision], int] | KernelDecision:
    """Classify one ``if`` construct: conditions and branches recursively."""
    if depth >= 2:
        return unjudged("conditionals nest too deeply")
    end = find_conditional_end(segments, start)
    if end is None:
        return unjudged("conditional construct does not parse")
    interior: list[list[str]] = []
    for segment in [segments[start][1:], *segments[start + 1 : end]]:
        stripped = strip_structure_keywords(segment)
        if stripped:
            interior.append(stripped)
    if not interior:
        return unjudged("conditional is empty")
    return (
        decide_segment_list(
            interior, rows, depth + 1, bindings, allowed_scopes, denied_scopes
        ),
        end + 1,
    )


def decide_case(
    segments: list[list[str]],
    start: int,
    rows: list[ShellRuleRow],
    depth: int,
    bindings: tuple[ShellBinding, ...] = (),
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> tuple[list[KernelDecision], int] | KernelDecision:
    """Classify one ``case`` construct: patterns are match data, bodies recurse."""
    if depth >= 2:
        return unjudged("case constructs nest too deeply")
    opener = segments[start]
    if len(opener) < 3 or opener[2] != "in":
        return unjudged("case construct does not parse")
    body: list[list[str]] = []
    collecting = False
    nested = 0
    end = None
    for index in range(start + 1, len(segments)):
        segment = segments[index]
        if nested == 0 and segment == ["esac"]:
            end = index
            break
        if nested == 0 and segment == [")"]:
            collecting = True
        elif nested == 0 and len(segment) == 1 and segment[0] in CASE_TERMINATORS:
            collecting = False
        elif nested == 0 and segment == ["("]:
            continue
        elif nested == 0 and not collecting:
            continue
        elif segment == ["esac"]:
            nested -= 1
            body.append(segment)
        elif segment[0] == "case":
            nested += 1
            body.append(segment)
        else:
            body.append(segment)
    if end is None:
        return unjudged("case construct does not parse")
    if not body:
        return [], end + 1
    return (
        decide_segment_list(
            body, rows, depth + 1, bindings, allowed_scopes, denied_scopes
        ),
        end + 1,
    )


def decide_segment_list(
    segments: list[list[str]],
    rows: list[ShellRuleRow],
    depth: int = 0,
    bindings: tuple[ShellBinding, ...] = (),
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> list[KernelDecision]:
    """Classify a segment list, grouping structured constructs recursively.

    Bindings are frozen pairs: an assignment or read rebinds by producing a
    new tuple for the segments that follow, recursion receives the current
    value, and nothing mutates across scopes. A reference the walk cannot
    resolve to a literal stays a live ``$`` word for the guarded-flag gates.
    """
    segments = list(segments)
    decisions: list[KernelDecision] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        if segment in (["("], [")"]):
            index += 1
            continue
        if len(segment) == 1 and segment[0] in CASE_TERMINATORS:
            return [
                *decisions,
                unjudged("case terminator outside a case construct"),
            ]
        while segment and segment[0] == "{":
            segment = segment[1:]
        while segment and segment[-1] == "}":
            segment = segment[:-1]
        if not segment:
            index += 1
            continue
        structural = segment[0] in ("for", "while", "until", "if", "case")
        resolved = resolve_segment_bindings(
            segment, bindings, rows, gate_opaque=not structural
        )
        if isinstance(resolved, KernelDecision):
            return [*decisions, resolved]
        segment = resolved
        segments[index] = segment
        if structural:
            match segment[0]:
                case "for" | "while" | "until":
                    outcome = decide_loop(
                        segments,
                        index,
                        rows,
                        depth,
                        bindings,
                        allowed_scopes,
                        denied_scopes,
                    )
                case "if":
                    outcome = decide_conditional(
                        segments,
                        index,
                        rows,
                        depth,
                        bindings,
                        allowed_scopes,
                        denied_scopes,
                    )
                case _:
                    outcome = decide_case(
                        segments,
                        index,
                        rows,
                        depth,
                        bindings,
                        allowed_scopes,
                        denied_scopes,
                    )
            if isinstance(outcome, KernelDecision):
                return [*decisions, outcome]
            grouped, index = outcome
            decisions.extend(grouped)
            continue
        assignments = pure_assignment_names(segment)
        if assignments is not None:
            if any(dangerous_env_name(name) for name, _value in assignments):
                decisions.append(
                    KernelDecision(
                        "ask",
                        "a security-sensitive environment assignment requires approval",
                    )
                )
                index += 1
                continue
            for name, value in assignments:
                bindings = bind_name(bindings, name, value)
            index += 1
            continue
        words, _dangerous = effective_command(segment)
        if words and posixpath.basename(words[0]) == "read":
            extended = read_bindings(words, bindings)
            if isinstance(extended, KernelDecision):
                return [*decisions, extended]
            bindings = extended
            index += 1
            continue
        decisions.append(
            decide_shell_segment(segment, rows, allowed_scopes, denied_scopes)
        )
        index += 1
    return decisions


def classify_shell(
    command: str,
    rows: list[ShellRuleRow],
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
) -> KernelDecision:
    """Conservatively classify every segment in one shell command."""
    segments = parse_shell_words(command)
    if isinstance(segments, KernelDecision):
        return segments
    decisions = decide_segment_list(
        segments, rows, 0, (), allowed_scopes, denied_scopes
    )
    denied = next((item for item in decisions if item.effect == "deny"), None)
    if denied is not None:
        return denied
    asked = next((item for item in decisions if item.effect == "ask"), None)
    if asked is not None:
        return asked
    deferred = next((item for item in decisions if item.effect == "defer"), None)
    if deferred is not None:
        return deferred
    return KernelDecision("allow", "every shell segment is declared safe")


def decide_shell(
    command: str,
    rows: list[ShellRuleRow],
    allowed_scopes: list[UrlScopeRow] | None = None,
    denied_scopes: list[UrlScopeRow] | None = None,
    sandboxed: bool = False,
) -> KernelDecision:
    """Classify one command, honoring an escalation marker and hinting denies.

    A leading ``# lup: escalate: <why>`` line promotes a classified deny or
    ask to an approval question carrying the agent's stated reason, so the
    human sees intent at the moment of judgment. A deny without a marker names
    the escalation recipe: unjudged work bounces back to the agent, which
    reshapes it into the allowed vocabulary or deliberately promotes it.
    When the execution is sandboxed, unjudged work defers instead: the OS
    boundary confines it, and only an unsandboxed escape returns to the
    deny lattice.
    """
    marker = ESCALATE_RE.match(command)
    if marker is not None:
        why = marker.group("why").strip()
        if not why:
            return KernelDecision(
                "deny", "escalation requires a stated reason" + ESCALATE_HINT
            )
        inner = classify_shell(
            command[marker.end() :], rows, allowed_scopes, denied_scopes
        )
        if inner.effect == "allow":
            return inner
        return KernelDecision("ask", f"escalated ({why}): {inner.reason}")
    decision = classify_shell(command, rows, allowed_scopes, denied_scopes)
    if decision.effect == "defer" and sandboxed:
        return decision
    if decision.effect in ("deny", "defer"):
        return KernelDecision("deny", decision.reason + ESCALATE_HINT)
    return decision


def url_matches_scope(
    scheme: str,
    hostname: str,
    port: int | None,
    path: str,
    scope: UrlScopeRow,
) -> bool:
    """Compare parsed URL components with one primitive scope row."""
    expected_scheme, expected_host, expected_port, path_prefix, _reason = scope
    return (
        scheme == expected_scheme
        and hostname == expected_host
        and port == expected_port
        and path.startswith(path_prefix)
    )


def decide_fetch(
    url: str,
    allowed_scopes: list[UrlScopeRow],
    denied_scopes: list[UrlScopeRow],
) -> KernelDecision:
    """Deny matching scopes first, allow declared scopes, and ask otherwise."""
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return KernelDecision("ask", "malformed URL requires approval")
    if not parsed.scheme or hostname is None:
        return KernelDecision("ask", "malformed URL requires approval")
    denied = next(
        (
            scope
            for scope in denied_scopes
            if url_matches_scope(parsed.scheme, hostname, port, parsed.path, scope)
        ),
        None,
    )
    if denied is not None:
        return KernelDecision("deny", denied[4] or "URL is denied")
    allowed = next(
        (
            scope
            for scope in allowed_scopes
            if url_matches_scope(parsed.scheme, hostname, port, parsed.path, scope)
        ),
        None,
    )
    if allowed is not None:
        return KernelDecision("allow", allowed[4])
    return KernelDecision("ask", "URL is outside the declared documentation scopes")


def python_tokens(source: str) -> list[tokenize.TokenInfo] | None:
    """Tokenize Python source, returning ``None`` for incomplete syntax."""
    try:
        return list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None


def python_comment_columns(source: str) -> dict[int, int] | None:
    """Map Python line numbers to real comment-token columns."""
    tokens = python_tokens(source)
    if tokens is None:
        return None
    return {
        token.start[0]: token.start[1]
        for token in tokens
        if token.type == tokenize.COMMENT
    }


def docstring_lines(source: str) -> set[int]:
    """Return lines occupied by bare string-expression documentation."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.end_lineno is not None
        ):
            lines.update(range(node.lineno, node.end_lineno + 1))
    return lines


def string_literal_lines(source: str) -> set[int]:
    """Return every line touched by a Python string token."""
    tokens = python_tokens(source)
    if tokens is None:
        return set()
    lines: set[int] = set()
    for token in tokens:
        if token.type == tokenize.STRING:
            lines.update(range(token.start[0], token.end[0] + 1))
    return lines


def mask_python_string_literals(source: str) -> list[str]:
    """Blank string-token characters while preserving line and column positions."""
    lines = [list(line) for line in source.splitlines()]
    tokens = python_tokens(source)
    if tokens is None:
        return source.splitlines()
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        start_line, start_column = token.start
        end_line, end_column = token.end
        for line_number in range(start_line, end_line + 1):
            line = lines[line_number - 1]
            first = start_column if line_number == start_line else 0
            last = end_column if line_number == end_line else len(line)
            line[first:last] = [" "] * (last - first)
            if line_number == start_line and last - first >= 2:
                line[first : first + 2] = ["'", "'"]
    return ["".join(line) for line in lines]


def python_code_lines(source: str) -> list[str]:
    """Blank string and comment tokens while preserving line and column positions."""
    lines = [list(line) for line in mask_python_string_literals(source)]
    tokens = python_tokens(source)
    if tokens is None:
        return ["".join(line) for line in lines]
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        start_line, start_column = token.start
        line = lines[start_line - 1]
        line[start_column : token.end[1]] = [" "] * (token.end[1] - start_column)
    return ["".join(line) for line in lines]


def marker_count(source: str, python_source: bool = False) -> int:
    """Count review markers, excluding markers inside ordinary Python strings."""
    if not python_source:
        return len(MARKER_RE.findall(source))
    tokens = python_tokens(source)
    if tokens is None:
        return len(MARKER_RE.findall(source))
    documentation = docstring_lines(source)
    return sum(
        len(MARKER_RE.findall(token.string))
        for token in tokens
        if token.type == tokenize.COMMENT
        or (
            token.type == tokenize.STRING
            and any(
                line in documentation
                for line in range(token.start[0], token.end[0] + 1)
            )
        )
    )


def empty_collection_exempt_lines(source: str) -> set[int]:
    """Return empty-collection lines whose AST context makes the seed deliberate."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    def is_empty_literal(node: ast.expr | None) -> bool:
        match node:
            case ast.Dict(keys=[]) | ast.List(elts=[]):
                return True
            case ast.Call(func=ast.Name(id="set"), args=[], keywords=[]):
                return True
        return False

    def is_self_attribute(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )

    exempt: set[int] = set()

    def mark(value: ast.expr | None) -> None:
        if value is not None and is_empty_literal(value):
            exempt.add(value.lineno)

    def is_loop(node: ast.AST) -> bool:
        return isinstance(node, ast.For | ast.AsyncFor | ast.While)

    def mutated_name(node: ast.AST) -> str | None:
        match node:
            case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=attr)) if (
                attr
                in (
                    "append",
                    "appendleft",
                    "extend",
                    "add",
                    "update",
                    "insert",
                    "setdefault",
                )
            ):
                return name
            case ast.Assign(targets=[ast.Subscript(value=ast.Name(id=name))]):
                return name
            case ast.AugAssign(
                target=ast.Name(id=name) | ast.Subscript(value=ast.Name(id=name))
            ):
                return name
        return None

    def exempt_scope_seeds(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        feeding: dict[str, list[bool]] = {}
        for loop in ast.walk(scope):
            if not is_loop(loop):
                continue
            tolerant = any(isinstance(inner, ast.Try) for inner in ast.walk(loop))
            for inner in ast.walk(loop):
                name = mutated_name(inner)
                if name is not None:
                    feeding.setdefault(name, []).append(tolerant)

        def visit(node: ast.AST, in_loop: bool) -> None:
            for child in ast.iter_child_nodes(node):
                match child:
                    case (
                        ast.FunctionDef()
                        | ast.AsyncFunctionDef()
                        | ast.ClassDef()
                        | ast.Lambda()
                    ):
                        continue
                    case (
                        ast.Assign(targets=[ast.Name(id=name)], value=value)
                        | ast.AnnAssign(target=ast.Name(id=name), value=value)
                    ) if is_empty_literal(value):
                        loops = feeding[name] if name in feeding else None
                        if in_loop:
                            if loops is not None:
                                mark(value)
                        elif loops is None or all(loops):
                            mark(value)
                visit(child, in_loop or is_loop(child))

        visit(scope, False)

    for node in ast.walk(tree):
        match node:
            case ast.Call(keywords=keywords):
                for keyword in keywords:
                    mark(keyword.value)
            case ast.ExceptHandler(body=handler_body):
                for statement in handler_body:
                    match statement:
                        case ast.Assign(value=value) | ast.AnnAssign(value=value):
                            mark(value)
            case ast.ClassDef(body=body):
                for statement in body:
                    if isinstance(statement, ast.AnnAssign):
                        mark(statement.value)
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if node.name == "__init__":
                    for statement in ast.walk(node):
                        match statement:
                            case ast.Assign(targets=targets, value=value) if all(
                                is_self_attribute(target) for target in targets
                            ):
                                mark(value)
                            case ast.AnnAssign(target=target, value=value) if (
                                is_self_attribute(target)
                            ):
                                mark(value)
                exempt_scope_seeds(node)
    return exempt


def added_line_numbers(before: str | None, after: str | None) -> dict[int, bool]:
    """Identify added line positions with duplicate-line accounting."""
    remaining = before.splitlines() if before is not None else []
    added: dict[int, bool] = {}
    for number, line in enumerate((after or "").splitlines(), start=1):
        if line in remaining:
            remaining.remove(line)
        else:
            added[number] = True
    return added


def added_lines(before: str | None, after: str | None) -> list[str]:
    """Return added lines with duplicate-line accounting."""
    remaining = before.splitlines() if before is not None else []
    added: list[str] = []
    for line in (after or "").splitlines():
        if line in remaining:
            remaining.remove(line)
        else:
            added.append(line)
    return added


def is_record_class(node: ast.ClassDef) -> bool:
    """Recognize a declarative record whose field lines are not real changes."""
    records = ("BaseModel", "TypedDict", "Enum", "IntEnum", "StrEnum", "NamedTuple")
    return any(
        (isinstance(base, ast.Name) and base.id in records)
        or (isinstance(base, ast.Attribute) and base.attr in records)
        for base in node.bases
    )


def non_real_lines(source: str) -> set[int]:
    """Return line numbers that do not count toward the small-change gate.

    Blank lines, comments, string and docstring bodies (already blanked by
    ``python_code_lines``), imports, and the field declarations of a pydantic
    or ``TypedDict`` record are boilerplate rather than logic.
    """
    code = python_code_lines(source)
    excluded = {
        number
        for number, line in enumerate(code, start=1)
        if not line or line.isspace()
    }
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return excluded
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom) and node.end_lineno:
            excluded.update(range(node.lineno, node.end_lineno + 1))
        if isinstance(node, ast.ClassDef) and is_record_class(node):
            for statement in node.body:
                if (
                    isinstance(statement, ast.AnnAssign | ast.Assign)
                    and statement.end_lineno
                ):
                    excluded.update(range(statement.lineno, statement.end_lineno + 1))
    return excluded


def real_added_line_count(
    before: str | None, after: str | None, python_source: bool
) -> int:
    """Count added lines that carry real code, ignoring boilerplate."""
    added = added_line_numbers(before, after)
    lines = (after or "").splitlines()
    if not python_source:
        return sum(
            1
            for number in added
            if lines[number - 1] and not lines[number - 1].isspace()
        )
    excluded = non_real_lines(after or "")
    return sum(1 for number in added if number not in excluded)


def ignore_rule_ids(match: re.Match[str]) -> tuple[str, ...] | None:
    """Return typed ids, or ``None`` for a bare suppression."""
    raw = match.group("ids")
    if raw is None:
        return None
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def file_ignore(source: str) -> tuple[bool, tuple[str, ...] | None]:
    """Return whether a file-level suppression exists and the ids it names."""
    for line in source.splitlines()[:10]:
        match = FILE_IGNORE_RE.match(line)
        if match is not None:
            return True, ignore_rule_ids(match)
    return False, ()


def antipattern_decision(
    before: str | None,
    after: str,
    rows: list[AntiPatternRow],
    python_source: bool,
) -> KernelDecision | None:
    """Reject newly added unsuppressed anti-patterns and ask on suppressions.

    Each row carries the syntactic context it inspects: a "code" rule is
    matched against token-masked Python (string literals and comments both
    blanked) so prose never trips it, while a "comment" rule targets comment
    directives and sees comments intact. Without a tokenizer (non-Python
    files, fragments that fail to tokenize) every rule scans the raw line.
    """
    added = added_line_numbers(before, after)
    original_lines = after.splitlines()
    scanned_lines = (
        mask_python_string_literals(after) if python_source else original_lines
    )
    code_lines = python_code_lines(after) if python_source else original_lines
    exempt = empty_collection_exempt_lines(after) if python_source else set()
    comment_columns = python_comment_columns(after) if python_source else None
    has_file_ignore, disabled_ids = file_ignore(after)
    for number in added:
        original = original_lines[number - 1]
        directive = IGNORE_RE.search(original)
        if directive is not None and (
            not python_source
            or comment_columns is None
            or (
                number in comment_columns
                and comment_columns[number] == directive.start()
            )
        ):
            return KernelDecision("ask", "edit introduces an antipattern suppression")
    tokenized = comment_columns is not None
    for number in added:
        masked = scanned_lines[number - 1].strip()
        if not tokenized and masked.startswith("#") and "type:" not in masked:
            continue
        code = code_lines[number - 1].strip()
        for rule_id, pattern, message, context in rows:
            stripped = code if tokenized and context == "code" else masked
            if not stripped:
                continue
            if rule_id == "empty-collection" and number in exempt:
                continue
            if re.search(pattern, stripped) is None:
                continue
            if has_file_ignore and (disabled_ids is None or rule_id in disabled_ids):
                continue
            directive = IGNORE_RE.search(original_lines[number - 1])
            if directive is not None:
                covered = ignore_rule_ids(directive)
                if covered is None or rule_id in covered:
                    return KernelDecision(
                        "ask", "edit introduces an antipattern suppression"
                    )
            return KernelDecision(
                "deny", f"{message} (rule {rule_id} — see docs/rules.md)"
            )
    return None


def normalized_path(path: str) -> str:
    """Normalize one portable path without resolving against the filesystem."""
    return posixpath.normpath(path.replace("\\", "/"))


def path_rule_matches(path: str, path_exists: bool, row: PathRuleRow) -> bool:
    """Evaluate one primitive protected-path rule."""
    kind, value, _reason, _allow_autonomous = row
    portable = normalized_path(path)
    expected = normalized_path(value)
    parts = tuple(part for part in portable.split("/") if part)
    match kind:
        case "exact":
            return portable == expected
        case "subtree":
            return portable == expected or portable.startswith(expected + "/")
        case "name_prefix":
            return posixpath.basename(portable).startswith(value)
        case "new_subtree":
            return (
                portable == expected or portable.startswith(expected + "/")
            ) and not path_exists
        case "contains_part":
            return value in parts and not (
                portable == f"/{value}" or portable.startswith(f"/{value}/")
            )
        case "new_devtools":
            return (
                any(
                    parts[index] == "src"
                    and index + 2 < len(parts)
                    and parts[index + 2] == "devtools"
                    for index in range(len(parts))
                )
                and not path_exists
            )
        case _:
            raise ValueError(f"invalid path rule kind {kind!r}")


def decide_edit(
    path: str,
    before: str | None,
    after: str | None,
    *,
    path_exists: bool,
    path_rules: list[PathRuleRow],
    antipattern_rows: list[AntiPatternRow],
    maximum_added_lines: int = 3,
    autonomous: bool = False,
    python_source: bool = False,
) -> KernelDecision:
    """Apply anti-pattern, path, marker, full-write, deletion, and size gates."""
    previous = before or ""
    updated = after or ""
    if after is not None:
        antipattern = antipattern_decision(
            before, after, antipattern_rows, python_source
        )
        if antipattern is not None:
            return antipattern
    protected = next(
        (row for row in path_rules if path_rule_matches(path, path_exists, row)),
        None,
    )
    if protected is not None and not (autonomous and protected[3]):
        return KernelDecision("ask", protected[2])
    if marker_count(previous, python_source) != marker_count(updated, python_source):
        return KernelDecision("ask", "edit changes inline review markers")
    if before is None:
        if autonomous:
            return KernelDecision("allow", "reviewed autonomous full write")
        return KernelDecision("ask", "full-file writes require approval")
    if after is None or after == "":
        return KernelDecision("allow", "pure deletion")
    if real_added_line_count(before, after, python_source) > maximum_added_lines:
        if autonomous:
            return KernelDecision("allow", "reviewed autonomous edit")
        return KernelDecision("defer", "edit exceeds the small-change gate")
    return KernelDecision("allow", "small safe edit")
