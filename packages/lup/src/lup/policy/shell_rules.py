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

* a bare command — ``ls``, ``sort`` — declares ``default_effect="allow"``,
  optionally with ``ask_flags`` that turn a reader into a writer (``sort -o``,
  ``find -delete``);
* a subcommand command — ``git``, ``gh`` — declares ``default_effect="deny"``
  (an unjudged subcommand bounces back to the agent) and lists the subcommands
  it has judged (``git status`` allows, ``git push`` asks); its ``value_flags``
  skip value-taking globals (``git -C <path>``) so the value is never read as
  the subcommand, and its ``ask_flags`` guard dangerous globals (``git -c``);
* a subcommand whose *operation* word decides safety — ``git worktree add`` is
  reversible, ``git worktree remove`` is not — carries ``operations``.

Both axes cascade down that nesting, and absence has exactly one meaning
everywhere: a level that omits ``effect`` or ``sandbox`` inherits the value
from the level above it, and a level that states one overrides what it
inherited in either direction — widening a restrictive parent is as ordinary
as narrowing a permissive one. So ``git`` says once where its subcommands run,
and each of them says only what differs.

Absence is distinguished from a stated value of the same word by what pydantic
already records about which fields a declaration supplied, so no field is
retyped as optional to carry the distinction. The one field with no such
escape is ``ShellCommandRule.default_effect``, which is required: who decides
has no member meaning "no opinion", so a command that forgot to say is a gap a
reader should see rather than a value it silently inherited. ``ROOT_EFFECT``
is what would be inherited beneath every table, spelled restrictively for the
same reason.
"""

from typing import Literal, TypedDict

from pydantic import BaseModel

from lup.policy.kernel.semantics import EffectClass, ReviewerRequirement
from lup.policy.kernel.decision import (
    DecisionEffect,
    CheckpointRequirement,
    SandboxPlacement,
)
from lup.policy.kernel.rows import (
    RefspecEffect,
    RunnerTargetRow,
    RuleLevel,
    ShellRuleRow,
)
from lup.seams import SelectableRule

type CommandEffect = Literal["allow", "ask", "deny"]

ROOT_EFFECT: CommandEffect = "deny"
"""Who decides, beneath a table that says nothing — nobody, so a human.

Every command declares its own effect, so this is structurally unreachable
through the models. It is spelled anyway, and spelled restrictively, because
the value a forgotten declaration would fall to is the one place a silent
default becomes a grant.
"""

ROOT_SANDBOX: SandboxPlacement = "ambient"
"""Where a call runs, beneath a table that says nothing — wherever it lands.

Unlike the effect axis, this one has a member meaning "no opinion", so
omission is a statement here rather than a gap, and a command is not made to
repeat it.
"""

ROOT_CHECKPOINT: CheckpointRequirement = "unrecoverable"
"""What puts back a loss nobody named — nothing does, so the question stands.

The restrictive value, for the reason ``ROOT_EFFECT`` is: this axis is read
to *relax* an approval question, so the value a forgotten declaration falls
to has to be the one that relaxes nothing. Annotating a rule is what says a
boundary answers for it, and silence can then only cost a prompt somebody did
not need, never a loss nobody could put back.
"""


ROOT_REVIEWER: ReviewerRequirement = "human_only"
"""Who answers a question no rule said anything about — a person.

