"""A shell vocabulary an adopter starts from, offered as groups to compose.

:mod:`lup.policy.shell_rules` declares the *shape* a vocabulary takes and
says the words themselves are a judgement about one project's toolchain, so
they arrive from outside. That is true, and it left the library shipping
nothing — which is not the neutral position it reads as. An empty table
matches no command and every command is then unlisted, which is a question
put to whoever is there and a refusal where nobody is: a fresh adopter's
agent prompts for ``ls`` in front of a human and cannot run it in a worker,
until several hundred lines of vocabulary exist. Shipping nothing chose a
verdict for them just as surely as shipping something would have, and chose
the least useful one.

So each group below is a function returning rules, and every word it declares
is a parameter default rather than a table. An adopter calls the group to
take the judgement as offered, passes their own words to replace it, or
splices extra rules around it::

    SHELL_RULES = [
        *read_only_rules(),
        *judged_ask_rules(),
        *guarded_tool_rules(),
        git_rule(guard_force_push=False, redirect_checkout=True),
        gh_rule(),
        docker_rule(),
        my_own_cli_rule(),
    ]

The judgement running through all of it: generous for reading and for local
work a second attempt undoes, conservative for anything that loses something.
Networked is deliberately not the line — publishing is how work becomes
reviewable and happens many times a session, so ``git push`` and the pull
request verbs that open and describe one are ordinary. What stays guarded is
the direction that removes something no second attempt restores.

Where a group's default encodes a judgement a reasonable project would make
differently, it takes a parameter instead of a fork: whether a force push is
guarded, whether ``checkout`` is redirected toward ``switch``/``restore``,
whether opening a pull request is authoring or publishing.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from lup.policy.kernel.decision import CheckpointRequirement, SandboxPlacement
from lup.policy.kernel.semantics import EffectClass, ReviewerRequirement
from lup.policy.shell_rules import (
    RunnerTargetRule,
    ShellCommandRule,
    ShellOperationRule,
    ShellSubcommandRule,
)


class JudgedCommand(BaseModel, frozen=True):
    """One command that stops for a human, and the reason it gives them."""

    name: str
    reason: str
    checkpoint: CheckpointRequirement = "unrecoverable"
    """What capture would put back what this command destroys, if any would.

    The question this row asks exists because a loss is permanent, so naming
    the capture that makes it impermanent is naming when the question stops
    being worth a person's attention. Silence keeps the question."""
    read_verbs: list[str] = []
    """This command's own spellings of its query action, which de-escalate it.

    Without somewhere to say "except this verb", listing an archive is as
    much an approval as extracting one."""
    write_markers: list[str] = []
    """Argument prefixes whose absence makes this command read-only.

    The same exception stated negatively, for a command that has no query
    verb because its query form is the plain one: `dd` writes given an `of=`
    and reads without it."""
    bare_reads: bool = False
    """Whether this command reads when handed nothing at all.

    Where `write_markers` still needs a word to find no marker in, this needs
    every word to be absent: `mount` alone prints the mount table, and each
    form that acts names a device or a mountpoint."""


def read_only_rules(
    commands: Sequence[str] = (
        "ls",
        "cat",
        "echo",
        "printf",
        "test",
        "file",
        "wc",
        "head",
        "tail",
        "nl",
        "tac",
        "rev",
        "fold",
        "cut",
        "tr",
        "expr",
        "numfmt",
        "comm",
        "join",
        "paste",
        "column",
        "col",
        "uniq",
        "grep",
        "egrep",
        "fgrep",
        "diff",
        "cmp",
        "jq",
        "stat",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "date",
        "seq",
        "du",
        "df",
        "cksum",
        "md5sum",
        "sha256sum",
        "which",
        "man",
        "true",
        "false",
        "set",
        "continue",
        "break",
        "shift",
        "return",
        "local",
        "exit",
        "sleep",
        "pwd",
        "id",
        "whoami",
        "hostname",
        "uname",
        "printenv",
        "env",
        "ps",
        "pgrep",
        "pidof",
        "lsof",
        "free",
        "uptime",
        "nproc",
        "xxd",
        "od",
        "strings",
        "getent",
        "zcat",
        "[",
    ),
) -> list[ShellCommandRule]:
    """Commands that read and report, and change nothing by running.

    The process and socket listings sit here for the same reason the file
    ones do: establishing that a service came up is a read, and a session
    that just started one is asking about its own process.

    The control-flow builtins report nothing and are here on the second half
    of that test: they change nothing by running, and nothing they do can
    reach a later command. `eval`, `exec`, `export`, `declare` and `unset`
    are deliberately absent — each decides what some later command sees or
    does, which is the thing this list promises a reader it does not touch.
    """
    return [ShellCommandRule(name=name, default_effect="allow") for name in commands]


