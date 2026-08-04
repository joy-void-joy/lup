"""This project's shell auto-allow vocabulary, declared as harness content.

The rule models and :func:`~lup.policy.shell_rules.erase_shell_rules` are
library mechanism; the *words* are this project's judgement about its own
toolchain, and they live here beside the fetch scopes and protected roots the
``HookSet`` in ``devtools/harness/catalog.py`` already owns. A downstream
project declares its own table and never edits lup to change a verdict.
:mod:`lup.policy.shell_rules` documents the three nesting levels an entry can
take and how each one erases into the rows the kernel reads.

The table is deliberately generous for read-only and reversible-local work and
conservative for anything destructive or networked: a destructive form
(``git push``, ``git reset --hard``, ``git branch -D``, ``gh pr close``) stays
an approval question.
"""

from lup.policy.shell_rules import (
    ShellCommandRule,
    ShellOperationRule,
    ShellSubcommandRule,
)

READ_ONLY_COMMANDS = (
    "ls",
    "tree",
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
    "comm",
    "join",
    "paste",
    "column",
    "uniq",
    "grep",
    "egrep",
    "fgrep",
    "rg",
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
    "true",
    "false",
    "set",
    "sleep",
    "pwd",
    "id",
    "whoami",
    "hostname",
    "uname",
    "printenv",
    "env",
    "ps",
    "free",
    "uptime",
    "nproc",
    "xxd",
    "od",
    "strings",
    "getent",
    "zcat",
    "[",
)

# These ask on every production path. Inside a root a `HookPathRole` declares
# as scratch they allow instead, which `lup.policy.kernel.words` settles by
# resolving each target's role. Closing the scratch execution path is what
# makes that safe: authoring a file there no longer earns an agent code it can
# run, so creating content is as harmless as destroying it.
JUDGED_ASK_COMMANDS = (
    ("rm", "deleting files requires approval"),
    ("rmdir", "deleting directories requires approval"),
    ("mv", "moving files requires approval"),
    ("cp", "copying over files requires approval"),
    ("mkdir", "creating directories requires approval"),
    ("touch", "creating files requires approval — prefer the Write tool"),
    ("chmod", "changing permissions requires approval"),
    ("chown", "changing ownership requires approval"),
    ("ln", "creating links requires approval"),
    ("tee", "writing files requires approval — prefer the Write tool"),
    ("dd", "raw device or file writes require approval"),
    ("truncate", "truncating files requires approval"),
    ("kill", "terminating processes requires approval"),
    ("pkill", "terminating processes requires approval"),
    ("tar", "archive operations write files — requires approval"),
    ("unzip", "archive extraction writes files — requires approval"),
    ("zip", "archive creation writes files — requires approval"),
    ("gzip", "compression rewrites files — requires approval"),
    ("gunzip", "decompression rewrites files — requires approval"),
    ("sudo", "privilege escalation requires approval"),
    ("doas", "privilege escalation requires approval"),
    ("ssh", "remote access requires approval"),
    ("scp", "remote copies require approval"),
    ("rsync", "remote sync requires approval"),
    ("wget", "downloading files requires approval — prefer curl or WebFetch"),
    ("make", "make executes arbitrary recipes — requires approval"),
    ("npm", "package tools fetch and execute code — requires approval"),
    ("npx", "package tools fetch and execute code — requires approval"),
    ("pnpm", "package tools fetch and execute code — requires approval"),
    ("yarn", "package tools fetch and execute code — requires approval"),
    ("apt", "system package changes require approval"),
    ("apt-get", "system package changes require approval"),
    ("pacman", "system package changes require approval"),
    ("brew", "system package changes require approval"),
    ("systemctl", "service management requires approval"),
    ("crontab", "schedule changes require approval"),
)

REDIRECTED_DENY_COMMANDS = (
    ("pip", "use uv add / uv remove instead of pip"),
    ("pip3", "use uv add / uv remove instead of pip"),
)

GIT_READ_ONLY_SUBCOMMANDS = (
    "status",
    "rev-parse",
    "ls-files",
    "ls-tree",
    "cat-file",
    "blame",
    "describe",
    "shortlog",
    "rev-list",
    "name-rev",
    "merge-base",
    "show-ref",
    "symbolic-ref",
    "for-each-ref",
    "count-objects",
    "cherry",
    "range-diff",
    "version",
    "help",
)

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


