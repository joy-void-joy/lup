"""Primitive row shapes the generated data file renders into."""

from typing import Literal, TypedDict

from .decision import DecisionEffect

type PathRuleKind = Literal[
    "exact",
    "subtree",
    "name_prefix",
    "new_subtree",
    "contains_part",
    "new_devtools",
]


class UrlScopeRow(TypedDict):
    """One erased fetch scope: an origin, the path beneath it, and its reason.

    ``include_subdomains`` widens ``host`` to cover names beneath it, so a
    scope can name a documentation site once instead of every subdomain.
    """

    scheme: str
    host: str
    port: int | None
    path_prefix: str
    reason: str
    include_subdomains: bool


class PathRuleRow(TypedDict):
    """One erased protected-path rule and whether review may bypass it.

    ``allow_autonomous`` releases the rule for an identity that already
    reviews its own edits; every other rule holds regardless of caller.
    """

    kind: PathRuleKind
    value: str
    reason: str
    allow_autonomous: bool


class AntiPatternRow(TypedDict):
    """One erased anti-pattern rule and the syntactic context it inspects."""

    id: str
    pattern: str
    message: str
    context: str


class ShellRuleRow(TypedDict):
    """One erased shell-command rule the kernel matches by executable name.

    ``subcommand`` and ``operation`` are ``""`` at the levels a rule does not
    constrain; ``ask_flags`` downgrades an ``allow`` to ``ask`` when one of the
    named flags appears among the command's remaining words. On the
    command-level row of a subcommand-gated command, ``ask_flags`` guard the
    global options before the subcommand and ``value_flags`` name globals that
    consume the following word (``git -C <path>``), so a flag value is never
    read as the subcommand. ``allow_flags`` name a pure read-only form of a
    non-allow row (``ssh-add -l``): the row de-escalates to allow only when
    every remaining word is exactly one of the named flags, so clusters,
    ``=`` values, paths, and unresolved expansions never qualify.
    ``read_verbs`` name action-selecting flags of a command that enforces one
    action at a time (``git config --get``): a non-allow row de-escalates to
    allow when a declared verb appears among words that are all literal and
    free of guarded flags, because the verb pins the invocation to its query
    action regardless of the other words.
    """

    command: str
    subcommand: str
    operation: str
    effect: DecisionEffect
    ask_flags: list[str]
    allow_flags: list[str]
    read_verbs: list[str]
    value_flags: list[str]
    reason: str