def judged_ask_rules(
    commands: Sequence[JudgedCommand] = (
        JudgedCommand(
            name="rm",
            reason="deleting files requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="rmdir",
            reason="deleting directories requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="mv",
            reason="moving files requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="cp",
            reason="copying over files requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(name="chmod", reason="changing permissions requires approval"),
        JudgedCommand(name="chown", reason="changing ownership requires approval"),
        JudgedCommand(
            name="ln",
            reason="creating links requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="tee",
            reason="writing files requires approval — prefer the Write tool",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="dd",
            # `dd` writes when handed an `of=` and reads to stdout without
            # one, so its read-only form is the invocation with nothing extra
            # in it. No verb list can name that, which is why every
            # `dd if=x` stopped for approval as a write.
            write_markers=["of="],
            reason="raw device or file writes require approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="mount",
            # Alone it prints the mount table, which is how a session finds out
            # what its own boundary is made of. Every form that acts names a
            # device or a mountpoint, so there is no marker to test for and no
            # verb to list -- what separates the two is that one carries words
            # and the other carries none.
            bare_reads=True,
            reason="mounting a filesystem requires approval",
        ),
        JudgedCommand(
            name="truncate",
            reason="truncating files requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="kill",
            reason="terminating processes requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="pkill",
            reason="terminating processes requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="command",
            # Reached only in the query shape: every other spelling runs the
            # program after it, which `effective_command` unwraps to instead.
            read_verbs=["-v", "-V"],
            reason="'command' runs a program through a modified lookup — name it directly",
        ),
        JudgedCommand(
            name="tar",
            # Named whole rather than scanned for a `t`, which a bundled
            # `-xzf` also contains: these are tar's own list-mode spellings.
            read_verbs=["-t", "--list", "-tf", "-tvf", "-tzf", "-tzvf", "-tjf", "-tJf"],
            reason="archive operations write files — requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="unzip",
            read_verbs=["-l", "-t", "-v", "-z"],
            reason="archive extraction writes files — requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="zip",
            read_verbs=["-sf", "--show-files"],
            reason="archive creation writes files — requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="gzip",
            read_verbs=["-l", "--list", "-t", "--test"],
            reason="compression rewrites files — requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="gunzip",
            read_verbs=["-l", "--list", "-t", "--test"],
            reason="decompression rewrites files — requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(name="sudo", reason="privilege escalation requires approval"),
        JudgedCommand(name="doas", reason="privilege escalation requires approval"),
        JudgedCommand(name="ssh", reason="remote access requires approval"),
        JudgedCommand(name="scp", reason="remote copies require approval"),
        JudgedCommand(name="rsync", reason="remote sync requires approval"),
        JudgedCommand(
            name="wget",
            reason="downloading files requires approval — prefer curl or WebFetch",
        ),
        JudgedCommand(
            name="make",
            read_verbs=["-n", "--dry-run", "--just-print", "-q", "--question"],
            reason="make executes arbitrary recipes — requires approval",
        ),
        JudgedCommand(
            name="npm",
            read_verbs=["ls", "list", "view", "outdated", "why", "explain"],
            reason="package tools fetch and execute code — requires approval",
        ),
        JudgedCommand(
            name="pnpm",
            reason="package tools fetch and execute code — requires approval",
        ),
        JudgedCommand(
            name="yarn",
            reason="package tools fetch and execute code — requires approval",
        ),
        JudgedCommand(
            name="apt",
            reason="system package changes require approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="apt-get",
            reason="system package changes require approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="pacman",
            reason="system package changes require approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="brew",
            reason="system package changes require approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="systemctl",
            reason="service management requires approval",
            checkpoint="boundary_wide",
        ),
        JudgedCommand(
            name="crontab",
            reason="schedule changes require approval",
            checkpoint="boundary_wide",
        ),
    ),
) -> list[ShellCommandRule]:
    """Commands that ask on every production path, with the reason each carries.

    Inside a root declared as scratch these allow instead, which the kernel
    settles by resolving each target's role — so the ask lands on production
    work rather than on a disposable tree.
    """
    return [
        ShellCommandRule(
            name=command.name,
            default_effect="ask",
            read_verbs=command.read_verbs,
            write_markers=command.write_markers,
            bare_reads=command.bare_reads,
            checkpoint=command.checkpoint,
            reason=command.reason,
        )
        for command in commands
    ]


def redirected_rules(
    commands: Sequence[JudgedCommand] = (
        JudgedCommand(name="pip", reason="use uv add / uv remove instead of pip"),
        JudgedCommand(name="pip3", reason="use uv add / uv remove instead of pip"),
    ),
) -> list[ShellCommandRule]:
    """Commands denied toward the spelling a project actually uses.

    A redirect is house style rather than a safety verdict, which is why the
    pairs are a parameter: a project on a different package manager replaces
    them instead of inheriting an argument about uv.
    """
    return [
        ShellCommandRule(
            name=command.name, default_effect="deny", reason=command.reason
        )
        for command in commands
    ]


def reaching_builtin_rules(
    commands: Sequence[JudgedCommand] = (
        JudgedCommand(
            name="eval",
            reason="eval runs text as code, which no gate reading the command"
            " can see into — write the command out",
        ),
        JudgedCommand(
            name="source",
            reason="sourcing a script runs its code in this shell, where no"
            " gate read it — run the commands it holds",
        ),
        JudgedCommand(
            name=".",
            reason="sourcing a script runs its code in this shell, where no"
            " gate read it — run the commands it holds",
        ),
        JudgedCommand(
            name="export",
            reason="an exported variable decides what later commands see —"
            " set it on the command that needs it",
        ),
        JudgedCommand(
            name="declare",
            reason="a declared variable decides what later commands see —"
            " set it on the command that needs it",
        ),
        JudgedCommand(
            name="unset",
            reason="unsetting a variable decides what later commands see —"
            " set it on the command that needs it",
        ),
    ),
) -> list[ShellCommandRule]:
    """Builtins that run unread code, or decide what a *later* command sees.

    :func:`read_only_rules` carries the control-flow builtins because they
    change nothing and nothing they do reaches a later command. These fail
    that second half, and were held out of that list to say so — but an
    omission is not a judgement anything can read. Left unlisted they refused
    with "command 'eval' is not classified", which is the one thing that was
    not true of them: they were classified, by being left out, and the agent
    was told the opposite.

    Declared so the refusal carries its own reason, and so the row answering
    for work nobody classified is not also the row enforcing a decision
    somebody made. The same verdict as before, arrived at on the record.

    Declaring them also settles what a sandbox does about them, and settles
    it the way the inline-code refusal beside them already answered: a
    judged deny survives a boundary, because the objection to ``eval`` is
    that nothing read what it runs, and confining unread code does not read
    it. Left unlisted they deferred to the boundary instead — so ``python -c
    'x'`` and ``eval echo x``, which are one objection, were enforced two
    ways depending on which of them somebody had written down.

    ``exec`` is absent though it was held out of that list too: the lexer
    already resolves it to the command it wraps, so ``exec rm -rf src`` is
    judged as ``rm -rf src`` and a row here would never be reached. Which is
    also the right answer — what ``exec`` runs is the whole of what it does
    to anything outside the shell it replaces.
    """
    return [
        ShellCommandRule(
            name=command.name, default_effect="deny", reason=command.reason
        )
        for command in commands
    ]


def guarded_tool_rules() -> list[ShellCommandRule]:
    """Readers whose own flags can turn them into writers, and the guards.

    Each entry is a fact about the utility rather than a preference: ``sort
    -o`` writes a file, ``ss -K`` closes sockets, ``nc`` moves bytes unless
    ``-z`` pins it to a scan. What varies between projects is which of these
    are installed, not what they do, so nothing here takes a parameter.
    """
    return [
        ShellCommandRule(
            # Not read-only, and not judged either. The verbs in the ask list
            # are destructive or content-bearing: they overwrite something, or
            # author a file that later holds code. An empty directory does
            # neither — `-p` is a no-op on one that exists, and it holds
            # nothing to run. Everything landing inside it still passes the
            # write and edit gates on its own path.
            name="mkdir",
            default_effect="allow",
        ),
        ShellCommandRule(
            # The same test `mkdir` passes, for the same reason. `touch` has
            # no form that writes content: on a path that exists it moves
            # timestamps and nothing else, and on one that does not it
            # authors an empty file, which holds nothing to run. Whatever
            # lands in that file afterwards passes the write and edit gates
            # on its own path, so asking here buys a prompt and no decision.
            name="touch",
            default_effect="allow",
        ),
        ShellCommandRule(
            # -l/-L print fingerprints and public keys — the read-only
            # diagnostic for push-auth failures; every other form mutates the
            # agent.
            name="ssh-add",
            default_effect="deny",
            allow_flags=["-l", "-L"],
            reason="credential-agent changes stay with the user — ask them to run it",
        ),
        ShellCommandRule(
            name="ssh-agent",
            default_effect="deny",
            reason="credential-agent lifecycle stays with the user — ask them to run it",
        ),
        ShellCommandRule(
            name="sort",
            default_effect="allow",
            ask_flags=["-o", "--output", "--compress-program"],
            reason="a sort flag that writes a file or runs a program requires approval",
        ),
        ShellCommandRule(
            # Listing a directory is a read, and `-o` lands that listing in a
            # file — the same flag on the same kind of tool as `sort -o`.
            name="tree",
            default_effect="allow",
            ask_flags=["-o"],
            checkpoint="boundary_wide",
            reason="a tree flag that writes a file requires approval",
        ),
        ShellCommandRule(
            # A search that runs a program. `--pre` and `--hostname-bin` name
            # one ripgrep invokes for every file it touches, which is
            # arbitrary execution wearing a search's clothes, and `-z` hands
            # the input to whichever decompressor the extension implies.
            name="rg",
            default_effect="allow",
            ask_flags=["--pre", "--hostname-bin", "--search-zip", "-z"],
            reason="a ripgrep flag that runs another program requires approval",
        ),
        ShellCommandRule(
            # Encoding is a filter; `-o` is the one form that lands a file.
            name="base64",
            default_effect="allow",
            ask_flags=["-o", "--output"],
            checkpoint="boundary_wide",
            reason="a base64 flag that writes a file requires approval",
        ),
        ShellCommandRule(
            name="yq",
            default_effect="allow",
            ask_flags=["-i", "--inplace", "--in-place", "-s", "--split-exp"],
            checkpoint="boundary_wide",
            reason=(
                "a yq flag that edits files in place or splits into files"
                " requires approval"
            ),
        ),
        ShellCommandRule(
            # xmllint reads every option with one or two leading dashes, so
            # both spellings are guarded; a two-char "-o" guard would
            # cluster-match benign words like -noout, and no bare "-o" option
            # exists.
            name="xmllint",
            default_effect="allow",
            ask_flags=["--output", "-output", "--shell", "-shell"],
            reason=(
                "an xmllint flag that writes files or opens a shell requires approval"
            ),
        ),
        ShellCommandRule(
            # -exec/-execdir payloads recurse through the kernel's find
            # screen; only the file-writing and deleting actions remain
            # flag-guarded.
            name="find",
            default_effect="allow",
            ask_flags=["-delete", "-fprint", "-fprint0", "-fprintf", "-fls"],
            checkpoint="boundary_wide",
            reason="a mutating find action requires approval",
        ),
        ShellCommandRule(
            # `ss -K` closes established sockets; every other form reports.
            name="ss",
            default_effect="allow",
            ask_flags=["-K", "--kill"],
            checkpoint="boundary_wide",
            reason="killing sockets requires approval",
        ),
        ShellCommandRule(
            # Establishing that a port answers is how a session learns the
            # service it just started came up, and `-z` does exactly that and
            # nothing else: connect, report, close. Every other form moves
            # bytes — `-l` listens, `-e`/`-c` hand the socket to a program.
            name="nc",
            default_effect="deny",
            read_verbs=["-z"],
            ask_flags=["-l", "-e", "-c"],
            reason="netcat moves data unless -z pins it to a port scan",
        ),
        ShellCommandRule(
            name="cd", default_effect="allow", reason="directory navigation"
        ),
    ]


def runner_target_rules(
    ambient: Sequence[str] = ("pyright", "pytest", "ruff"),
    session_opening: Sequence[str] = ("lup-devtools",),
) -> list[RunnerTargetRule]:
    """The ``uv run`` targets a project blesses, grouped by what each needs.

    A checker reads the tree and writes inside it, so it runs wherever the
    session runs and takes ``ambient``.

    A toolchain that opens agent sessions cannot. The runtime keeps
    per-session state under its own configuration directory — for Claude Code,
    ``~/.claude/session-env/<session id>``, following ``CLAUDE_CONFIG_DIR`` —
    and a session opened from inside a sandbox that does not grant that path
    dies on its first shell call with a bare ``EROFS``, which reads to an agent
    like a broken repository rather than like a boundary. It then retries,
    works around it, or reports success from a session that never ran a
    command; one planning run finished that way and looked normal.

    The deny is the runtime protecting its own configuration directory, and a
    grant does not lift it. A live session's filesystem policy shows the shape:
    the repository root sits in ``allowOnly`` while the configuration home
    below it — ``session-env`` and its neighbours — is listed again under
    ``denyWithinAllow``, a carve-out applied within the grant. The runtime
    enumerates that directory itself, so the entries appear whether or not a
    project declares them. Nor would lifting it be the
    remedy: the runtime chooses that path per session, so the grant is a family
    rather than a path; deriving a private configuration home does not move it,
    because every entry such a home does not own links back to the shared one;
    and session state is only the first thing such a
    toolchain writes outside the tree — a worktree, a plugin cache, and the
    git configuration behind them follow it.

    That requirement is the *boundary's* to meet rather than a placement to
    declare. A placement says where an operation runs; what a session-opening
    toolchain needs is for wherever it already runs to grant a path — which is
    a statement about the profile, measured at launch, and stated with the rest
    of the boundary. Declared as a placement instead it was unmeasurable: the
    profile that grants the path and the profile that does not both read as
    ``outside``, and the second one only finds out at the first shell call.
    """
    return [RunnerTargetRule(name=name) for name in (*ambient, *session_opening)]


# One criterion decides this table, applied across git's surface rather than to
# whichever word was last found missing: a subcommand belongs here when it moves
# no ref, mutates no index entry, and writes nothing into the working tree.
#
# That is a question about what a verb *reaches*, not about whether it happens
# to write bytes, which is why the object-construction verbs pass it. An object
# nothing points at is unreachable the moment it exists and git collects it, so
# there is no ref to restore and nothing to undo — `merge-tree --write-tree`,
# the way to ask whether two branches still merge, is as unremarkable as
# `merge-base`, and refusing it refuses the question rather than the write.
#
# What fails the criterion is absent on purpose and meets git's own deny:
# `read-tree` and `update-index` write the index, `update-ref` and `pack-refs`
# move refs, and `format-patch`, `unpack-file`, and `difftool --dir-diff` each
# land files in the working tree.
# lup: ignore[library-default] — git's own query and object-construction verbs, taken by the criterion above; which of them reaches a ref is a fact about git rather than a choice made for an adopter
GIT_READ_ONLY_SUBCOMMANDS = (
    # Reporting on the object store, the refs, the index, and the config.
    "status",
    "rev-parse",
    "ls-files",
    "ls-tree",
    "ls-remote",
    "cat-file",
    "blame",
    "annotate",
    "describe",
    "rev-list",
    "name-rev",
    "merge-base",
    "show-ref",
    "for-each-ref",
    "count-objects",
    "cherry",
    "check-ignore",
    "check-attr",
    "check-mailmap",
    "check-ref-format",
    "column",
    "fmt-merge-msg",
    "show-branch",
    "show-index",
    "verify-commit",
    "verify-tag",
    "verify-pack",
    "pack-redundant",
    "fsck",
    "patch-id",
    "request-pull",
    "stripspace",
    "get-tar-commit-id",
    "var",
    "version",
    "help",
    # Constructing an object, which no ref yet points at.
    "merge-tree",
    "hash-object",
    "commit-tree",
    "mktree",
    "mktag",
    "write-tree",
)

# lup: ignore[library-default] — git subcommands the reflog or a second invocation undoes; fixed by what git records rather than by taste
GIT_REVERSIBLE_SUBCOMMANDS = (
    "add",
    "commit",
    "mv",
    "cherry-pick",
    "revert",
    "merge",
    "notes",
    "stage",
)

GIT_CONFIG_EXECUTING_KEYS = (
    "core.hookspath",
    "core.pager",
    "core.editor",
    "core.sshcommand",
    "core.fsmonitor",
    "alias.*",
    "credential.helper",
    "credential.*.helper",
    "init.templatedir",
    "merge.*.driver",
    "filter.*.clean",
    "filter.*.smudge",
    "diff.*.command",
    "diff.*.textconv",
    "url.*.insteadof",
)
"""The git settings whose value is a program, or decides which one runs.

Writing any of these arranges for code to run at somebody else's next git
command, which is what separates them from the rest of `git config`: setting
`user.email` or a branch's base records a fact, and setting `core.hooksPath`
hands over execution. The distinction is the whole reason the row can ask
about one and not the other, and it is why this list is about execution
rather than about importance -- a key that merely matters is not one of
these.

Lowercase because the match folds case, and globbed where git lets the caller
name the middle segment. `credential.*.helper` is listed beside
`credential.helper` because the per-URL form is a separate key rather than a
spelling of the same one, and it runs a program just as readily.
"""


def git_rule(
    guard_force_push: bool = True,
    redirect_checkout: bool = False,
    sandbox: SandboxPlacement = "ambient",
    config_executing_keys: tuple[str, ...] = GIT_CONFIG_EXECUTING_KEYS,
) -> ShellCommandRule:
    """Compile the git surface: reads and reversible work allow, losses ask.

    Three judgements a project can reasonably differ on are parameters rather
    than a reason to fork the table.

    ``guard_force_push`` decides whether replacing what a remote ref points
    at is worth a question. It usually is. A project whose review flow
    rebases and republishes a branch every round answers no, because there
    the force is the ordinary case and the ask lands on nearly every push.
    What removes a ref outright stays guarded either way: no second push
    restores it.

    Both effects are guarded twice over, because push spells each of them
    twice: as a flag, and as refspec grammar. ``--delete origin main`` and
    ``origin :refs/heads/main`` remove the same ref, ``--force`` and
    ``+main:main`` replace the same one, and a guard written only as flag
    spellings held the first half of each pair while allowing the second.
    The parameter therefore moves ``ask_refspecs`` and ``ask_flags``
    together: an effect this rule asks about is asked about however it was
    written.

    ``redirect_checkout`` decides how ``git checkout`` is met. Off, it asks —
    the branch-switching form is harmless, but ``checkout -- <path>``
    discards work. On, it denies and names ``switch`` and ``restore``
    instead, which suits a project that has settled on the newer verbs. The
    ref-sourced ``checkout <ref> -- <path>`` form is recognized by the kernel
    ahead of this row either way, because committed content stays
    recoverable.

    ``sandbox`` is where git runs, stated once here and inherited by every
    subcommand. The default is ``ambient``, because what git needs is not the
    launcher's host but a boundary that grants a route to the remote and the
    repository's own locks — which is a fact about the profile, declared and
    measured with the rest of the boundary rather than requested per command.
    A profile whose boundary cannot grant them says so at launch, where the
    gap is actionable; a placement could only say it per call, after the
    failure. ``outside`` remains available for a verb that genuinely has to
    run on the launcher's host, and is reviewed every time it is used.

    ``config_executing_keys`` are the settings whose value is a program, and
    so the only `git config` writes worth a question. A project can add to
    them -- a bespoke `merge.*.driver` family, or a key its own tooling reads
    and executes -- and one that keeps its configuration under review by
    other means can pass fewer. Passing none makes every config write allow,
    which is a coherent answer for a project whose config is not writable
    from where the agent runs; it is not the default, because it usually is.
    """
    leaf = [
        ShellSubcommandRule(name=name, effect="allow")
        for name in (*GIT_READ_ONLY_SUBCOMMANDS, *GIT_REVERSIBLE_SUBCOMMANDS)
    ]
    push_flags = ["--delete", "--mirror", "--prune"]
    guarded = [
        *[
            ShellSubcommandRule(
                name=name,
                effect="allow",
                ask_flags=["--output"],
                checkpoint="boundary_wide",
                reason="writing command output to a file requires approval",
            )
            # `--output` names a path on the command line and lands a file
            # there, which is the clause that disqualified `format-patch` from
            # the query family above. The plumbing spellings are not a quieter
            # kind of read: `diff-tree --output=` lands a file exactly where
            # `log --output=` does.
            #
            # The guard has to follow forwarding rather than only the verbs
            # that document the flag, because several reach it by handing their
            # arguments to `log` or `diff` — `stash list`, `stash show` and
            # `bisect view` carry it for that reason, on their own rows below.
            # Where a verb forwards is a fact about git worth checking against
            # its source; guarding one that turns out to reject the flag costs
            # nothing, since git refuses it either way.
            #
            # `--ext-diff` and `--textconv` are deliberately absent, by the
            # same reasoning that leaves `--paginate` alone: neither names a
            # program. They enable a driver already configured, and reaching
            # that configuration means `-c` or `git config`, which ask. That is
            # what separates them from `rg --pre`, which takes its program as
            # the next word.
            for name in (
                "log",
                "diff",
                "show",
                "whatchanged",
                "diff-tree",
                "diff-index",
                "diff-files",
                "diff-pairs",
                "range-diff",
                "shortlog",
            )
        ],
        ShellSubcommandRule(
            name="grep",
            effect="allow",
            ask_flags=["-O", "--open-files-in-pager"],
            reason="opening matches in an arbitrary program requires approval",
        ),
        ShellSubcommandRule(
            name="rebase",
            effect="allow",
            ask_flags=["-x", "--exec"],
            reason="replaying commits through a shell command requires approval",
        ),
        ShellSubcommandRule(
            name="fetch",
            effect="allow",
            ask_flags=["--upload-pack"],
            reason="overriding the transport program requires approval",
        ),
        ShellSubcommandRule(
            name="pull",
            effect="allow",
            ask_flags=["--upload-pack"],
            reason="overriding the transport program requires approval",
        ),
        ShellSubcommandRule(
            name="push",
            effect="allow",
            ask_refspecs=(["delete", "force"] if guard_force_push else ["delete"]),
            ask_flags=(
                [*push_flags, "-f", "--force", "--force-with-lease"]
                if guard_force_push
                else push_flags
            ),
            reason=(
                "rewriting or removing a remote ref requires approval"
                if guard_force_push
                else "removing a remote ref requires approval"
            ),
        ),
        ShellSubcommandRule(
            name="clone",
            effect="ask",
            reason="cloning fetches external code — requires approval",
        ),
        ShellSubcommandRule(
            name="apply",
            effect="allow",
            ask_flags=["--unsafe-paths", "--build-fake-ancestor"],
            checkpoint="boundary_wide",
            reason="a patch that writes outside the working area requires approval",
        ),
        ShellSubcommandRule(
            name="restore",
            effect="ask",
            checkpoint="targeted",
            reason="restoring files discards working-tree changes",
        ),
        ShellSubcommandRule(
            name="rm",
            effect="ask",
            checkpoint="targeted",
            reason="removing tracked files requires approval",
        ),
        ShellSubcommandRule(
            # The one destructive git verb the snapshot does not answer, and
            # the reason it keeps asking wherever the others stop. `-fdx`
            # takes ignored files, and ignored files are exactly what the
            # snapshot leaves out: `.env.local`, the resolver's state, a
            # virtual environment. Naming a restorer here would relax the one
            # command whose whole purpose is destroying what nothing holds.
            name="clean",
            effect="ask",
            reason="deleting untracked files is destructive — requires approval",
        ),
        ShellSubcommandRule(
            name="config",
            effect="ask",
            # Where the write lands, when the key says nothing about it. The
            # guarded keys below judge a write to this repository's own
            # configuration; these flags aim the same write at a file the
            # caller names, so a key that reads as ordinary is not.
            ask_flags=["--file", "-f", "--blob"],
            read_verbs=[
                "--get",
                "--get-all",
                "--get-regexp",
                "--get-urlmatch",
                "--get-color",
                "--get-colorbool",
                "--list",
                "-l",
            ],
            guarded_keys=list(config_executing_keys),
            reason=(
                "git config can set what program git runs — this names such a"
                " key, redirects the write to a named file, or cannot be read"
            ),
        ),
        ShellSubcommandRule(
            name="checkout",
            effect="deny" if redirect_checkout else "ask",
            checkpoint="targeted",
            reason=(
                "use git switch for branches or git restore for files"
                if redirect_checkout
                else "checkout can discard working-tree changes"
            ),
        ),
        ShellSubcommandRule(
            name="reflog",
            effect="allow",
            operations=[
                ShellOperationRule(
                    name="expire",
                    effect="ask",
                    reason="expiring reflog entries is destructive — requires approval",
                ),
                ShellOperationRule(
                    name="delete",
                    effect="ask",
                    reason="deleting reflog entries is destructive — requires approval",
                ),
            ],
        ),
        ShellSubcommandRule(
            name="branch",
            effect="allow",
            ask_flags=["-d", "-D", "--delete", "-m", "-M", "--move"],
            reason="deleting or moving a branch requires approval",
        ),
        ShellSubcommandRule(
            name="bisect",
            effect="ask",
            operations=[
                ShellOperationRule(name="log", effect="allow"),
                ShellOperationRule(
                    # Falls back to `git log` where no display is available,
                    # and hands it the arguments it was given.
                    name="view",
                    effect="allow",
                    ask_flags=["--output"],
                    checkpoint="boundary_wide",
                    reason="writing command output to a file requires approval",
                ),
            ],
            checkpoint="targeted",
            reason="a bisect step moves HEAD across commits",
        ),
        ShellSubcommandRule(
            name="submodule",
            effect="ask",
            operations=[
                ShellOperationRule(name="status", effect="allow"),
                ShellOperationRule(name="summary", effect="allow"),
            ],
            reason="submodule operations fetch and check out external code",
        ),
        ShellSubcommandRule(
            name="tag",
            effect="allow",
            ask_flags=["-d", "--delete"],
            reason="deleting a tag requires approval",
        ),
        ShellSubcommandRule(
            # The one query verb whose write form is spelled by arity rather
            # than by a flag: a second operand points the ref somewhere else.
            # The kernel recognizes the reading form ahead of this row.
            name="symbolic-ref",
            effect="ask",
            reason="pointing a symbolic ref somewhere else moves HEAD",
        ),
        ShellSubcommandRule(
            name="reset",
            effect="allow",
            ask_flags=["--hard", "--merge", "--keep"],
            checkpoint="targeted",
            reason="a working-tree-destroying reset requires approval",
        ),
        ShellSubcommandRule(
            name="switch",
            effect="allow",
            ask_flags=["-f", "--force", "--discard-changes"],
            checkpoint="targeted",
            reason="a force switch can discard working-tree changes",
        ),
        ShellSubcommandRule(
            name="worktree",
            effect="deny",
            operations=[
                ShellOperationRule(name="list", effect="allow"),
                ShellOperationRule(name="add", effect="allow"),
                ShellOperationRule(name="move", effect="allow"),
                ShellOperationRule(name="repair", effect="allow"),
                ShellOperationRule(
                    name="remove",
                    effect="ask",
                    reason="removing a worktree deletes it — requires approval",
                ),
                ShellOperationRule(
                    name="prune",
                    effect="ask",
                    reason="pruning worktrees is destructive — requires approval",
                ),
            ],
            reason="this worktree operation is not classified",
        ),
        ShellSubcommandRule(
            name="stash",
            effect="allow",
            operations=[
                ShellOperationRule(
                    # Forwards its arguments to `git log`, `--output` included.
                    name="list",
                    effect="allow",
                    ask_flags=["--output"],
                    checkpoint="boundary_wide",
                    reason="writing command output to a file requires approval",
                ),
                ShellOperationRule(
                    # Accepts any format git diff knows, `--output` included.
                    name="show",
                    effect="allow",
                    ask_flags=["--output"],
                    checkpoint="boundary_wide",
                    reason="writing command output to a file requires approval",
                ),
                ShellOperationRule(name="push", effect="allow"),
                ShellOperationRule(name="save", effect="allow"),
                ShellOperationRule(name="pop", effect="allow"),
                ShellOperationRule(name="apply", effect="allow"),
                ShellOperationRule(
                    name="drop",
                    effect="ask",
                    reason="dropping a stash is destructive — requires approval",
                ),
                ShellOperationRule(
                    name="clear",
                    effect="ask",
                    reason="clearing stashes is destructive — requires approval",
                ),
            ],
        ),
        ShellSubcommandRule(
            name="remote",
            effect="allow",
            operations=[
                ShellOperationRule(
                    name="remove",
                    effect="ask",
                    reason="removing a remote requires approval",
                ),
                ShellOperationRule(
                    name="rm",
                    effect="ask",
                    reason="removing a remote requires approval",
                ),
                ShellOperationRule(
                    name="set-url",
                    effect="ask",
                    reason="changing a remote URL requires approval",
                ),
                ShellOperationRule(
                    name="prune",
                    effect="ask",
                    reason="pruning a remote is destructive — requires approval",
                ),
            ],
        ),
    ]
    # A global that points git somewhere else is judged here rather than per
    # subcommand, because the subcommand word is found only after these are
    # read. A redirect left to `value_flags` alone would only advance the
    # parser past its argument, and every verb behind it would be answered by a
    # row reasoning about this worktree: `git -C /elsewhere commit` reads as
    # reversible because the reflog that undoes it is *here*. The redirect is
    # exactly what makes that premise someone else's.
    #
    # Only the three that name a directory are also in `value_flags`, which
    # selects the wording of the question rather than the parse — the ask is
    # reached before any value is skipped. Those three have a way through worth
    # naming, because `cd there && git status` is two allowed segments.
    # `--namespace` has none: it redirects refs rather than a path, and the
    # environment spelling of it is a guarded assignment of its own.
    #
    # `--paginate` is deliberately not among them, though it is on the list this
    # sweep was measured against. It moves no ref, no index entry, and no file:
    # it forces the pager these subcommands already run by default, and the
    # program that pager names is reachable only through `-c` or `git config`,
    # which ask. Gating it would spend a question on the flag rather than on
    # what the flag could reach.
    directory_flags = ["-C", "--git-dir", "--work-tree"]
    return ShellCommandRule(
        name="git",
        default_effect="deny",
        # `git version` is classified read-only as a subcommand, and the same
        # question spelled as a flag was reaching the default deny -- so the
        # policy answered "this git subcommand is not classified" about a
        # command carrying no subcommand at all. The same shape `bun` fixes
        # above, and the same class as the pure reads §4.2 closed: asking a
        # program what it is cannot change anything.
        allow_flags=["--version", "--help"],
        ask_flags=[
            "-c",
            "--config-env",
            "--exec-path",
            "--super-prefix",
            "--namespace",
            *directory_flags,
        ],
        value_flags=directory_flags,
        sandbox=sandbox,
        subcommands=[*leaf, *guarded],
        reason="this git subcommand is not classified as read-only or reversible",
    )


def gh_rule(allow_authoring: bool = True) -> ShellCommandRule:
    """Compile the gh surface by what each operation does beyond this machine.

    Three bands rather than the two a read/write split offers.

    **Compensable collaboration allows.** Opening a pull request, retitling
    it, marking it ready, commenting, closing, reopening, and the same set for
    issues: every one of them is restored by a normal follow-up operation, and
    a review flow performs several of them every round. Compensable is a claim
    about the remote *state*, never about observation — reopening a pull
    request does not un-send the mail that closing it generated — so it is the
    right test for whether a person needs to see the moment, and the wrong one
    for whether the effect was free.

    **Execution, attestation, publication, and repository security ask.** A
    merge runs something; an approving or request-changes review says
    something in the caller's name; a release publishes; a secret, a ruleset,
    or a repository setting is the security posture of the repository itself.
    A later compensating action may exist for each and does not make them
    compensable: what happened was an event, and events are what a person is
    being asked about.

    **A deletion nested inside an allowed operation survives it.** ``gh pr
    close`` allows and ``gh pr close --delete-branch`` asks, because a safe
    outer verb cannot erase an unsafe inner one. The same shape as a push
    whose refspec deletes.

    ``allow_authoring`` decides whether opening and describing a pull request
    is the author describing their own work or a publication worth a question.
    On, they allow — the branch is already pushed by then. Off, they join the
    verbs that ask.

    Both halves of that grant are claims about *this* repository — the work is
    the author's own, and the branch is already pushed — and ``--repo`` is what
    makes them someone else's, so the authoring verbs carry it as a guard the
    way git's redirecting globals do. Spelled as a flag, the redirect is judged
    per verb, so reading another repository keeps its grant: a read is a read
    wherever it points.

    The flag is only half of it. ``GH_REPO`` and ``GH_HOST`` reach the same
    retarget through the environment, and that spelling is caught by the
    dangerous-assignment prefixes in :mod:`lup.policy.kernel.words` rather than
    here — a guard that reads the assignment before any verb is known, so
    unlike the flag it stops a redirected read as well. The asymmetry is the
    price of catching the variable gh has not learned yet.
    """
    elsewhere = ["-R", "--repo"]
    authoring = ["create", "edit", "ready"]
    # The two spellings of each attestation. gh accepts the short forms, and a
    # guard written as the long ones alone holds half of each — the same shape
    # a push guard written as flag spellings had before refspec grammar was
    # read structurally.
    attesting = ["--approve", "-a", "--request-changes", "-r"]

    def reads(names: list[str]) -> list[ShellOperationRule]:
        """Operations that report and change nothing."""
        return [ShellOperationRule(name=name, effect="allow") for name in names]

    def compensable(names: list[str]) -> list[ShellOperationRule]:
        """Collaboration a normal follow-up operation restores."""
        return [
            ShellOperationRule(
                name=name,
                effect="allow",
                effect_class="compensable",
                ask_flags=elsewhere,
                reason="this operation against another repository requires approval",
            )
            for name in names
        ]

    def judged(
        names: list[str],
        effect_class: EffectClass,
        reason: str,
        reviewer: ReviewerRequirement = "human_only",
    ) -> list[ShellOperationRule]:
        """Operations whose effect a person is asked about every time."""
        return [
            ShellOperationRule(
                name=name,
                effect="ask",
                effect_class=effect_class,
                reviewer=reviewer,
                reason=reason,
            )
            for name in names
        ]

    def group(name: str, operations: list[ShellOperationRule]) -> ShellSubcommandRule:
        return ShellSubcommandRule(
            name=name,
            effect="deny",
            operations=operations,
            reason=f"this gh {name} operation is not classified",
        )

    return ShellCommandRule(
        name="gh",
        default_effect="deny",
        subcommands=[
            group(
                "pr",
                [
                    *reads(["list", "view", "diff", "status", "checks", "checkout"]),
                    *compensable(
                        [
                            "comment",
                            "reopen",
                            *(authoring if allow_authoring else []),
                        ]
                    ),
                    # Closing restores by reopening; deleting the branch does
                    # not, so the deletion nested inside the allowed verb keeps
                    # its own question.
                    ShellOperationRule(
                        name="close",
                        effect="allow",
                        effect_class="compensable",
                        ask_flags=[*elsewhere, "--delete-branch", "-d"],
                        reason="deleting the branch alongside the close"
                        " removes work no reopen restores",
                    ),
                    # A review that carries neither verdict is a comment. The
                    # two that do are claims made in the caller's name, and
                    # saying something else later is not unsaying them.
                    ShellOperationRule(
                        name="review",
                        effect="allow",
                        effect_class="compensable",
                        ask_flags=[*elsewhere, *attesting],
                        reason="approving or requesting changes attests in your"
                        " name — requires approval",
                    ),
                    *judged(
                        ["merge"],
                        "execution",
                        "merging runs the change into the base branch"
                        " — requires approval",
                    ),
                    *(
                        []
                        if allow_authoring
                        else judged(
                            authoring,
                            "publication",
                            "opening or describing a pull request publishes"
                            " — requires approval",
                        )
                    ),
                ],
            ),
            group(
                "issue",
                [
                    *reads(["list", "view", "status"]),
                    *compensable(
                        ["create", "edit", "comment", "close", "reopen", "pin", "unpin"]
                    ),
                    *judged(
                        ["delete", "transfer"],
                        "execution",
                        "removing an issue from this repository is not"
                        " restored by a follow-up — requires approval",
                    ),
                ],
            ),
            group(
                "run",
                [
                    *reads(["list", "view", "watch"]),
                    *judged(
                        ["rerun", "cancel"],
                        "execution",
                        "changing what a workflow run is doing requires approval",
                    ),
                    *compensable(["download"]),
                ],
            ),
            group(
                "repo",
                [
                    *reads(["view", "list"]),
                    # Cloning writes here and reaches nobody there.
                    ShellOperationRule(name="clone", effect="allow"),
                    *judged(
                        ["create", "fork", "rename", "archive", "delete", "edit"],
                        "repository_security",
                        "changing what this repository is, or creating another,"
                        " requires approval",
                    ),
                ],
            ),
            group(
                "release",
                [
                    *reads(["list", "view", "download"]),
                    *judged(
                        ["create", "upload", "edit", "delete"],
                        "publication",
                        "a release is published where people consume it"
                        " — requires approval",
                    ),
                ],
            ),
            group(
                "secret",
                [
                    *reads(["list"]),
                    *judged(
                        ["set", "delete"],
                        "repository_security",
                        "repository secrets decide what automation can reach"
                        " — requires approval",
                    ),
                ],
            ),
            group(
                "variable",
                [
                    *reads(["list", "get"]),
                    *judged(
                        ["set", "delete"],
                        "repository_security",
                        "repository variables configure automation — requires approval",
                    ),
                ],
            ),
            group(
                "ruleset",
                [
                    *reads(["list", "view", "check"]),
                    *judged(
                        ["create", "edit", "delete"],
                        "repository_security",
                        "rulesets are this repository's own protection"
                        " — requires approval",
                    ),
                ],
            ),
            group(
                "workflow",
                [
                    *reads(["list", "view"]),
                    *judged(
                        ["run", "enable", "disable"],
                        "execution",
                        "dispatching or gating a workflow runs something"
                        " — requires approval",
                    ),
                ],
            ),
            group(
                "cache",
                [
                    *reads(["list"]),
                    *compensable([]),
                    *judged(
                        ["delete"],
                        "execution",
                        "a deleted cache is not restored by a follow-up"
                        " — requires approval",
                    ),
                ],
            ),
            group("auth", reads(["status"])),
            group("search", reads(["repos", "issues", "prs", "code", "commits"])),
            group(
                "label",
                [
                    *reads(["list"]),
                    *compensable(["create", "edit", "clone"]),
                    *judged(
                        ["delete"],
                        "execution",
                        "deleting a label removes it from everything carrying it"
                        " — requires approval",
                    ),
                ],
            ),
            group(
                "gist",
                [
                    *reads(["list", "view", "clone"]),
                    *judged(
                        ["create", "edit", "delete"],
                        "publication",
                        "a gist is published outside this repository"
                        " — requires approval",
                    ),
                ],
            ),
            group(
                "project",
                [
                    *reads(["list", "view", "item-list", "field-list"]),
                    *compensable(["item-add", "edit", "close"]),
                    *judged(
                        ["create", "delete", "item-delete"],
                        "execution",
                        "creating or removing project state is not restored by"
                        " a follow-up — requires approval",
                    ),
                ],
            ),
            group("config", [*reads(["get", "list"]), *compensable(["set"])]),
            ShellSubcommandRule(name="status", effect="allow"),
            ShellSubcommandRule(name="browse", effect="allow"),
            ShellSubcommandRule(
                # The default method is GET, so the unguarded form is a read.
                # Every way of making it something else — naming a method,
                # attaching a field, reading a body from a file — is guarded,
                # which leaves the mutation ask exactly where it belongs
                # instead of on every query that shares the subcommand.
                #
                # Opaque rather than classified: this is the one gh surface
                # that can reach any endpoint, so what a mutation here does is
                # exactly what the table cannot say.
                name="api",
                effect="allow",
                effect_class="opaque",
                ask_flags=[
                    "-X",
                    "--method",
                    "-f",
                    "--field",
                    "-F",
                    "--raw-field",
                    "--input",
                ],
                reason="gh api can mutate anything — requires approval",
            ),
        ],
        reason="this gh command is not classified",
    )


def docker_rule() -> ShellCommandRule:
    """Compile the docker surface: queries allow, everything else asks.

    Nothing here is a parameter because the split is not a judgement: a verb
    either reports on containers, images, volumes and the daemon, or changes
    one of them. An unclassified or expansion-obscured subcommand keeps the
    ask rather than falling through to a grant.
    """

    def noun(name: str, verbs: list[str]) -> ShellSubcommandRule:
        return ShellSubcommandRule(
            name=name,
            effect="ask",
            operations=[
                ShellOperationRule(name=verb, effect="allow") for verb in verbs
            ],
            reason="container operations require approval",
        )

    queries = [
        ShellSubcommandRule(name=name, effect="allow")
        for name in (
            "info",
            "version",
            "ps",
            "images",
            "inspect",
            "logs",
            "top",
            "port",
            "diff",
            "history",
            "stats",
            "events",
        )
    ]
    return ShellCommandRule(
        name="docker",
        default_effect="ask",
        subcommands=[
            *queries,
            noun(
                "container", ["ls", "inspect", "logs", "top", "port", "diff", "stats"]
            ),
            noun("image", ["ls", "inspect", "history"]),
            noun("volume", ["ls", "inspect"]),
            noun("network", ["ls", "inspect"]),
            noun("context", ["ls", "show", "inspect"]),
            noun("system", ["df", "info", "events"]),
        ],
        reason="container operations require approval",
    )


def bun_rule() -> ShellCommandRule:
    """Compile the bun surface, which is a package manager wearing a runtime.

    `bun` is in the kernel's interpreter set, so without a rule naming it
    every invocation is refused as inline code — including `bun install`,
    which carries none. Declaring the safe forms is what separates the two,
    and it separates them the safe way round: the default is `deny`, so an
    eval spelling this table never anticipated is refused by falling through
    rather than by being listed. That matters more than usual, because the
    ways of handing an interpreter a program are many and growing — `-e`,
    `--eval`, `-p`, a bare `-` reading stdin, and on a sibling runtime an
    `eval` *subcommand* that no flag list could have caught.

    The split between allow and ask is what a verb does to the manifest
    rather than to the filesystem: restoring dependencies somebody already
    declared is the ordinary case, while adding one, removing one, or
    fetching a package that is not declared at all changes what this project
    depends on and is worth a question.
    """
    return ShellCommandRule(
        name="bun",
        default_effect="deny",
        # The version banner is not a subcommand and would otherwise fall to
        # the default deny, which is the wrong answer for a pure read.
        allow_flags=["--version", "--revision"],
        subcommands=[
            ShellSubcommandRule(
                name="install",
                effect="allow",
                reason="restoring declared dependencies reaches the registry",
            ),
            ShellSubcommandRule(name="run", effect="allow"),
            ShellSubcommandRule(name="test", effect="allow"),
            ShellSubcommandRule(name="build", effect="allow"),
            ShellSubcommandRule(
                name="add",
                effect="ask",
                reason="adding a dependency changes what this project needs",
            ),
            ShellSubcommandRule(
                name="remove",
                effect="ask",
                reason="removing a dependency changes what this project needs",
            ),
            ShellSubcommandRule(
                name="x",
                effect="ask",
                reason="running a package that is not a declared dependency",
            ),
        ],
        reason="bare interpreters and inline code are not allowed",
    )


def typescript_rule() -> list[ShellCommandRule]:
    """Compile the TypeScript compiler: checking allows, emitting asks.

    `--noEmit` is the whole of the read-only form and it still takes
    operands, so no all-flags test recognizes it — which is what
    ``read_verbs`` exists for. A bare invocation writes output at paths a
    configuration file chooses, so nothing in the command bounds what it
    touches, which is the shape this table asks about everywhere else.

    Both package runners are declared alongside it because reaching a
    project-local compiler through one is how a pinned version gets used, and
    a globally installed `tsc` checks against whatever somebody last
    installed. Each default asks, since a runner will fetch a package that is
    not a declared dependency rather than report that it is missing — but the
    compiler they most often reach is named beneath them, so a type check
    spelled through a runner is the read it is. Without that, a verify line
    ending in `npx tsc --noEmit` asked about its last segment and made the
    whole line ask, which is a question about running the type checker.

    They differ on one axis and it is not a preference. `bunx` is placed
    outside the boundary because reaching the registry is what it is for;
    `npx` is left unplaced, because the invocation this rule exists to
    recognize resolves a dependency the project already has and needs no
    network at all. A project whose runner does have to fetch says so by
    widening this declaration, which is a change a reviewer sees.
    """
    checking = ShellSubcommandRule(
        name="tsc",
        effect="ask",
        read_verbs=["--noEmit", "--version"],
        reason="emitting compiler output writes files the command does not bound",
    )
    return [
        ShellCommandRule(
            name="tsc",
            default_effect="ask",
            allow_flags=["--version"],
            read_verbs=["--noEmit"],
            reason="emitting compiler output writes files the command does not bound",
        ),
        ShellCommandRule(
            name="bunx",
            default_effect="ask",
            subcommands=[checking],
            reason="the package runner fetches what is not already a dependency",
        ),
        ShellCommandRule(
            name="npx",
            default_effect="ask",
            subcommands=[checking],
            reason="the package runner fetches what is not already a dependency",
        ),
    ]


def default_vocabulary() -> list[ShellCommandRule]:
    """Every group at its offered defaults — the batteries-included table.

    A project with no opinion yet composes this and gets a working agent; one
    that has an opinion replaces the groups it differs on rather than this
    call.
    """
    return [
        *read_only_rules(),
        *judged_ask_rules(),
        *redirected_rules(),
        *reaching_builtin_rules(),
        *guarded_tool_rules(),
        git_rule(),
        gh_rule(),
        docker_rule(),
    ]
