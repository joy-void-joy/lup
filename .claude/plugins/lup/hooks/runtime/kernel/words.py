# lup: ignore[empty-collection, set-shape, string-split]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Word-level shell helpers: expansion safety, flags, and payloads."""

import posixpath
from fnmatch import fnmatchcase
from typing import TypedDict

from .archives import archive_targets, archive_write
from .decision import CheckpointRequirement, KernelDecision, SUBSTITUTION_SENTINEL
from .edit import path_rule_matches
from .roles import (
    GENERATED_PLUGIN_REFUSAL,
    is_generated_plugin_target,
    path_role,
)
from .rows import PathRoleRow, PathRuleRow


class EffectiveCommand(TypedDict):
    """The words the shell finally executes, and whether a binding was dangerous."""

    words: list[str]
    dangerous: bool


class VerbOperands(TypedDict):
    """A path verb's operands, and whether every flag among them was inert."""

    operands: list[str]
    inert: bool


# lup: ignore[library-default] — real wrappers that exec the argument after them
PASS_THROUGH_WORDS = (
    "env",
    "command",
    "exec",
    "time",
    "nohup",
    "setsid",
    "stdbuf",
)
# lup: ignore[library-default] — variables the shell and language runtimes read to redirect execution
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
    "MANPAGER",
    "EDITOR",
    "VISUAL",
    "NODE_OPTIONS",
    "PERL5LIB",
    "PERL5OPT",
    "RUBYLIB",
    "RUBYOPT",
)
# lup: ignore[library-default] — variable prefixes the OS, those runtimes, and these tools read to redirect execution or retarget a command
DANGEROUS_ENV_PREFIXES = ("LD_", "DYLD_", "PYTHON", "GIT_", "GH_", "BASH_FUNC_")
# lup: ignore[library-default] — real interpreter executables; omitting one is a hole, not a preference
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


def effective_command(segment: list[str]) -> EffectiveCommand:
    """Skip assignments and transparent wrappers, noting dangerous assignments.

    Wrappers that take values (``timeout 5``, ``nice -n 10``) consume them, so
    the returned words start at the command the shell finally executes. A bare
    ``env`` with nothing to wrap is itself the command, and ``command -v`` asks
    where a program is rather than running one, so it is the command too.
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
            return EffectiveCommand(words=segment[position:], dangerous=dangerous)
        if executable == "command" and segment[position + 1 : position + 2] in (
            ["-v"],
            ["-V"],
        ):
            return EffectiveCommand(words=segment[position:], dangerous=dangerous)
        if executable in PASS_THROUGH_WORDS:
            position += 1
            continue
        if executable == "timeout":
            position = timeout_payload(segment, position + 1)
            continue
        if executable == "nice":
            position = nice_payload(segment, position + 1)
            continue
        return EffectiveCommand(words=segment[position:], dangerous=dangerous)
    return EffectiveCommand(words=[], dangerous=dangerous)


def command_words(words: list[str]) -> list[str]:
    """Skip assignments and transparent wrappers to the effective command."""
    return effective_command(words)["words"]


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


# Every verb that acts on paths, paired with the short flags whose presence
# does not change what the verb does to them. A long flag or an unrecognized
# cluster falls through to the verb's own effect. Membership is about taking
# paths, not about asking: `mkdir` and `touch` are allowed and still listed,
# because the refusals that read this map — a write inside a generated plugin
# tree, above all — are owed by every verb that names a path.
# lup: ignore[library-default] — each verb's own POSIX flags, fixed by what the utility does rather than by who is asking
SCRATCH_VERB_FLAGS = {
    "rm": "rfv",
    "rmdir": "pv",
    "mv": "fnv",
    "cp": "aprRvL",
    "mkdir": "pv",
    "touch": "acm",
}


class OperandGrammar(TypedDict):
    """How a command that carries a program tells its paths from its program.

    The verbs above take paths and nothing else, so their operands are
    whatever is not a flag. A command handed a program does not work that way:
    `sed -n '/^def x/,/^def y/p' file.py` names one path and one script, and
    reading both as paths is reading a script as a path.

    That mattered because the reading feeds three questions and only two of
    them stat anything. Whether a target is a directory and whether it is an
    empty one both skip a path that is not on disk, so a script fell out
    harmlessly; whether a target sits under a writable root resolves the
    string and asks -- and a sed address script *begins with a slash*, so it
    resolved to an absolute path no root contains and was reported as a write
    outside the lease. `sed -n '/^def x/,/^def y/p' file.py` asked for
    approval, naming the script as the file it was about to write.
    """

    script_flags: str
    """Short options that supply the program, so no operand carries it."""
    script_options: list[str]
    """Long spellings of the same, matched before any ``=`` value."""
    value_flags: str
    """Short options that consume the following word, program or otherwise."""


# lup: ignore[constant-declaration] — each command's own documented grammar, fixed by what the utility parses rather than by anybody's judgement
PROGRAM_CARRYING_COMMANDS = {
    "sed": OperandGrammar(
        script_flags="ef", script_options=["expression", "file"], value_flags="efl"
    )
}
"""Commands whose first operand is a program unless an option supplied one.