The restrictive value, and for the reason ``ROOT_EFFECT`` is restrictive: this
axis is read to *widen* who may answer, so what a forgotten declaration falls
to has to widen nothing. A rule that means its question to be answerable by a
supervisor says so, and silence can then only cost a person a question a
supervisor could have taken, never route a release past them.
"""


class DeclaredAxes(BaseModel, frozen=True):
    """What one level of a table states, leaving the rest to the level above.

    ``None`` is inheritance, and it is the only thing absence means anywhere in
    the table — never a reset to the most permissive value.
    """

    effect: CommandEffect | None = None
    sandbox: SandboxPlacement | None = None
    checkpoint: CheckpointRequirement | None = None
    reviewer: ReviewerRequirement | None = None
    effect_class: EffectClass | None = None


class RowAxes(TypedDict):
    """The fields one resolved level contributes to an erased row.

    Provenance travels beside each value because the question a reader
    has at a verdict they did not expect is which level said so, and a
    resolved value alone cannot answer it.
    """

    effect: DecisionEffect
    effect_source: RuleLevel
    sandbox: SandboxPlacement
    sandbox_source: RuleLevel
    checkpoint: CheckpointRequirement
    checkpoint_source: RuleLevel
    reviewer: ReviewerRequirement
    effect_class: str


class ResolvedAxes(BaseModel, frozen=True):
    """Every axis as one level resolved it, and where each value came from."""

    effect: CommandEffect
    effect_source: RuleLevel
    sandbox: SandboxPlacement
    sandbox_source: RuleLevel
    checkpoint: CheckpointRequirement
    checkpoint_source: RuleLevel
    reviewer: ReviewerRequirement
    effect_class: EffectClass | None

    def row_fields(self) -> RowAxes:
        """This triple as the erased row spells it, provenance included."""
        return RowAxes(
            effect=self.effect,
            effect_source=self.effect_source,
            sandbox=self.sandbox,
            sandbox_source=self.sandbox_source,
            checkpoint=self.checkpoint,
            checkpoint_source=self.checkpoint_source,
            reviewer=self.reviewer,
            effect_class=self.effect_class or "",
        )

    def inherit(self, declared: DeclaredAxes, level: RuleLevel) -> "ResolvedAxes":
        """These axes as the level beneath resolves them over its own statements.

        A declaration wins in either direction: widening a restrictive parent is
        as ordinary as narrowing a permissive one, so nothing here compares the
        two values — only whether the level supplied one.
        """
        return ResolvedAxes(
            effect=self.effect if declared.effect is None else declared.effect,
            effect_source=self.effect_source if declared.effect is None else level,
            sandbox=self.sandbox if declared.sandbox is None else declared.sandbox,
            sandbox_source=self.sandbox_source if declared.sandbox is None else level,
            checkpoint=self.checkpoint if declared.checkpoint is None else declared.checkpoint,
            checkpoint_source=(
                self.checkpoint_source if declared.checkpoint is None else level
            ),
            reviewer=(
                self.reviewer if declared.reviewer is None else declared.reviewer
            ),
            effect_class=(
                self.effect_class
                if declared.effect_class is None
                else declared.effect_class
            ),
        )


ROOT_AXES = ResolvedAxes(
    effect=ROOT_EFFECT,
    effect_source="root",
    sandbox=ROOT_SANDBOX,
    sandbox_source="root",
    checkpoint=ROOT_CHECKPOINT,
    checkpoint_source="root",
    reviewer=ROOT_REVIEWER,
    effect_class=None,
)
"""What the outermost level of every table inherits from."""


class RunnerTargetRule(BaseModel, frozen=True):
    """One ``uv run <target>`` a project blesses, and where it has to run.

    ``uv`` is parsed rather than matched against the command table, so this is
    the only surface on which a runner target can carry the sandbox axis. A
    toolchain that opens its own agent sessions needs ``outside``: the runtime
    creates per-session state under its configuration directory, and a session
    launched from inside a sandbox that does not grant that path loses its
    shell entirely. Declaring it beside the name is what keeps the escape off
    the call sites — one that has to remember a flag is one that forgets it.

    The field is the whole placement vocabulary and not a two-valued switch,
    so a target that only sometimes needs the outside says ``escalable`` here
    and keeps the ordinary run confined. One field says every way a target may
    leave, which is what stops a second way of saying it from growing.
    """

    name: str
    sandbox: SandboxPlacement = "ambient"

    effect: CommandEffect = "allow"
    """What running this target costs, on the same vocabulary a command row uses.

    Blessing is the common case and stays the default. The other effects are
    here because a target a project means to refuse has nowhere else to say
    so: leaving it undeclared is not a refusal but an absence of judgment,
    which a confined session hands to the runtime's own permissions. For a
    target that spends money, runs for an hour, or publishes something, not
    refusing is precisely the outcome the declaration existed to prevent.
    """

    reason: str = ""
    """What the agent is told, which for a refusal is the whole of its value.

    A refused target usually has a right way to reach the same end — print
    the command for a human to run, use the dry-run flag, go through the
    review step — and the reason is the only channel that carries it.
    """

    subcommands: list["ShellSubcommandRule"] = []
    """Verbs beneath the target that answer differently from the target itself.

    A toolchain reached through ``uv run`` is one target and many commands,
    and a project that blesses the toolchain rarely means to bless every verb
    in it — a devtools CLI that mostly reads a repository may also have one
    subcommand that opens a paid agent session. Without this the choice is
    between blessing that verb and refusing the whole toolchain.

    The shape is the shell table's own, and so is the matching: a target with
    subcommands is judged by the same rows and the same walk as a command
    named directly, with the target's own effect as the default beneath them.
    Empty leaves the target a single verdict, which is what most are.
    """


class ShellOperationRule(BaseModel, frozen=True):
    """One operation word under a subcommand — e.g. ``worktree remove``."""

    name: str
    effect: CommandEffect = ROOT_EFFECT
    ask_flags: list[str] = []
    sandbox: SandboxPlacement = ROOT_SANDBOX
    checkpoint: CheckpointRequirement = ROOT_CHECKPOINT
    reviewer: ReviewerRequirement = ROOT_REVIEWER
    effect_class: EffectClass | None = None
    reason: str = ""

    def declared(self) -> DeclaredAxes:
        """The axes this operation states itself, leaving the rest to inherit."""
        supplied = self.model_fields_set
        return DeclaredAxes(
            effect=self.effect if "effect" in supplied else None,
            sandbox=self.sandbox if "sandbox" in supplied else None,
            checkpoint=self.checkpoint if "checkpoint" in supplied else None,
            reviewer=self.reviewer if "reviewer" in supplied else None,
            effect_class=(
                self.effect_class if "effect_class" in supplied else None
            ),
        )


class ShellSubcommandRule(BaseModel, frozen=True):
    """One subcommand under a command — e.g. ``git worktree``, ``gh pr``.

    ``read_verbs`` name action-selecting flags that pin a one-action-at-a-time
    subcommand to its query form (``git config --get``); their presence among
    literal, unguarded words de-escalates a non-allow effect to allow.
    ``guarded_keys`` state the inverse, for a subcommand whose writes are not
    all alike: their *absence* among legible words de-escalates, so the
    effect is kept only for the settings that redirect how commands execute.
    ``ask_refspecs`` states the ``ask_flags`` downgrade about an operand's
    grammar instead of a word's spelling, for a subcommand whose refspecs
    carry the same effects its flags do.
    """

    name: str
    effect: CommandEffect = ROOT_EFFECT
    ask_refspecs: list[RefspecEffect] = []
    ask_flags: list[str] = []
    read_verbs: list[str] = []
    guarded_keys: list[str] = []
    operations: list[ShellOperationRule] = []
    sandbox: SandboxPlacement = ROOT_SANDBOX
    checkpoint: CheckpointRequirement = ROOT_CHECKPOINT
    reviewer: ReviewerRequirement = ROOT_REVIEWER
    effect_class: EffectClass | None = None
    reason: str = ""

    def declared(self) -> DeclaredAxes:
        """The axes this subcommand states itself, leaving the rest to inherit."""
        supplied = self.model_fields_set
        return DeclaredAxes(
            effect=self.effect if "effect" in supplied else None,
            sandbox=self.sandbox if "sandbox" in supplied else None,
            checkpoint=self.checkpoint if "checkpoint" in supplied else None,
            reviewer=self.reviewer if "reviewer" in supplied else None,
            effect_class=(
                self.effect_class if "effect_class" in supplied else None
            ),
        )


class ShellCommandRule(SelectableRule, frozen=True):
    """One executable — a read-only tool, or a subcommand-gated command.

    Selectable by its executable name, which is also what the kernel matches
    on, so a project replacing ``git`` replaces exactly the rule that would
    have judged ``git`` and leaves no second rule under that name for a walk
    to reach first.

    On a subcommand-gated command, ``value_flags`` name the global options that
    consume the following word (``git -C <path>``) so the value is never read
    as the subcommand, and ``ask_flags`` guard dangerous globals in that same
    pre-subcommand position (``git -c``). ``allow_flags`` declare the pure
    read-only form of a non-allow command: the row de-escalates to allow only
    when every argument is exactly one of the named flags (``ssh-add -l``).
    ``read_verbs`` do the same for a command whose read-only form still takes
    operands, so no all-flags test can recognize it (``nc -z host port``): a
    declared verb among otherwise literal, unguarded words pins the action.

    ``sandbox`` is the other axis, declared here rather than inferred by a
    renderer: it says where an invocation matched by this rule has to run,
    whatever effect the rule reaches. Reads that need a remote take
    ``outside`` and run unprompted; writes that need one take ``outside``
    beside an ``ask``, so the approval says both things at once. A command
    that usually belongs inside but sometimes has to leave takes
    ``escalable``, which confines it and lets the agent making the call take
    it out — one field says every one of these, so a rule that permits the
    outside never has a second way to say it.
    """

    name: str
    default_effect: CommandEffect
    ask_flags: list[str] = []
    allow_flags: list[str] = []
    read_verbs: list[str] = []
    write_markers: list[str] = []
    """Argument prefixes whose *absence* makes this command read-only.

    Every other de-escalation here is a positive test: some word has to be
    present for the rule to relax. A few commands are the other way round --
    `dd` writes only when handed an `of=`, and with no `of=` it is a plain
    read of `if=` to stdout. There is no verb to list, because the read-only
    form is the one with nothing extra in it, so a membership test can never
    recognize it and every such invocation stopped for approval as a write.
    """
    guarded_keys: list[str] = []
    """Setting names whose *absence* makes this command's write an ordinary one.

    The same absence test as `write_markers`, asked about a write's subject
    instead of its form. That one asks whether a command writes at all; this
    assumes it does and asks whether what it writes decides how later
    commands execute. `git config` is the case: it can set `user.email` or it
    can set `core.hooksPath`, and only the second arranges for a program to
    run. A row without this can only hold one effect over both, which makes
    its reason -- "git config can change how commands execute" -- false for
    nearly every invocation it stops, and an approval question whose stated
    reason does not hold is one nobody can weigh.

    Glob patterns, matched case-blind. Git reads a key's section and name
    without regard to case, so a guard written `core.hookspath` has to catch
    `core.hooksPath`, and the families worth naming are shaped around a
    subsection the caller chooses (`merge.*.driver`).
    """
    bare_reads: bool = False
    """Whether this command only reads when handed no arguments at all.

    The one case `write_markers` cannot reach. That recognizes a reading form
    by the marker it lacks, which still needs a word to examine; `mount` reads
    in the form that has no words, and every form that acts names a device or
    a mountpoint. So the emptiness itself is the whole signal.

    Declared per command rather than derived, because a bare invocation is an
    action for plenty of commands and nothing in the row's shape says which:
    `ssh-add` with nothing after it adds the default key.
    """
    value_flags: list[str] = []
    subcommands: list[ShellSubcommandRule] = []
    sandbox: SandboxPlacement = ROOT_SANDBOX
    checkpoint: CheckpointRequirement = ROOT_CHECKPOINT
    reviewer: ReviewerRequirement = ROOT_REVIEWER
    effect_class: EffectClass | None = None
    reason: str = ""

    def selection_id(self) -> str:
        return self.name

    def declared(self) -> DeclaredAxes:
        """The axes this command states itself, leaving the rest to inherit."""
        supplied = self.model_fields_set
        return DeclaredAxes(
            effect=self.default_effect,
            sandbox=self.sandbox if "sandbox" in supplied else None,
            checkpoint=self.checkpoint if "checkpoint" in supplied else None,
            reviewer=self.reviewer if "reviewer" in supplied else None,
            effect_class=(
                self.effect_class if "effect_class" in supplied else None
            ),
        )


def erase_runner_targets(targets: list[RunnerTargetRule]) -> list[RunnerTargetRow]:
    """Flatten the declared runner targets into the kernel's primitive rows."""
    return [
        RunnerTargetRow(
            name=target.name,
            sandbox=target.sandbox,
            effect=target.effect,
            reason=target.reason,
        )
        for target in targets
    ]