def git_rule() -> ShellCommandRule:
    """Compile the git surface: read-only and reversible-local allow, judged
    destructive or publishing forms ask, and unjudged subcommands deny."""
    leaf = [
        ShellSubcommandRule(name=name)
        for name in (*GIT_READ_ONLY_SUBCOMMANDS, *GIT_REVERSIBLE_SUBCOMMANDS)
    ]
    guarded = [
        *[
            ShellSubcommandRule(
                name=name,
                ask_flags=["--output"],
                reason="writing command output to a file requires approval",
            )
            for name in ("log", "diff", "show", "whatchanged")
        ],
        ShellSubcommandRule(
            name="grep",
            ask_flags=["-O", "--open-files-in-pager"],
            reason="opening matches in an arbitrary program requires approval",
        ),
        ShellSubcommandRule(
            name="rebase",
            ask_flags=["-x", "--exec"],
            reason="replaying commits through a shell command requires approval",
        ),
        ShellSubcommandRule(
            name="fetch",
            ask_flags=["--upload-pack"],
            reason="overriding the transport program requires approval",
        ),
        ShellSubcommandRule(
            name="pull",
            ask_flags=["--upload-pack"],
            reason="overriding the transport program requires approval",
        ),
        ShellSubcommandRule(
            name="push",
            effect="ask",
            reason="publishing to the remote requires approval",
        ),
        ShellSubcommandRule(
            name="clone",
            effect="ask",
            reason="cloning fetches external code — requires approval",
        ),
        ShellSubcommandRule(
            name="apply",
            ask_flags=["--unsafe-paths", "--build-fake-ancestor"],
            reason="a patch that writes outside the working area requires approval",
        ),
        ShellSubcommandRule(
            name="restore",
            effect="ask",
            reason="restoring files discards working-tree changes",
        ),
        ShellSubcommandRule(
            name="rm",
            effect="ask",
            reason="removing tracked files requires approval",
        ),
        ShellSubcommandRule(
            name="clean",
            effect="ask",
            reason="deleting untracked files is destructive — requires approval",
        ),
        ShellSubcommandRule(
            name="config",
            effect="ask",
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
            reason="git config can change how commands execute",
        ),
        ShellSubcommandRule(
            name="checkout",
            effect="deny",
            reason="use git switch for branches or git restore for files",
        ),
        ShellSubcommandRule(
            name="reflog",
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
            ask_flags=["-d", "-D", "--delete", "-m", "-M", "--move"],
            reason="deleting or moving a branch requires approval",
        ),
        ShellSubcommandRule(
            name="tag",
            ask_flags=["-d", "--delete"],
            reason="deleting a tag requires approval",
        ),
        ShellSubcommandRule(
            name="reset",
            ask_flags=["--hard", "--merge", "--keep"],
            reason="a working-tree-destroying reset requires approval",
        ),
        ShellSubcommandRule(
            name="switch",
            ask_flags=["-f", "--force", "--discard-changes"],
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
            operations=[
                ShellOperationRule(name="list", effect="allow"),
                ShellOperationRule(name="show", effect="allow"),
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
    return ShellCommandRule(
        name="git",
        default_effect="deny",
        ask_flags=["-c", "--config-env", "--exec-path"],
        value_flags=["-C", "--git-dir", "--work-tree", "--namespace"],
        subcommands=[*leaf, *guarded],
        reason="this git subcommand is not classified as read-only or reversible",
    )


def gh_rule() -> ShellCommandRule:
    """Compile the gh surface: read-only allow, judged mutations ask, else deny."""

    def group(
        name: str, allowed: list[str], asked: list[str] | None = None
    ) -> ShellSubcommandRule:
        return ShellSubcommandRule(
            name=name,
            effect="deny",
            operations=[
                *[
                    ShellOperationRule(name=operation, effect="allow")
                    for operation in allowed
                ],
                *[
                    ShellOperationRule(
                        name=operation,
                        effect="ask",
                        reason=f"gh {name} {operation} changes remote state"
                        " — requires approval",
                    )
                    for operation in asked or []
                ],
            ],
            reason=f"this gh {name} operation is not classified",
        )

    return ShellCommandRule(
        name="gh",
        default_effect="deny",
        subcommands=[
            group(
                "pr",
                ["list", "view", "diff", "status", "checks", "checkout"],
                ["create", "edit", "comment", "review", "merge", "ready", "close"],
            ),
            group(
                "issue",
                ["list", "view", "status"],
                ["create", "edit", "comment", "close"],
            ),
            group("run", ["list", "view", "watch"], ["rerun", "cancel", "download"]),
            group("repo", ["view", "list"], ["clone", "fork"]),
            group("release", ["list", "view"], ["create", "upload"]),
            group("cache", ["list"], ["delete"]),
            group("workflow", ["list", "view"], ["run", "enable", "disable"]),
            group("auth", ["status"]),
            ShellSubcommandRule(
                name="api",
                effect="ask",
                reason="gh api can read or mutate anything — requires approval",
            ),
        ],
        reason="this gh command is not classified",
    )


def docker_rule() -> ShellCommandRule:
    """Compile the docker surface: read-only queries allow; every form that
    can mutate containers, images, volumes, or the daemon keeps the judged
    ask, including unclassified and expansion-obscured subcommands."""

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
        ShellSubcommandRule(name=name)
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


SHELL_RULES: list[ShellCommandRule] = [
    *[ShellCommandRule(name=name) for name in READ_ONLY_COMMANDS],
    *[
        ShellCommandRule(name=name, default_effect="ask", reason=reason)
        for name, reason in JUDGED_ASK_COMMANDS
    ],
    *[
        ShellCommandRule(name=name, default_effect="deny", reason=reason)
        for name, reason in REDIRECTED_DENY_COMMANDS
    ],
    ShellCommandRule(
        # -l/-L print fingerprints and public keys — the read-only diagnostic
        # for push-auth failures; every other form mutates the agent.
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
        ask_flags=["-o", "--output", "--compress-program"],
        reason="a sort flag that writes a file or runs a program requires approval",
    ),
    ShellCommandRule(
        name="yq",
        ask_flags=["-i", "--inplace", "--in-place", "-s", "--split-exp"],
        reason="a yq flag that edits files in place or splits into files requires approval",
    ),
    ShellCommandRule(
        # xmllint reads every option with one or two leading dashes, so both
        # spellings are guarded; a two-char "-o" guard would cluster-match
        # benign words like -noout, and no bare "-o" option exists.
        name="xmllint",
        ask_flags=["--output", "-output", "--shell", "-shell"],
        reason="an xmllint flag that writes files or opens a shell requires approval",
    ),
    ShellCommandRule(
        # -exec/-execdir payloads recurse through the kernel's find screen;
        # only the file-writing and deleting actions remain flag-guarded.
        name="find",
        ask_flags=[
            "-delete",
            "-fprint",
            "-fprintf",
            "-fls",
        ],
        reason="a mutating find action requires approval",
    ),
    ShellCommandRule(name="cd", reason="directory navigation"),
    git_rule(),
    gh_rule(),
    docker_rule(),
]
