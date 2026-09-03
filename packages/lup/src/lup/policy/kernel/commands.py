# lup: ignore[empty-collection, import-re, re-call, string-split]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Per-command shell classification for the judged executables."""

import posixpath
import re
from typing import TypedDict

from .decision import DecisionEffect, KernelDecision, unjudged, unlisted
from .rows import (
    PathRoleRow,
    PathRuleRow,
    RunnerTargetRow,
    ShellRuleRow,
    UrlScopeRow,
)
from .words import (
    INTERPRETERS,
    flag_matches,
    git_restore_operands,
    key_matches,
    opaque_argument,
    protected_write_target,
    refspec_effects,
    rewrites_only_recoverable_files,
    uv_run_words,
)
from .fetch import decide_fetch

# lup: ignore[constant-declaration] — refusal wording, declared with its verdict
IN_PLACE_SED_REFUSAL = (
    "in-place sed bypasses every gate an edit is judged by — the anti-pattern"
    " table, the review-note gate, the size gate, and the protected paths. For"
    " a rename across many sites, `rename_symbol` resolves scopes an"
    " exact-string substitution cannot tell apart; otherwise make the change"
    " through the edit tool, which is what those gates read"
)
# lup: ignore[constant-declaration] — sed's own short flags, spelled as sed does
SED_SAFE_SHORT_FLAGS = "nErsuz"
# lup: ignore[library-default] — sed's own long spellings of the short flags above
SED_SAFE_LONG_OPTIONS = (
    "--quiet",
    "--silent",
    "--regexp-extended",
    "--separate",
    "--null-data",
)
# lup: ignore[constant-declaration] — the flag characters sed's own `s///` takes
SED_SUBSTITUTE_FLAG_CHARS = "0123456789gpiImM"


def row_verdict(
    row: ShellRuleRow, effect: DecisionEffect, reason: str
) -> KernelDecision:
    """One row's verdict, carrying every fact the row states about itself.

    The purpose is derived rather than declared, because for a shell row it
    is a function of what the row already says: a question about a loss some
    capture would put back is an unrecovered local mutation, one about an
    operation with an effect beyond this machine is an external consequence,
    and one about neither is a question this row has not classified. Deriving
    it keeps a table of several hundred commands from having to restate what
    two of its columns already imply.
    """
    if effect != "ask":
        purpose = None
    elif row["checkpoint"] != "unrecoverable":
        purpose = "unrecovered_local_mutation"
    elif row["effect_class"]:
        purpose = "external_consequence"
    else:
        purpose = None
    return KernelDecision(
        effect,
        reason,
        row["sandbox"],
        checkpoint=row["checkpoint"],
        reviewer=row["reviewer"],
        purpose=purpose,
        rule=row["rule"],
        evaluator="shell-vocabulary",
    )