One entry, and a table rather than a branch because the fact is about `sed`
rather than about this function: what is declared is where the paths start,
and a second command with the same shape is a row instead of a second `if`
that has to be found and read to know it is the same shape.
"""


def leaves_the_checkout(path_text: str) -> bool:
    """Whether this spelling reaches somewhere the checkout does not cover.

    Read off the spelling rather than resolved against a root, because the
    readings that need it run before any root is in hand. That makes it
    conservative in the one direction that is safe: an absolute path *inside*
    the checkout reads as outside it and earns the question anyway, while
    nothing outside can read as inside.

    Both escapes are spellings rather than places. An absolute path names
    somewhere without reference to where this session is, and a leading `..`
    climbs out of wherever it is -- and a `..` further along cannot climb past
    what preceded it without an absolute segment, which the first test already
    holds.
    """
    if path_text.startswith("/"):
        return True
    return path_text == ".." or path_text.startswith("../")


def write_scope(path_text: str, path_roles: list[PathRoleRow]) -> str:
    """Which tree a write's target is in, as :class:`WritesPath` names them.

    One reading for every spelling of a write, which is the whole point: a
    redirection and a write flag land the same bytes at the same path, so
    what separates the answers has to be the path rather than the syntax that
    named it.

    ``.git`` is ``protected`` rather than ``production`` because it is not
    reviewable source and not the working tree either -- it is the repository
    the working tree is checked out *of*. A write there is what `git` itself
    does through verbs this table judges one by one; reaching it with a
    redirection goes around all of them, which is the shape an approval
    question exists for. Nothing declares this, because a checkout that did
    not hold it would not be a checkout.

    A declared role is read before either spelling, because a role is somebody
    saying where a path belongs and a spelling is only this reading guessing.
    The session scratchpad is the case that settles it: it is absolute, so the
    escape test would call it outside, and it is declared scratch, which is
    what it is.
    """
    if path_role(path_text, path_roles) == "scratch":
        return "scratch"
    if path_text == ".git" or path_text.startswith(".git/"):
        return "protected"
    if leaves_the_checkout(path_text):
        return "outside"
    return "production"


def write_checkpoint(scope: str) -> CheckpointRequirement:
    """Which capture would put back what a write to this scope replaced.

    Read off the scope rather than off the row, because it is the same fact
    the scope already states and a row carries one value for every path it
    might touch. A snapshot of this checkout holds the checkout: a write
    inside it is a targeted loss that capture answers for, and a write to
    ``/etc/hosts`` or into ``.git`` is not held by it at all.

    Getting this from the row is what let a redirection outside the tree be
    settled by the capture row -- "the affected paths are captured and
    restorable", said of a path no capture had ever seen.
    """
    return "targeted" if scope in ("scratch", "production") else "unrecoverable"


def written_beyond_the_checkout(
    targets: list[str], path_roles: list[PathRoleRow]
) -> bool:
    """Whether any of these paths is somewhere this checkout cannot answer for.

    The grants below reason about a path from what the checkout knows of it: a
    role declared it disposable, Git could put it back, nothing stands there
    yet. Each of those is a fact about a path inside the checkout, and none of
    them says anything about ``/etc/newfile`` -- where no role reaches, the
    object store holds nothing, and "nothing stands there" is a fact about
    somebody else's filesystem.

    Read through :func:`write_scope`, which is what a redirection and a delete
    already read, so one answer covers every spelling of a write. Measured
    before this: `ls > /etc/newfile` asked, while `cp README.md /etc/newfile`,
    `touch /etc/newfile`, `mkdir /etc/newdir` and `tar -cf /etc/backup.tar
    src` were allowed -- one place, five spellings, two answers.

    ``True`` gives the line back to the row that judges it rather than
    refusing it, which is where a contained session's placement is read: the
    write row allows a write outside the checkout when the call cannot leave
    the boundary, and that is a reading no grant here is holding.
    """
    return any(
        write_checkpoint(write_scope(target, path_roles)) == "unrecoverable"
        for target in targets
    )


def flag_write_targets(words: list[str], write_flags: list[str]) -> list[str]:
    """The paths this command's declared write flags name, in the order given.

    Three spellings reach the same place and all three are read, because a
    guard that recognized two of them would be the flag guard's own history
    repeating: ``--output=path`` carries the value attached, ``--output path``
    and ``-o path`` carry it in the following word.

    Matched exactly rather than through :func:`flag_matches`, which the guard
    beside this one uses. That reader accepts a short flag anywhere inside a
    cluster, which is right for asking whether a guarded flag is present and
    wrong for deciding which word is the path: ``-no`` would carry ``-o``, and
    the following word is then somebody else's operand. A flag whose value is
    missing, clustered, or otherwise unresolvable yields nothing rather than a
    guess -- what reads this uses it to relax a row, so an unnamed target
    leaves the row's own verdict standing and a misnamed one would not.
    """
    targets: list[str] = []
    following = False
    for word in words[1:]:
        if following:
            following = False
            if not word.startswith("-"):
                targets.append(word)
            continue
        name, sign, value = word.partition("=")
        if sign and name in write_flags:
            if value:
                targets.append(value)
            continue
        following = word in write_flags
    return targets


def program_carrying_operands(words: list[str], grammar: OperandGrammar) -> list[str]:
    """The words this command names paths with, by its declared grammar.

    Over-naming is safe for the questions that stat what they are handed and
    unsafe for the one that does not, so this under-names instead: an option
    whose value is unknown takes the following word with it, and the leading
    operand is a path only once something else has supplied the program.
    """
    operands: list[str] = []
    supplied = not grammar["script_flags"]
    skipping = False
    for word in words[1:]:
        if skipping:
            skipping = False
            continue
        if word.startswith("--") and len(word) > 2:
            if word[2:].split("=", 1)[0] in grammar["script_options"]:
                supplied = True
            continue
        if word.startswith("-") and len(word) > 1:
            letters = word[1:]
            if any(letter in grammar["script_flags"] for letter in letters):
                supplied = True
            skipping = letters[-1] in grammar["value_flags"]
            continue
        if not supplied:
            supplied = True
            continue
        operands.append(word)
    return operands


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


def path_verb_operands(words: list[str]) -> VerbOperands:
    """A path verb's operands, and whether every flag among them was inert.

    An inert flag does not change what the verb does to its operands, so the
    operand list means what it reads. An unrecognized one can move the
    destination, add one, or change which paths are touched at all — which is
    why the two directions diverge on it: a caller granting something must
    decline outright, and a caller refusing something must widen to every
    operand rather than trust their positions.
    """
    allowed = SCRATCH_VERB_FLAGS[posixpath.basename(words[0])]
    operands: list[str] = []
    inert = True
    for word in words[1:]:
        if word == "--":
            continue
        if word.startswith("-") and len(word) > 1:
            if word.startswith("--") or not all(
                letter in allowed for letter in word[1:]
            ):
                inert = False
            continue
        operands.append(word)
    return VerbOperands(operands=operands, inert=inert)


class RestoreOperands(TypedDict):
    """A ``git restore``'s source ref, if it named one, and the paths it rewrites.

    ``source`` is ``None`` for the index-sourced form, which is the one whose
    safety depends on whether those paths carry uncommitted work.
    """

    source: str | None
    paths: list[str]


def git_restore_operands(words: list[str]) -> RestoreOperands | None:
    """Split ``git restore`` into the ref it reads from and the paths it writes.

    ``None`` where the line is not a restore, carries a flag beyond the source
    and target selectors, or holds a word that expands at run time — each of
    which leaves the restore row's ask to answer for it, because a flag this
    does not know could move which paths are touched.
    """
    if len(words) < 3 or posixpath.basename(words[0]) != "git" or words[1] != "restore":
        return None
    source: str | None = None
    paths: list[str] = []
    position = 2
    while position < len(words):
        word = words[position]
        if word == "--source" and position + 1 < len(words):
            source = words[position + 1]
            position += 2
            continue
        if word.startswith("--source="):
            source = word[len("--source=") :]
            position += 1
            continue
        if word in ("--staged", "--worktree", "-S", "-W", "--"):
            position += 1
            continue
        if word.startswith("-"):
            return None
        paths.append(word)
        position += 1
    if not paths or (source is not None and source.startswith("-")):
        return None
    if opaque_argument(source or "") or any(opaque_argument(word) for word in paths):
        return None
    return RestoreOperands(source=source, paths=paths)


def git_apply_patches(words: list[str]) -> list[str]:
    """The patch files ``git apply`` is handed, which name the paths it writes.

    A patch is the one write in this table whose targets are neither operands
    nor flag values: they are inside a file, in a format with a reader of its
    own. So this names the file, and what reads it asks Git what the patch
    would touch -- delegating to the format's parser rather than growing a
    second one here, which is the same arrangement the archive readers keep.

    Empty where the patch arrives on standard input, which is a spelling this
    cannot see and must not guess at: ``git apply < f`` names no operand, and
    reporting the redirection's source as a write would be reporting the wrong
    file in the wrong direction. The row's own verdict answers for that.

    Over-naming is safe here in a way it is not elsewhere, because nothing
    consults these words as paths. They are handed to a patch reader that
    rejects whatever is not a patch, so a flag value swept up by mistake
    yields no targets rather than a target nobody writes.
    """
    if len(words) < 3 or posixpath.basename(words[0]) != "git" or words[1] != "apply":
        return []
    return [
        word
        for word in words[2:]
        if not word.startswith("-") and word != "--" and not opaque_argument(word)
    ]


def written_operands(executable: str, operands: list[str]) -> list[str]:
    """The operands a path verb modifies, as opposed to the ones it reads.

    Copying reads every source and writes only the destination, so a path
    named as a source is an ordinary read however protected it is. Every other
    verb here removes or creates each path it is given.
    """
    if executable == "cp" and len(operands) > 1:
        return operands[-1:]
    return operands


def written_targets(words: list[str]) -> list[str] | None:
    """Every path this line would write over, or ``None`` where none can be named.

    Two grammars answer one question. A path verb takes paths and nothing
    else, so its operands are its targets; an archive verb states separately
    where it authors, what it consumes and which directory it unpacks into.
    What a caller wants of either is the same list, because what it asks of
    that list is the same question -- where the loss lands.

    ``None`` for an unmodelled line and for a verb whose flags could move
    which paths are touched, which leaves every caller with the answer it had
    before it asked.
    """
    if not words:
        return None
    archived = archive_write(words)
    if archived is not None:
        return archive_targets(archived)
    executable = posixpath.basename(words[0])
    if executable not in SCRATCH_VERB_FLAGS:
        return None
    verb = path_verb_operands(words)
    if not verb["inert"]:
        return None
    return written_operands(executable, verb["operands"])


def created_destination(
    executable: str,
    operands: list[str],
    existing_targets: list[str] | None,
    path_roles: list[PathRoleRow],
) -> str | None:
    """The operand a copy or move would bring into being, if it would.

    Both verbs write their last operand and read the rest, so a destination
    nothing occupies yet is a creation, and creating a file destroys nothing
    — the same reason a redirection to a fresh path is written freely. That
    is what leaves ``mv`` and ``rm`` agreeing about a tracked, clean file
    instead of the move asking where the delete did not.

    Destroying nothing is only half of it, because a create also *places*
    content, and the edit gate reads every line that enters production.
    Content already in production has passed it; content in a scratch root
    never did, and arriving by rename is how it would skip it. So a source
    there withholds the grant even though the destination is empty.

    ``existing_targets`` of ``None`` means no caller established anything, so
    every destination is treated as occupied. An expansion is never resolved:
    it names a different path at run time than the one that was stat'd.
    """
    if executable not in ("cp", "mv") or len(operands) < 2:
        return None
    destination = operands[-1]
    if existing_targets is None or destination in existing_targets:
        return None
    if opaque_argument(destination) or destination.startswith("~"):
        return None
    if path_role(destination, path_roles) != "scratch" and any(
        path_role(source, path_roles) == "scratch" for source in operands[:-1]
    ):
        return None
    return destination


def refuses_generated_plugin_target(word: str) -> KernelDecision | None:
    """Refuse one path that would write inside a generated plugin tree.

    Every writing form routes its targets here — a path verb's operands, a
    redirection's target — so the refusal and the reason it carries are
    written once and cannot drift between the paths that reach them.
    """
    if not is_generated_plugin_target(word):
        return None
    return KernelDecision("deny", GENERATED_PLUGIN_REFUSAL)


def refuses_generated_plugin_write(words: list[str]) -> KernelDecision | None:
    """Refuse a verb that would write inside a generated plugin tree.

    Every verb naming a path owes this, not only the ones the flag map
    models: an archive unpacked over a generated tree replaces it exactly as
    a copy would, and the regeneration that repairs it is the same one.
    """
    executable = posixpath.basename(words[0])
    archived = archive_write(words)
    if archived is not None:
        for word in archive_targets(archived):
            refused = refuses_generated_plugin_target(word)
            if refused is not None:
                return refused
        return None
    if executable not in SCRATCH_VERB_FLAGS:
        return None
    verb = path_verb_operands(words)
    operands = verb["operands"]
    inert = verb["inert"]
    targets = written_operands(executable, operands) if inert else operands
    for word in targets:
        refused = refuses_generated_plugin_target(word)
        if refused is not None:
            return refused
    return None


def asks_before_removing_a_directory(
    words: list[str],
    path_roles: list[PathRoleRow],
    directory_targets: list[str] | None = None,
) -> KernelDecision | None:
    """Ask before a verb destroys a directory, naming the way through.

    Git restores a file it tracks, so a delete confined to files is bounded by
    the files named. A directory is not: its size is whatever it happens to
    hold, nothing in the command says what that is, and untracked work inside
    it is restored by nothing. The ask says which route is open rather than
    leaving a refusal the agent can only guess at. A scratch root keeps its
    own grant, because there the tree is disposable by declaration.
    """
    executable = posixpath.basename(words[0])
    if executable not in ("rm", "mv"):
        return None
    operands = path_verb_operands(words)["operands"]
    named = [
        word
        for word in operands
        if word in (directory_targets or [])
        and path_role(word, path_roles) != "scratch"
    ]
    if not named:
        return None
    return KernelDecision(
        "ask",
        "removing a directory is never granted, because nothing in the command"
        " bounds what it holds — name the files instead, or approve this",
    )


def rewrites_only_recoverable_files(
    targets: list[str],
    path_roles: list[PathRoleRow],
    recoverable_targets: list[str] | None = None,
    recoverable_target_limit: int = 5,
    path_rules: list[PathRuleRow] | None = None,
) -> KernelDecision | None:
    """Grant a rewrite in place whose every named file could be brought back.

    The same question :func:`confined_to_recoverable_roots` asks of a delete,
    asked of a command that overwrites: what would this cost if it were
    wrong. A scratch file costs nothing by declaration; a committed file with
    no uncommitted change costs a checkout and no information. Past the cap
    it is a sweep rather than an edit, and a sweep is worth a question even
    where every file in it could be restored.

    What this does *not* answer is the other half of why an in-place rewrite
    is gated: it walks past the gates an edit is judged by — the anti-pattern
    table, the review-note gate, the size gate. Those are reviewability, and
    no boundary and no undo layer answers them. What recoverability does
    settle is that being wrong is repairable and the whole change stands in
    the diff, so the grant says which half it granted.

    ``None`` wherever the answer is not established — no targets, a word that
    expands at run time, a file the host reported nothing about — and ``None``
    leaves the caller's own refusal standing.
    """
    if not targets:
        return None
    if any(opaque_argument(word) or "$" in word for word in targets):
        return None
    disposable = [word for word in targets if path_role(word, path_roles) == "scratch"]
    restorable = [
        word
        for word in targets
        if word not in disposable and word in (recoverable_targets or [])
    ]
    if len(disposable) + len(restorable) != len(targets):
        return None
    if len(restorable) > recoverable_target_limit:
        return None
    protected = protected_write_target(targets, path_rules or [], True)
    if protected is not None:
        return protected
    return KernelDecision(
        "allow",
        "every file this rewrites is restorable, and the whole change is in the"
        " diff — but the edit gates did not read it, so the anti-pattern, note"
        " and size rules are `dev check`'s to catch",
    )


def protected_write_target(
    targets: list[str], path_rules: list[PathRuleRow], path_exists: bool
) -> KernelDecision | None:
    """Ask before granting a write to a path the declared rules protect.

    Every grant below answers "what would destroying this cost" — nothing,
    for a scratch file; a checkout, for one Git can restore. That is the
    wrong question for a file protected by who owns it rather than by what
    it would cost to rebuild, and answering it anyway is how ``rm sync.json``
    and ``cp x README.md`` passed a gate the Edit tool stops. The rules are
    the edit gate's own, so the two cannot come to disagree about a path.

    ``path_exists`` is the caller's own established fact, because the rule
    kinds that fire only on a path that is not there yet — a new subtree, a
    new devtools module — mean the opposite thing when it is. A grant over a
    scratch or Git-clean operand has settled that it exists; a redirection
    knows from the targets the host stat'd.
    """
    for word in targets:
        matched = next(
            (row for row in path_rules if path_rule_matches(word, path_exists, row)),
            None,
        )
        if matched is not None:
            return KernelDecision("ask", matched["reason"])
    return None


def confined_to_recoverable_roots(
    words: list[str],
    path_roles: list[PathRoleRow],
    recoverable_targets: list[str] | None = None,
    recoverable_target_limit: int = 5,
    path_rules: list[PathRuleRow] | None = None,
    existing_targets: list[str] | None = None,
) -> KernelDecision | None:
    """Recognize a path-taking judged-ask verb whose every target is disposable.

    A scratch role names a tree of disposable files, so destroying one is as
    safe as writing it and creating one there settles nothing. A path the host
    reports as recoverable is committed with no uncommitted change, so
    destroying it costs a checkout rather than any information — the host
    establishes that, because the kernel never reads the filesystem. Only the
    operands the verb writes are judged, so copying any source into a scratch
    root is as disposable as the root it lands in. A long flag, an opaque
    word, or a single written target outside those roots falls through to the
    verb's ask, so a mixed command still asks.

    The two grants are bounded differently because what backs them differs. A
    scratch root is disposable by declaration, so emptying one is one act
    whatever it holds. Restoring committed work is instead a repair somebody
    has to know to perform, so that grant is capped: past the limit a delete
    is a sweep, and a sweep is worth a question even when every file in it
    could be brought back.

    A destination nothing occupies yet is neither: it is brought into being,
    and the cap does not reach it because there is nothing there to restore
    — provided the content arriving there already lives in production, where
    the edit gate has read it.

    All three readings are about a path this checkout answers for, so a target
    beyond it gives the line back to the row rather than taking any of them:
    see :func:`written_beyond_the_checkout`.
    """
    executable = posixpath.basename(words[0])
    if executable not in SCRATCH_VERB_FLAGS:
        return None
    verb = path_verb_operands(words)
    operands = verb["operands"]
    inert = verb["inert"]
    if not inert or not operands:
        return None
    targets = written_operands(executable, operands)
    if written_beyond_the_checkout(targets, path_roles):
        return None
    created = created_destination(executable, operands, existing_targets, path_roles)
    disposable = [word for word in targets if path_role(word, path_roles) == "scratch"]
    restorable = [
        word
        for word in targets
        if word not in disposable and word in (recoverable_targets or [])
    ]
    fresh = [word for word in targets if word == created and word not in disposable]
    if len(disposable) + len(restorable) + len(fresh) != len(targets):
        return None
    if len(restorable) > recoverable_target_limit:
        return None
    protected = protected_write_target(targets, path_rules or [], True)
    if protected is not None:
        return protected
    return KernelDecision("allow", "confined to recoverable roots")


def archive_lands_on_nothing(
    words: list[str],
    path_roles: list[PathRoleRow],
    recoverable_targets: list[str] | None = None,
    path_rules: list[PathRuleRow] | None = None,
    existing_targets: list[str] | None = None,
    empty_directories: list[str] | None = None,
) -> KernelDecision | None:
    """Grant an archive or compression verb that would replace nothing.

    These verbs ask because they place content over whatever stands there.
    Where nothing stands there, the ask is answering a question that has no
    second side: unpacking into a directory that does not exist, or into one
    holding nothing, destroys nothing, and neither does authoring an archive
    at a path nothing occupies.

    A named file is judged exactly as a delete's operand is — disposable by
    role, restorable from Git, or not yet there — because the cost of
    replacing it is the same cost whichever verb does the replacing. That is
    what leaves ``gzip`` and ``rm`` agreeing about a committed, unmodified
    file instead of one asking where the other does not.

    A destination directory cannot be judged that way, because what would
    land in it comes from the archive rather than from the command. So it is
    judged by being empty: nothing there is nothing to replace, whatever the
    archive turns out to hold. Everything the extraction then writes is new,
    and a later edit to any of it passes the edit gate on its own path.

    Both readings are about a path this checkout answers for, so a target
    beyond it gives the line back to the row rather than taking either: see
    :func:`written_beyond_the_checkout`.

    ``None`` wherever the answer is not established — an unmodelled line, an
    expansion that names a different path at run time, a caller that resolved
    no filesystem facts — and ``None`` leaves the verb's own ask standing.
    """
    write = archive_write(words)
    if write is None:
        return None
    authored, consumed = write["authored"], write["consumed"]
    directory = write["directory"]
    named = archive_targets(write)
    # An extraction that named no destination unpacks where it stands, which
    # is the repository itself — certain to be occupied, and the one place an
    # unread archive should never land without a question.
    if not named:
        return None
    if any(opaque_argument(word) or word.startswith("~") for word in named):
        return None
    if written_beyond_the_checkout(named, path_roles):
        return None
    for word in authored:
        if path_role(word, path_roles) == "scratch":
            continue
        if existing_targets is not None and word not in existing_targets:
            continue
        if word in (recoverable_targets or []):
            continue
        return None
    # A consumed path is destroyed rather than created, so being absent is
    # not the licence it is above: it is a fact the host could not establish,
    # and for a destructive verb an unestablished fact is a question.
    for word in consumed:
        if path_role(word, path_roles) == "scratch":
            continue
        if word in (recoverable_targets or []):
            continue
        return None
    if directory is not None and path_role(directory, path_roles) != "scratch":
        if existing_targets is None:
            return None
        if directory in existing_targets and directory not in (empty_directories or []):
            return None
    protected = protected_write_target(named, path_rules or [], True)
    if protected is not None:
        return protected
    return KernelDecision("allow", "archive lands where nothing stands")


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


class CarriedSetting(TypedDict):
    """The setting a guarded global names, and how many words it took to say it.

    Both halves, because the reader needs both: the value decides whether the
    global is one worth interrupting about, and the count is how far the parse
    advances past it. Deriving the second from the first would be re-doing the
    spelling test that produced it.
    """

    value: str
    words: int


def carried_setting(
    word: str, flags: list[str], following: list[str]
) -> CarriedSetting:
    """The ``key=value`` a settings global carries, in the spellings that read.

    Two of them, and deliberately not the third. A long option carries its
    value after an ``=`` (``--config-env=core.pager=VAR``), and any of them
    carries it in the next word (``git -c core.pager=x``). A short option with
    the value pressed against it — ``git -ccore.pager=x`` — reads as neither:
    the ``=`` in that word separates the *setting's* value rather than the
    flag's, so splitting on it yields ``x``, and a guard reading that would
    compare a value against a list of keys.

    Nothing found is an empty value, which a caller reads as "this is not a
    shape I can judge" and answers as it would have answered without this. The
    failure worth avoiding is the other direction, where a spelling read
    wrongly makes a guarded key look unguarded.
    """
    for flag in flags:
        if flag.startswith("--") and word.startswith(flag + "="):
            return CarriedSetting(value=word[len(flag) + 1 :], words=1)
        if word == flag:
            return CarriedSetting(
                value=following[0] if following else "", words=2 if following else 1
            )
    return CarriedSetting(value="", words=1)


def opaque_argument(word: str) -> bool:
    """A word whose runtime expansion could inject a guarded flag.

    A substitution sentinel anywhere in the word marks it: the substitution's
    output word-splits at expansion, so even a mid-word result can become new
    words.
    """
    if word.startswith("$") or SUBSTITUTION_SENTINEL in word:
        return True
    return "}" in word and ("{-" in word or ",-" in word)


def key_matches(word: str, patterns: list[str]) -> bool:
    """Match a setting name against a rule's guarded-key globs, case-blind.

    Lowercased on both sides because git resolves a configuration key's
    section and name without regard to case: `core.hooksPath`,
    `CORE.HOOKSPATH` and `Core.hooksPath` are one key, and a guard comparing
    literally would catch the spelling in the pattern and no other. A
    subsection is the one case-sensitive part, and the patterns that reach
    into one match it with `*` rather than by naming it, so nothing is lost
    by folding it too.

    Globbing rather than prefix-matching because the shapes worth guarding
    sit around a subsection the caller chooses -- `merge.<name>.driver` names
    a program, and the name is theirs. `fnmatchcase` lets `*` cross a `.`,
    which is right here: a subsection may contain dots, so `merge.*.driver`
    should still answer for `merge.a.b.driver`.

    A `key=value` word answers to the key's own pattern, the way
    ``flag_matches`` reads `--flag=value`. Some settings arrive joined --
    `git -c core.pager=x` is the shape -- and a guard reading only the whole
    word would compare `core.pager=x` against `core.pager`, find no match,
    and wave through the one spelling that carries its value with it.
    """
    folded = word.lower()
    return any(
        fnmatchcase(folded, pattern) or fnmatchcase(folded, f"{pattern}=*")
        for pattern in patterns
    )


HELP_UNSAFE = set("/=$*?~<>|&;`\\'\" \t\n")


def is_help_probe(arguments: list[str], unsafe: set[str] = HELP_UNSAFE) -> bool:
    """Recognize an invocation that only prints usage.

    ``--help`` is inert wherever it sits among plain subcommand words, so
    an unclassified command is still readable through it. Bare ``-h`` counts
    only when it stands alone, because several commands spend it on a value
    (``mysql -h host``) rather than on help.
    """
    if not arguments:
        return False
    if any(character in unsafe for word in arguments for character in word):
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


def refspec_effects(word: str) -> list[str]:
    """What one ``git push`` operand does to the ref it names.

    A refspec spells the same two effects the push flags spell. `--delete`
    removes a remote ref and `:<dst>` removes the same ref by giving it no
    source; `--force` replaces one non-fast-forward and `+<src>:<dst>`
    replaces the same ref by prefixing it. A guard written as a list of flag
    spellings therefore holds only half of each effect, which is what let
    `git push origin :refs/heads/main` past a table that asks about
    `git push --delete origin main`.

    Read structurally rather than matched against a second list of spellings,
    because a list of spellings is what missed these. The grammar is small
    and total: `^` opens a negative refspec, which excludes rather than
    writes; a leading `+` forces; and an empty source — everything before the
    first colon — deletes, which `startswith(":")` is the whole of after the
    plus is taken off.

    Every operand is read, the repository among them, because reading only
    the ones past it would need to know where it stopped, and a repository
    that looked like a refspec would cost a question rather than miss one.
    An scp-style remote (`git@host:repo.git`) names a non-empty source and so
    reads as neither effect.
    """
    if word.startswith("^"):
        return []
    forced = word.startswith("+")
    source = word[1:] if forced else word
    effects = ["force"] if forced else []
    return [*effects, "delete"] if source.startswith(":") else effects
