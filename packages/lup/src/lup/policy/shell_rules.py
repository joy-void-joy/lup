"""Readable source of truth for the shell auto-allow vocabulary.

The hermetic kernel classifies one shell command by consulting primitive rows,
exactly as it consults URL scopes and protected-path rows: the control flow
lives in :mod:`lup.policy.kernel`, the *vocabulary* lives here as data. This
module declares that vocabulary as a nested pydantic table a human can read and
extend, and :func:`erase_shell_rules` flattens it into the ``ShellRuleRow``
tuples the kernel interprets. :mod:`lup.policy.bundle` erases the same table
into ``policy_data.py`` at generation time, so the canonical ``ShellPolicy``
and every generated dispatcher decide identically.

Three nesting levels mirror how real tools are shaped:

* a bare command — ``ls``, ``sort`` — is read-only (``default_effect`` is
  ``allow``), optionally with ``ask_flags`` that turn a reader into a writer
  (``sort -o``, ``find -delete``);
* a subcommand command — ``git``, ``gh`` — defaults to ``ask`` and allows only
  the subcommands it lists (``git status``, ``gh pr view``); its
  ``value_flags`` skip value-taking globals (``git -C <path>``) so the value
  is never read as the subcommand, and its ``ask_flags`` guard dangerous
  globals (``git -c``);
* a subcommand whose *operation* word decides safety — ``git worktree add`` is
  reversible, ``git worktree remove`` is not — carries ``operations``.

The baseline is deliberately generous for read-only and reversible-local work
and conservative for anything destructive or networked: a destructive form
(``git push``, ``git reset --hard``, ``git branch -D``, ``gh pr close``) stays
an approval question. An adopter extends the vocabulary through
``HookSet.shell_rules`` rather than editing the kernel; the two tables are
concatenated at erasure time.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lup.policy.kernel import ShellRuleRow

type CommandEffect = Literal["allow", "ask"]


class ShellOperationRule(BaseModel):
    """One operation word under a subcommand — e.g. ``worktree remove``."""

    model_config = ConfigDict(frozen=True)

    name: str
    effect: CommandEffect
    ask_flags: list[str] = Field(default_factory=list)
    reason: str = ""


class ShellSubcommandRule(BaseModel):
    """One subcommand under a command — e.g. ``git worktree``, ``gh pr``."""

    model_config = ConfigDict(frozen=True)

    name: str
    effect: CommandEffect = "allow"
    ask_flags: list[str] = Field(default_factory=list)
    operations: list[ShellOperationRule] = Field(default_factory=list)
    reason: str = ""


class ShellCommandRule(BaseModel):
    """One executable — a read-only tool, or a subcommand-gated command.

    On a subcommand-gated command, ``value_flags`` name the global options that
    consume the following word (``git -C <path>``) so the value is never read
    as the subcommand, and ``ask_flags`` guard dangerous globals in that same
    pre-subcommand position (``git -c``).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    default_effect: CommandEffect = "allow"
    ask_flags: list[str] = Field(default_factory=list)
    value_flags: list[str] = Field(default_factory=list)
    subcommands: list[ShellSubcommandRule] = Field(default_factory=list)
    reason: str = ""


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
    "yq",
    "xmllint",
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
    "sleep",
    "pwd",
    "id",
    "whoami",
    "hostname",
    "uname",
    "printenv",
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
    """Compile the git surface: read-only and reversible-local allow, else ask."""
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
            effect="ask",
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
            reason="unknown worktree operation requires approval",
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
        default_effect="ask",
        ask_flags=["-c", "--config-env", "--exec-path"],
        value_flags=["-C", "--git-dir", "--work-tree", "--namespace"],
        subcommands=[*leaf, *guarded],
        reason="this git subcommand is not classified as read-only or reversible",
    )


def gh_read_only_rule() -> ShellCommandRule:
    """Compile the gh surface: read-only subcommand operations only."""

    def viewer(name: str, *operations: str) -> ShellSubcommandRule:
        return ShellSubcommandRule(
            name=name,
            effect="ask",
            operations=[
                ShellOperationRule(name=operation, effect="allow")
                for operation in operations
            ],
            reason=f"this gh {name} operation is not read-only",
        )

    return ShellCommandRule(
        name="gh",
        default_effect="ask",
        subcommands=[
            viewer("pr", "list", "view", "diff", "status", "checks"),
            viewer("issue", "list", "view", "status"),
            viewer("run", "list", "view", "watch"),
            viewer("repo", "view", "list"),
            viewer("release", "list", "view"),
            viewer("cache", "list"),
            viewer("workflow", "list", "view"),
        ],
        reason="this gh command is not classified as read-only",
    )


BASE_SHELL_RULES: list[ShellCommandRule] = [
    *[ShellCommandRule(name=name) for name in READ_ONLY_COMMANDS],
    ShellCommandRule(
        name="sort",
        ask_flags=["-o", "--output", "--compress-program"],
        reason="a sort flag that writes a file or runs a program requires approval",
    ),
    ShellCommandRule(
        name="find",
        ask_flags=[
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-delete",
            "-fprint",
            "-fprintf",
            "-fls",
        ],
        reason="a mutating find action requires approval",
    ),
    ShellCommandRule(name="cd", reason="directory navigation"),
    git_rule(),
    gh_read_only_rule(),
]


def erase_shell_rules(rules: list[ShellCommandRule]) -> list[ShellRuleRow]:
    """Flatten the nested table into the kernel's primitive command rows.

    Each row is ``(command, subcommand, operation, effect, ask_flags, reason)``;
    an empty string at a level means "the default at that level". A command
    contributes one default row plus, per subcommand, one row per operation and
    a subcommand-default row for the bare form.
    """

    def subcommand_rows(
        command_name: str, subcommand: ShellSubcommandRule
    ) -> list[ShellRuleRow]:
        operations = [
            ShellRuleRow(
                command=command_name,
                subcommand=subcommand.name,
                operation=operation.name,
                effect=operation.effect,
                ask_flags=list(operation.ask_flags),
                value_flags=[],
                reason=operation.reason,
            )
            for operation in subcommand.operations
        ]
        default = ShellRuleRow(
            command=command_name,
            subcommand=subcommand.name,
            operation="",
            effect=subcommand.effect,
            ask_flags=list(subcommand.ask_flags),
            value_flags=[],
            reason=subcommand.reason,
        )
        return [*operations, default]

    def command_rows(command: ShellCommandRule) -> list[ShellRuleRow]:
        default = ShellRuleRow(
            command=command.name,
            subcommand="",
            operation="",
            effect=command.default_effect,
            ask_flags=list(command.ask_flags),
            value_flags=list(command.value_flags),
            reason=command.reason,
        )
        nested = [
            row
            for subcommand in command.subcommands
            for row in subcommand_rows(command.name, subcommand)
        ]
        return [default, *nested]

    return [row for command in rules for row in command_rows(command)]