def apply_command_row(row: ShellRuleRow, arguments: list[str]) -> KernelDecision:
    """Return a row's effect, downgrading an allow to ask on a guarded flag.

    On a flag-guarded row an unresolved expansion could become the guarded
    flag at runtime, so opaque words deny toward an explicit literal binding.
    A non-allow row with ``allow_flags`` de-escalates only when every
    argument is exactly one of those flags — the command's declared pure
    read-only form. One with ``read_verbs`` de-escalates when a declared
    verb appears and every word is a literal free of guarded flags — the
    verb pins the invocation to its query action. One with ``write_markers``
    states that de-escalation negatively, for a command whose read-only form
    is the one carrying nothing extra: it allows when no legible word carries
    a marker. One with ``bare_reads`` carries that to its limit, for a command
    whose reading form carries no words at all: it allows the empty argument
    list and nothing else. One with ``guarded_keys`` states absence about the
    write's subject instead of its form: it allows when no legible word names
    a setting that decides how later commands execute, so the row keeps its
    effect for ``core.hooksPath`` and lets ``user.email`` past.
    """
    if row["effect"] != "allow" and row["allow_flags"] and arguments:
        if all(word in row["allow_flags"] for word in arguments):
            return row_verdict(
                row, "allow", "every argument is a declared read-only flag"
            )
    if row["effect"] != "allow" and row["guarded_keys"] and arguments:
        # Absence is the test, so every word has to be legible on the same
        # strict bar `write_markers` sets: a word this cannot read might be
        # the guarded key, and "no guarded key found" would otherwise be
        # indistinguishable from "none was readable". `git config --local
        # "$KEY" v` is the shape that has to keep asking.
        #
        # Guarded flags block the de-escalation too, which is what keeps
        # `--file` from turning an allowed write into one aimed at a path of
        # the caller's choosing.
        readable = not any(
            opaque_argument(word)
            or "$" in word
            or "`" in word
            or flag_matches(word, row["ask_flags"])
            for word in arguments
        )
        if readable and not any(
            key_matches(word, row["guarded_keys"]) for word in arguments
        ):
            return row_verdict(
                row,
                "allow",
                "no setting that redirects how commands execute is named",
            )
    if row["effect"] != "allow" and row["read_verbs"] and arguments:
        clean = not any(
            opaque_argument(word) or flag_matches(word, row["ask_flags"])
            for word in arguments
        )
        if clean and any(word in row["read_verbs"] for word in arguments):
            return row_verdict(
                row, "allow", "a declared read-only verb pins the query action"
            )
    if row["effect"] != "allow" and row["write_markers"] and arguments:
        # Absence is the test, so every word has to be legible: one this
        # cannot read might carry the marker, and "no marker found" would
        # otherwise be indistinguishable from "no marker was readable".
        #
        # A stricter bar than `opaque_argument`, deliberately. That catches a
        # `$` opening a word, because what it guards are positive tests where
        # a missed expansion still leaves the required verb absent. Here a
        # missed expansion is the whole verdict, and `dd if=$X` splits into
        # `of=` at runtime if `$X` holds a space — measured allowing until
        # this test replaced it.
        legible = not any(
            opaque_argument(word) or "$" in word or "`" in word for word in arguments
        )
        if legible and not any(
            word.startswith(marker)
            for word in arguments
            for marker in row["write_markers"]
        ):
            return row_verdict(
                row,
                "allow",
                "no declared write marker is present, so this only reads",
            )
    # No opacity test here, unlike every de-escalation above. Those read the
    # words to decide, so a word they cannot read is a word that might carry
    # what they are looking for; this one is deciding *on* the absence of
    # words, and a list with nothing in it has nothing to misread.
    if row["effect"] != "allow" and row["bare_reads"] and not arguments:
        return row_verdict(row, "allow", "this command's argument-less form only reads")
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
            return row_verdict(
                row, "ask", row["reason"] or f"{guarded} requires approval"
            )
    if row["effect"] == "allow" and row["ask_refspecs"]:
        # No opacity test of its own: a row declaring refspec effects declares
        # flag effects too, so the block above has already bounced every word
        # this one could not read.
        carried = next(
            (
                (word, effect)
                for word in arguments
                for effect in refspec_effects(word)
                if effect in row["ask_refspecs"]
            ),
            None,
        )
        if carried is not None:
            return row_verdict(
                row,
                "ask",
                row["reason"] or f"{carried[0]} would {carried[1]} a ref",
            )
    return row_verdict(row, row["effect"], row["reason"])


class Subcommand(TypedDict):
    """The subcommand word a command line names, and the arguments after it.

    ``word`` is empty when the line carried only global flags, which leaves
    the default row to answer for it.
    """

    word: str
    remainder: list[str]


def split_subcommand(
    executable: str, arguments: list[str], default: ShellRuleRow | None
) -> Subcommand | KernelDecision:
    """Find the subcommand word, honoring global value-taking and guarded flags.

    A guarded global is answered from the command's own row, so the approval it
    raises carries that row's placement: the call still has to run where the
    command declared it runs, and a question that dropped the placement would
    approve one thing and perform another.

    A guarded global that also takes a value is one that moves the command to
    another tree, so the question names the way through: running the same verb
    from inside that tree is judged on its own and needs no redirect.
    """
    ask_flags = default["ask_flags"] if default else []
    value_flags = default["value_flags"] if default else []
    position = 0
    while position < len(arguments):
        word = arguments[position]
        if not word.startswith("-"):
            return Subcommand(word=word, remainder=arguments[position + 1 :])
        if flag_matches(word, ask_flags) and default is not None:
            redirect = (
                " — or cd into that tree and run it there"
                if flag_matches(word, value_flags)
                else ""
            )
            return row_verdict(
                default,
                "ask",
                f"{executable} global flag {word} requires approval{redirect}",
            )
        position += 2 if word in value_flags else 1
    return Subcommand(word="", remainder=[])