def runner_target_tables(targets: list[RunnerTargetRule]) -> list[ShellRuleRow]:
    """The verb tables of every target that declares one, as command rows.

    A target with subcommands is a command table wearing a runner target's
    name, so it is erased as one and matched by the walk that already reads
    those rows. Targets without subcommands contribute nothing here and keep
    their single verdict on the runner row.
    """
    return erase_shell_rules(
        [
            ShellCommandRule(
                name=target.name,
                default_effect=target.effect,
                subcommands=target.subcommands,
                sandbox=target.sandbox,
                reason=target.reason,
            )
            for target in targets
            if target.subcommands
        ]
    )


def rule_id(command: str, subcommand: str = "", operation: str = "") -> str:
    """The stable id of the row matching these levels.

    Derived from what the row matches rather than declared beside it, so a
    renamed subcommand renames its id and no second place has to be kept in
    step. The ``shell:`` prefix is what keeps it distinguishable from an edit
    or fetch rule in a single audit table.
    """
    return "shell:" + ".".join(part for part in (command, subcommand, operation) if part)


def erase_shell_rules(rules: list[ShellCommandRule]) -> list[ShellRuleRow]:
    """Flatten the nested table into the kernel's primitive command rows.

    Each row carries its match levels, its flag lists, its reason, and both
    axes already resolved against every level above it, so the kernel matching
    one row has the whole answer and never composes anything. An empty string
    at a level means "the default at that level". A command contributes one
    default row plus, per subcommand, one row per operation and a
    subcommand-default row for the bare form.

    Resolving here rather than at decision time is what keeps the canonical
    policy and every generated dispatcher from disagreeing about what a level
    inherited: they read the same rows, so there is nothing left to disagree
    about.
    """

    def subcommand_rows(
        command_name: str, subcommand: ShellSubcommandRule, above: ResolvedAxes
    ) -> list[ShellRuleRow]:
        axes = above.inherit(subcommand.declared(), "subcommand")
        operations = [
            ShellRuleRow(
                rule=rule_id(command_name, subcommand.name, operation.name),
                command=command_name,
                subcommand=subcommand.name,
                operation=operation.name,
                ask_refspecs=[],
                ask_flags=list(operation.ask_flags),
                allow_flags=[],
                read_verbs=[],
                write_markers=[],
                guarded_keys=[],
                bare_reads=False,
                value_flags=[],
                reason=operation.reason,
                **axes.inherit(operation.declared(), "operation").row_fields(),
            )
            for operation in subcommand.operations
        ]
        default = ShellRuleRow(
            rule=rule_id(command_name, subcommand.name),
            command=command_name,
            subcommand=subcommand.name,
            operation="",
            ask_refspecs=list(subcommand.ask_refspecs),
            ask_flags=list(subcommand.ask_flags),
            allow_flags=[],
            read_verbs=list(subcommand.read_verbs),
            write_markers=[],
            guarded_keys=list(subcommand.guarded_keys),
            bare_reads=False,
            value_flags=[],
            reason=subcommand.reason,
            **axes.row_fields(),
        )
        return [*operations, default]

    def command_rows(command: ShellCommandRule) -> list[ShellRuleRow]:
        axes = ROOT_AXES.inherit(command.declared(), "command")
        default = ShellRuleRow(
            rule=rule_id(command.name),
            command=command.name,
            subcommand="",
            operation="",
            ask_refspecs=[],
            ask_flags=list(command.ask_flags),
            allow_flags=list(command.allow_flags),
            read_verbs=list(command.read_verbs),
            write_markers=list(command.write_markers),
            guarded_keys=list(command.guarded_keys),
            bare_reads=command.bare_reads,
            value_flags=list(command.value_flags),
            reason=command.reason,
            **axes.row_fields(),
        )
        nested = [
            row
            for subcommand in command.subcommands
            for row in subcommand_rows(command.name, subcommand, axes)
        ]
        return [default, *nested]

    return [row for command in rules for row in command_rows(command)]
