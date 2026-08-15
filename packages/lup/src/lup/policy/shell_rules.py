"""The shape a shell vocabulary takes, and its erasure into kernel rows.

The hermetic kernel classifies one shell command by consulting primitive rows,
exactly as it consults URL scopes and protected-path rows: the control flow
lives in :mod:`lup.policy.kernel`, and the *vocabulary* — which tools are safe
to run unattended, which forms need a human — is a judgement about one
project's toolchain, so it arrives from outside. This module declares the
shape that judgement takes as a nested pydantic table a human can read and
extend, and :func:`erase_shell_rules` flattens it into the ``ShellRuleRow``
tuples the kernel interprets.

An application declares its own table and hands it to ``ShellPolicy`` and to
``HookSet.shell_rules``; :mod:`lup.policy.bundle` erases that same table into
``policy_data.py`` at generation time, so the canonical ``ShellPolicy`` and
every generated dispatcher decide identically. This repository's table is
``lup_template.devtools.harness.content.shell_vocabulary``.

Three nesting levels mirror how real tools are shaped:

* a bare command — ``ls``, ``sort`` — is read-only (``default_effect`` is
  ``allow``), optionally with ``ask_flags`` that turn a reader into a writer
  (``sort -o``, ``find -delete``);
* a subcommand command — ``git``, ``gh`` — defaults to ``deny`` (an unjudged
  subcommand bounces back to the agent) and lists the subcommands it has
  judged (``git status`` allows, ``git push`` asks); its ``value_flags`` skip
  value-taking globals (``git -C <path>``) so the value is never read as the
  subcommand, and its ``ask_flags`` guard dangerous globals (``git -c``);
* a subcommand whose *operation* word decides safety — ``git worktree add`` is
  reversible, ``git worktree remove`` is not — carries ``operations``.
"""

from typing import Literal

from pydantic import BaseModel

from lup.policy.kernel.rows import ShellRuleRow

type CommandEffect = Literal["allow", "ask", "deny"]


class ShellOperationRule(BaseModel, frozen=True):
    """One operation word under a subcommand — e.g. ``worktree remove``."""

    name: str
    effect: CommandEffect
    ask_flags: list[str] = []
    reason: str = ""


class ShellSubcommandRule(BaseModel, frozen=True):
    """One subcommand under a command — e.g. ``git worktree``, ``gh pr``.

    ``read_verbs`` name action-selecting flags that pin a one-action-at-a-time
    subcommand to its query form (``git config --get``); their presence among
    literal, unguarded words de-escalates a non-allow effect to allow.
    """

    name: str
    effect: CommandEffect = "allow"
    ask_flags: list[str] = []
    read_verbs: list[str] = []
    operations: list[ShellOperationRule] = []
    reason: str = ""


class ShellCommandRule(BaseModel, frozen=True):
    """One executable — a read-only tool, or a subcommand-gated command.

    On a subcommand-gated command, ``value_flags`` name the global options that
    consume the following word (``git -C <path>``) so the value is never read
    as the subcommand, and ``ask_flags`` guard dangerous globals in that same
    pre-subcommand position (``git -c``). ``allow_flags`` declare the pure
    read-only form of a non-allow command: the row de-escalates to allow only
    when every argument is exactly one of the named flags (``ssh-add -l``).
    ``read_verbs`` do the same for a command whose read-only form still takes
    operands, so no all-flags test can recognize it (``nc -z host port``): a
    declared verb among otherwise literal, unguarded words pins the action.
    """

    name: str
    default_effect: CommandEffect = "allow"
    ask_flags: list[str] = []
    allow_flags: list[str] = []
    read_verbs: list[str] = []
    value_flags: list[str] = []
    subcommands: list[ShellSubcommandRule] = []
    reason: str = ""


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
                allow_flags=[],
                read_verbs=[],
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
            allow_flags=[],
            read_verbs=list(subcommand.read_verbs),
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
            allow_flags=list(command.allow_flags),
            read_verbs=list(command.read_verbs),
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