def declares_command(executable: str, rows: list[ShellRuleRow]) -> bool:
    """Whether the vocabulary says anything at all about this executable.

    Asked of an interpreter, which is otherwise refused outright for having
    an eval mode at all. That blanket refusal denied `bun install` -- a
    package operation carrying no code -- in the vocabulary of inline code,
    which is judging a token rather than an effect.

    A positive test, rather than a list of the flags that mean "inline code".
    Such a list is a denylist carrying a security guarantee, so it has to be
    complete to be worth anything -- and a first draft of one already missed
    ``php -r``, the ``-s`` that takes a program on stdin, the bare ``-`` that
    does the same, and ``deno eval``, which is a subcommand no flag list
    could catch. Asking whether the vocabulary declares the executable fails
    the right way instead: an interpreter nothing declares keeps denying
    entirely, and one a project does declare still denies everything outside
    the forms it named, including spellings nobody thought of.
    """
    return any(row["command"] == executable for row in rows)


def decide_command_rows(words: list[str], rows: list[ShellRuleRow]) -> KernelDecision:
    """Classify a command against the erased vocabulary rows by name and depth."""
    executable = posixpath.basename(words[0])
    matches = [row for row in rows if row["command"] == executable]
    if not matches:
        # Unlisted only where the name itself was legible. `$CMD --flag`
        # names nothing a reviewer could weigh: they would be approving
        # whatever the expansion becomes, which is not what they were shown.
        if opaque_argument(executable):
            return unjudged(f"command {executable!r} is not classified")
        return unlisted(f"command {executable!r} is not classified")
    arguments = words[1:]
    if not any(row["subcommand"] for row in matches):
        return apply_command_row(
            next(row for row in matches if not row["subcommand"]), arguments
        )
    default = next((row for row in matches if not row["subcommand"]), None)
    split = split_subcommand(executable, arguments, default)
    if isinstance(split, KernelDecision):
        return split
    subword = split["word"]
    remainder = split["remainder"]
    subrows = [row for row in matches if subword and row["subcommand"] == subword]
    if not subrows:
        if default is None:
            return unlisted(f"{executable} {subword} is not classified")
        return apply_command_row(default, arguments)
    if any(row["operation"] for row in subrows):
        opword = next((word for word in remainder if not word.startswith("-")), "")
        oprows = [row for row in subrows if opword and row["operation"] == opword]
        if oprows:
            return apply_command_row(oprows[0], remainder)
        subdefault = next((row for row in subrows if not row["operation"]), None)
        if subdefault is not None:
            return apply_command_row(subdefault, remainder)
        return unlisted(f"{executable} {subword} {opword} is not classified")
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


