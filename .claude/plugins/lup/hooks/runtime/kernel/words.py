# lup: ignore[empty-collection, set-shape, string-split, tuple-shape]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Word-level shell helpers: expansion safety, flags, and payloads."""

import posixpath

from .decision import KernelDecision, SUBSTITUTION_SENTINEL

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
    "TMPDIR",
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
GENERATED_PLUGIN_ROOTS = (".claude/plugins", ".codex/plugins")
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
UV_RUN_ALLOWED_TARGETS = (
    "pyright",
    "pytest",
    "ruff",
    "lup-devtools",
)


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


def is_trusted_script(word: str, roots: list[str]) -> bool:
    """Recognize an absolute script confined to a native-managed package root."""
    if "$" in word or not word.startswith("/"):
        return False
    normalized = posixpath.normpath(word)
    return any(
        normalized.startswith(posixpath.join(posixpath.normpath(root), ""))
        for root in roots
        if root.startswith("/") and posixpath.normpath(root) != "/"
    )


def is_session_scratch_target(word: str) -> bool:
    """Recognize a path confined to the session scratchpad.

    ``$TMPDIR`` is the harness-provided scratch root and ``/tmp/claude-*`` its
    host-side spelling, so writes there are scratch by definition. A suffix
    that expands further or climbs out of the root stays unrecognized.
    """
    for prefix in ("$TMPDIR/", "${TMPDIR}/"):
        if word.startswith(prefix):
            suffix = word[len(prefix) :]
            normalized = posixpath.normpath(suffix)
            return "$" not in suffix and not normalized.startswith(("..", "/"))
    return "$" not in word and posixpath.normpath(word).startswith("/tmp/claude-")


def is_generated_plugin_target(word: str) -> bool:
    """Recognize a path confined to a native plugin tree the harness renders.

    Every file there is compiled from typed source, so removing one costs a
    regeneration rather than any information. The roots stop at ``plugins``
    because their parents also hold settings, trust state, and hand-written
    skills and commands that no generator can restore.
    """
    normalized = posixpath.normpath(word)
    if normalized.startswith("/"):
        return False
    return any(
        normalized == root or normalized.startswith(root + "/")
        for root in GENERATED_PLUGIN_ROOTS
    )


def rm_confined_to_recoverable_roots(words: list[str]) -> KernelDecision | None:
    """Recognize ``rm`` whose every target is scratch or regenerable.

    Scratch roots exist for disposable files, so clearing them is as safe as
    writing them; a generated plugin tree costs a regeneration rather than any
    information. A long flag, an opaque word, or a single target outside those
    roots falls through to the rm row's ask, so a mixed removal still asks.
    """
    targets: list[str] = []
    for word in words[1:]:
        if word == "--":
            continue
        if word.startswith("-"):
            short = not word.startswith("--") and len(word) > 1
            if short and all(letter in "rfv" for letter in word[1:]):
                continue
            return None
        targets.append(word)
    if not targets:
        return None
    if all(
        is_repository_tmp_script(word)
        or is_session_scratch_target(word)
        or is_generated_plugin_target(word)
        for word in targets
    ):
        return KernelDecision("allow", "removal confined to recoverable roots")
    return None


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
    """A word whose runtime expansion could inject a guarded flag.

    A substitution sentinel anywhere in the word marks it: the substitution's
    output word-splits at expansion, so even a mid-word result can become new
    words.
    """
    if word.startswith("$") or SUBSTITUTION_SENTINEL in word:
        return True
    return "}" in word and ("{-" in word or ",-" in word)


HELP_UNSAFE = set("/=$*?~<>|&;`\\'\" \t\n")


def is_help_probe(arguments: list[str]) -> bool:
    """Recognize an invocation that only prints usage.

    ``--help`` is inert wherever it sits among plain subcommand words, so
    an unclassified command is still readable through it. Bare ``-h`` counts
    only when it stands alone, because several commands spend it on a value
    (``mysql -h host``) rather than on help.
    """
    if not arguments:
        return False
    if any(character in HELP_UNSAFE for word in arguments for character in word):
        return False
    if arguments == ["-h"]:
        return True
    return "--help" in arguments


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