def decide_sed_words(
    words: list[str],
    path_roles: list[PathRoleRow] | None = None,
    recoverable_targets: list[str] | None = None,
    recoverable_target_limit: int = 5,
    path_rules: list[PathRuleRow] | None = None,
) -> KernelDecision:
    """Allow only read-only sed: safe flags plus a safe script grammar.

    ``--sandbox`` makes sed itself reject the write and execute commands, so
    the script screen is skipped under it; a script file stays denied toward
    an inline script, because nothing screens what is in it.

    In-place editing is two objections wearing one refusal, and only one of
    them survives a boundary. *Being wrong is unrepairable* is answered by
    the files themselves: a scratch file costs nothing, a committed file with
    no uncommitted change costs a checkout, and the whole change stands in
    the diff either way — the same question a delete is already granted on,
    asked of the verb that overwrites instead of the one that removes. So a
    rewrite whose every named file could be brought back is allowed, with the
    grant saying what it granted.

    *It walks past the gates an edit is judged by* is not answered by
    anything: the anti-pattern table, the review-note gate and the size gate
    are reviewability, and no container and no undo layer enforces them. That
    is what remains once recoverability is established, and it is why the
    grant names `dev check` as where those rules will still be read.

    Where recoverability is not established — a file the host reported
    nothing about, a word that expands at run time, more restorable files
    than a rewrite should sweep — the refusal stands and names the tool that
    does the job it is usually reached for: a rename across many sites is
    `rename_symbol`, which resolves scopes an exact-string substitution
    cannot tell apart. A stated reason still turns that refusal into the
    question it asks for.
    """
    scripts: list[str] = []
    positional: list[str] = []
    script_expected = False
    script_from_options = False
    sandbox = False
    in_place = False
    for word in words[1:]:
        if script_expected:
            scripts.append(word)
            script_expected = False
            continue
        if word.startswith("--"):
            name, separator, value = word.partition("=")
            if name in ("--in-place", "--inplace"):
                in_place = True
                continue
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
                # `-i` takes its backup suffix attached, so everything after
                # it is that suffix rather than more flags — which is also
                # sed's own reading of `-ie`.
                in_place = True
                flags = flags[: flags.index("i")]
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
    if not in_place:
        return KernelDecision("allow", "read-only sed script")
    granted = rewrites_only_recoverable_files(
        positional,
        path_roles or [],
        recoverable_targets,
        recoverable_target_limit,
        path_rules,
    )
    return (
        granted if granted is not None else KernelDecision("deny", IN_PLACE_SED_REFUSAL)
    )


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


# lup: ignore[library-default] — curl's own flags that change reporting and not the request; the value follows curl's manual, not a project's taste
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
# The single letters above, which curl accepts clustered as readily as apart.
# `-sS` is one word to every shell and to curl, and reading it as an unknown
# option refused the request's most ordinary spellings while admitting the
# same flags written with spaces between them.
CURL_SAFE_CLUSTER_LETTERS = "".join(
    flag[1] for flag in CURL_SAFE_FLAGS if len(flag) == 2 and not flag[1].isdigit()
)


def curl_safe_flag(word: str) -> bool:
    """Whether one curl word is a declared reporting flag, clustered or alone."""
    if word in CURL_SAFE_FLAGS:
        return True
    return (
        len(word) > 1
        and word.startswith("-")
        and not word.startswith("--")
        and all(letter in CURL_SAFE_CLUSTER_LETTERS for letter in word[1:])
    )


# lup: ignore[library-default] — curl's own value-taking flags; misreading one shifts the argument scan
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


def curl_url(word: str) -> str:
    """Spell one curl operand the way curl itself resolves it.

    curl accepts a URL with no ``scheme://`` and guesses one, defaulting to
    HTTP — which is how a liveness probe is actually typed, and how its own
    manual documents it. Reading the bare form as malformed put an approval
    question on ``curl localhost:8000/health`` while the identical request
    spelled in full was already declared safe.

    Guessing HTTP where curl guesses HTTP keeps the verdict conservative on
    its own terms: a scope declared for ``https`` alone does not match the
    guess, so an origin reachable only over TLS still asks rather than
    inheriting a grant its scheme never gave.
    """
    return word if "://" in word else f"http://{word}"


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
        if curl_safe_flag(word):
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
        verdict = decide_fetch(curl_url(url), allowed_scopes, denied_scopes)
        if verdict.effect != "allow":
            return verdict
    return KernelDecision("allow", "read-only curl within declared scopes")


# lup: ignore[library-default] — gh's own value-taking flags; misreading one shifts the argument scan
GH_API_VALUE_FLAGS = (
    "-H",
    "--header",
    "-q",
    "--jq",
    "-t",
    "--template",
    "--cache",
    "--hostname",
    "-p",
    "--preview",
)
# lup: ignore[library-default] — gh's own flags that send a request body, which is what makes a call a write however it is spelled
GH_API_BODY_FLAGS = (
    "-f",
    "--raw-field",
    "-F",
    "--field",
    "--input",
)
# lup: ignore[library-default] — the HTTP methods that do not change state; the same pair the curl screen reads, fixed by the protocol rather than by a project's taste
GH_API_READ_METHODS = ("GET", "HEAD")


def decide_gh_api_words(words: list[str]) -> KernelDecision:
    """Allow only read-method ``gh api`` calls, the way curl is screened.

    ``gh api`` is the read path for everything the typed ``gh`` subcommands
    cannot express, so a blanket ask on it asks about the ordinary case. What
    separates a read from a write here is the same thing that separates them
    in curl: the method, plus whether a body is being sent. A field flag
    implies POST even with no ``-X``, which is why it decides on its own
    rather than only informing the method.
    """
    method = "GET"
    expect_value = False
    expect_method = False
    for word in words[2:]:
        if expect_value:
            expect_value = False
            continue
        if expect_method:
            method = word
            expect_method = False
            continue
        if word in ("-X", "--method"):
            expect_method = True
            continue
        if word.startswith("--method="):
            method = word.partition("=")[2]
            continue
        if word in GH_API_BODY_FLAGS or word.partition("=")[0] in GH_API_BODY_FLAGS:
            return KernelDecision(
                "ask",
                "gh api sending a request body can change remote state",
                purpose="external_consequence",
                rule="shell:gh.api",
                evaluator="gh-api-screen",
            )
        if word in GH_API_VALUE_FLAGS:
            expect_value = True
            continue
        if word.partition("=")[0] in GH_API_VALUE_FLAGS:
            continue
        if word.startswith("-"):
            return unjudged(f"gh api option {word!r} is not classified")
        if opaque_argument(word):
            return unjudged(
                "a gh api endpoint that expands at run time is not classified"
            )
    if expect_value or expect_method:
        return unjudged("gh api option has no value")
    if method.upper() not in GH_API_READ_METHODS:
        return KernelDecision(
            "ask",
            f"gh api {method} can change remote state — requires approval",
            purpose="external_consequence",
            rule="shell:gh.api",
            evaluator="gh-api-screen",
        )
    return KernelDecision(
        "allow",
        "read-only gh api call",
        rule="shell:gh.api",
        evaluator="gh-api-screen",
    )


UV_FOREIGN_SOURCE_FLAGS = (
    "--index",
    "--index-url",
    "--extra-index-url",
    "--default-index",
    "--find-links",
    "-f",
    "--no-build-isolation",
    "--no-build-isolation-package",
    "--no-sources",
    "--no-sources-package",
)
"""Where a uv invocation stops obeying what this project declared.

The spellings are uv's; which of them count is a judgement, so this is the
default a caller overrides rather than a table anybody has to fork. A project
that pins its own index, or that has a reason to build without isolation,
says so by naming a different set here.
"""


def uv_package_source(
    arguments: list[str], guarded: tuple[str, ...] = UV_FOREIGN_SOURCE_FLAGS
) -> str | None:
    """The flag naming where packages come from, when one is present.

    A verb obeying the project's own declaration is only obeying it while
    nothing on the command line redirects where packages come from or removes
    the isolation their build code runs in. Either makes it a different act
    wearing the same verb, so it is named back rather than folded into an
    allow.

    An unreadable word answers too. What is being tested is the absence of a
    flag, and a word this cannot read might be one, so the conservative
    direction is to treat it as though it were.
    """
    for word in arguments:
        if opaque_argument(word) or "$" in word or "`" in word:
            return word
        if flag_matches(word, list(guarded)):
            return word
    return None


# lup: Re-installing lup still asks. `uv cache clean` and `uv lock` moved below the install line and are allowed, but `uv sync --all-extras` is judged as an install that fetches and runs build code — so the refresh line still puts a question for a dependency the project already declares, without an escalate marker now rather than with one. `decide_uv` argues that half deliberately: the verb that reaches the network to install is a question, every time. A disagreement to settle rather than an oversight to fix.
def decide_uv(
    words: list[str],
    runner_targets: list[RunnerTargetRow],
    target_tables: list[ShellRuleRow] | None = None,
) -> KernelDecision:
    """Classify a uv invocation, gating dependency and inline-code forms.

    A declared target carries its own verdict, placement and reason, so a
    toolchain that has to run outside the sandbox says so once here rather
    than at each call site — and a target a project refuses is refused here
    rather than falling through to no judgment, which is a different answer:
    it leaves the verdict to the runtime rather than stating one.

    Installing is where a decision was asked for and refused. Fetching a
    package runs its build code, and that code is the escape a supply-chain
    compromise arrives through — so `add` and `sync` both ask, and the fact
    that the packages were declared earlier does not answer it, because the
    thing that changed is not the declaration but what the index now serves
    under it. What is written down here rather than re-argued: the verb that
    reaches the network to install is a question, every time.

    Two verbs sit below that line and one sat above it by omission. `lock`
    and `remove` write files and fetch nothing to execute. A cache is
    reproducible by the command that reads it, so clearing one destroys
    nothing anybody has — and it was reaching no rule at all, which is why a
    refresh line asked with the cache verb as one of its reasons.

    A flag naming where packages come from, or dropping the isolation build
    code runs in, is not the verb it rides on: it is a source nobody
    declared, and it asks even where the bare verb would not — and it is
    asked *before* the target is looked at, for the same reason. Placed after,
    it was unreachable for exactly the spelling that matters:
    ``uv run --with X ruff check .`` asked and
    ``uv run --with X python script.py`` was allowed, because the interpreter
    branch answered and returned first. Order was the whole of that defect.
    """
    subcommand = words[1]
    if subcommand in ("add", "sync"):
        return KernelDecision(
            "ask", "installing a package fetches and runs its build code"
        )
    if subcommand in ("remove", "lock"):
        redirect = uv_package_source(words[2:])
        if redirect is not None:
            return KernelDecision(
                "ask",
                f"{redirect} takes packages from somewhere this project does not"
                " declare — requires approval",
            )
        return KernelDecision("allow", "writes what this project already declares")
    if subcommand == "cache":
        return KernelDecision(
            "allow", "a package cache is rebuilt by the command that reads it"
        )
    if subcommand == "run" and len(words) > 2:
        run_words = uv_run_words(words)
        if not run_words:
            return unjudged("uv run has no command")
        run_command = posixpath.basename(run_words[0])
        bare_target = "/" not in run_words[0]
        # A script file and an inline program are different questions, and
        # answering them together denied the rung the guidance points at for
        # computing something once. What the deny is actually about is
        # reviewability: `-c` leaves nothing behind to read, where a file can
        # be opened, diffed and run again. So the flags keep the refusal and a
        # named script does not.
        rest = run_words[1:]
        inline = [word for word in rest if word in ("-c", "-m")]
        named = [word for word in rest if not word.startswith("-")]
        interpreted = run_command in INTERPRETERS
        if run_command in ("-c", "-m", "--script") or (
            interpreted and (inline or not named)
        ):
            return KernelDecision("deny", "inline code is not allowed")
        # Between the refusal above and the target's own verdict below, which
        # is where the lattice would put it anyway: a deny outranks an ask,
        # and an ask outranks whatever the target says about itself. These
        # flags are not a property of the target at all -- they name a source
        # nobody declared and install from it before the target runs -- so
        # they cannot sit under the target's answer. Measured sitting under
        # it: `uv run --with X ruff check .` asked while
        # `uv run --with X python script.py` was allowed, because the
        # interpreter branch answered and returned first. Then measured
        # sitting above the refusal, which was worse:
        # `uv run --with X python -c 'code'` softened from deny to ask.
        risky = ("--with", "--with-editable", "--with-requirements", "--env-file")
        if any(
            word == option or word.startswith(option + "=")
            for word in words[2:]
            for option in risky
        ):
            return KernelDecision(
                "ask", "uv run --with fetches and executes external code"
            )
        if interpreted:
            return KernelDecision(
                "allow", "a script file can be read, where inline code cannot"
            )
        declared = next(
            (row for row in runner_targets if row["name"] == run_command), None
        )
        if bare_target and declared is not None:
            tabled = [
                row for row in (target_tables or []) if row["command"] == run_command
            ]
            if tabled:
                return decide_command_rows(run_words, tabled)
            return KernelDecision(
                declared["effect"], declared["reason"], declared["sandbox"]
            )
        if bare_target and len(run_words) == 2 and run_words[1] == "--help":
            return KernelDecision("allow", "command help is read-only")
    return unjudged(f"uv {words[1]} is not classified")


def git_checkout_pathspec(words: list[str]) -> KernelDecision | None:
    """Recognize ``git checkout <ref> -- <path>...`` — a ref-sourced restore.

    Content comes from a named commit, so committed state is recoverable
    through the reflog; the branch-switch and index-sourced ``checkout --
    <path>`` forms fall through to their redirect rows, and opaque words
    deny toward explicit literal bindings.
    """
    if len(words) < 5 or words[1] != "checkout" or words[3] != "--":
        return None
    ref = words[2]
    if ref.startswith("-") or opaque_argument(ref):
        return None
    if any(opaque_argument(word) for word in words[4:]):
        return None
    return KernelDecision(
        "allow", "checkout from a named ref restores committed file state"
    )


def git_restore_source(words: list[str]) -> KernelDecision | None:
    """Recognize ``git restore --source=<ref> [--staged|--worktree] <path>...``.

    The ref-sourced twin of ``git checkout <ref> -- <path>``: content comes
    from a named commit, so committed state stays recoverable through the
    reflog. The index-sourced form and opaque words fall through to the
    restore row's ask.
    """
    parsed = git_restore_operands(words)
    if parsed is None or parsed["source"] is None:
        return None
    return KernelDecision(
        "allow", "restore from a named ref recovers committed file state"
    )


def git_restore_unchanged(
    words: list[str], recoverable_targets: list[str], path_rules: list[PathRuleRow]
) -> KernelDecision | None:
    """Recognize an index-sourced ``git restore`` whose paths hold no pending work.

    The row asks because restoring discards what the working tree has that the
    index does not. Where the host reports a path as tracked and carrying no
    uncommitted change, it has nothing the index does not, and the restore
    writes back the bytes already on disk — so the row's question has no
    answer worth putting to anyone. A path with pending work keeps it, which
    is the only case the question was ever about.

    Nothing bounds this the way the delete grant is bounded. That cap counts
    how much committed work one command destroys before a sweep is worth a
    question; this destroys none of it, however many paths are named. What
    does bound it is ownership, which the delete grant defers to for the same
    reason: what a path costs to rebuild is the wrong question about a file
    protected by whose it is, and the two gates read one table so they cannot
    come to differ about one.
    """
    parsed = git_restore_operands(words)
    if parsed is None or parsed["source"] is not None:
        return None
    if not all(path in recoverable_targets for path in parsed["paths"]):
        return None
    protected = protected_write_target(parsed["paths"], path_rules, True)
    if protected is not None:
        return protected
    return KernelDecision("allow", "every restored path already matches the index")


def git_symbolic_ref_read(words: list[str]) -> KernelDecision | None:
    """Recognize ``git symbolic-ref [--short] <name>`` — the form that reports.

    Alone among the query verbs, symbolic-ref spells its write as a second
    operand rather than as a flag, so no flag list separates reading HEAD from
    pointing it elsewhere. One operand and nothing but the reporting flags is
    the read; a second operand, ``--delete``, or a word that expands at run
    time falls through to the row's ask.
    """
    if len(words) < 3 or words[1] != "symbolic-ref":
        return None
    operands = [word for word in words[2:] if not word.startswith("-")]
    flags = [word for word in words[2:] if word.startswith("-")]
    if len(operands) != 1 or any(opaque_argument(word) for word in words[2:]):
        return None
    if any(flag not in ("--short", "-q", "--quiet") for flag in flags):
        return None
    return KernelDecision("allow", "reading a symbolic ref reports where it points")
