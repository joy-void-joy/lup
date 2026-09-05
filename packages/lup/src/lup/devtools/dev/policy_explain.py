"""Ask the live permission policy what it would decide, and why.

Tuning a vocabulary against a session's actual friction needs the verdict for
a spelling, not a reading of the table that produces it: the shell classifier
recurses through substitutions, loops, and redirections, resolves paths
against the filesystem, and consults four declared row sets, so which of them
answered is rarely obvious from the command alone.

This runs the same composition a session runs — ``semantic_policy_for`` over
the project's own ``HookSet`` — so a verdict here is the verdict there rather
than an approximation of it. The generated dispatchers reach the identical
kernel through their own compiled halves, which is why one answer covers both
the in-process session and the native plugin.
"""

import json
from pathlib import Path

import typer
from pydantic import AnyHttpUrl, BaseModel

from lup.devtools.utils import output_json
from lup.harness.enforcement import measured_containment, semantic_policy_for
from lup.harness.models import HookSet
from lup.policy.kernel.lex import shell_write_targets
from lup.policy.models import EditBatch, EditChange, FetchUrl, ShellCommand
from lup.policy.shell_rules import ShellCommandRule
from lup.policy.survey import classify_forms, survey_shell_rules
from lup.types import StringMap

# Open keys only by spelling: the effects are lup's own closed set, but this
# reads them off a verdict rather than matching on them, so a caller may add
# a colour for an effect a later policy introduces.
EFFECT_STYLES: StringMap = {
    "allow": typer.colors.GREEN,
    "ask": typer.colors.YELLOW,
    "defer": typer.colors.BLUE,
    "deny": typer.colors.RED,
}
"""How each verdict reads at a glance, for a caller that does not say."""


class Placement(BaseModel, frozen=True):
    """One placement a subject is read under, and the flag it sets."""

    name: str
    sandboxed: bool


PLACEMENTS: list[Placement] = [
    Placement(name="sandboxed", sandboxed=True),
    Placement(name="unsandboxed", sandboxed=False),
]
"""Both placements, rather than whichever this process happens to be in.

Placement is the single fact that moves the most verdicts -- an unclassified
command is settled by containment inside and refused outside -- so a reader
given one answer has to know which one they were given before they can use it,
and a reader given both never has to ask.
"""


class PolicyReading(BaseModel, frozen=True):
    """What one placement's answer is, and why."""

    placement: str
    effect: str
    reason: str


class PolicyVerdict(BaseModel, frozen=True):
    """One classified input, read under every placement that could move it."""

    input: str
    kind: str
    readings: list[PolicyReading]
    assumed: list[str] = []
    """Session facts every reading supplied itself, where they could move one."""

    def settled(self) -> bool:
        """Whether placement changes nothing here, so one line says it all."""
        return len({reading.effect for reading in self.readings}) == 1

    def allows_anywhere(self) -> bool:
        """Whether any placement permits this, which is what an exit code says."""
        return any(reading.effect == "allow" for reading in self.readings)


def unresolved_facts(subject: str, kind: str) -> list[str]:
    """Which session facts a reading of a bare command string had to assume.

    Only the ones that could move *this* subject. A line naming a fact that
    cannot reach the verdict teaches a reader to skip the line, which costs
    more than the line ever saves -- so a command that writes nothing says
    nothing, and the note appears exactly where the answer is soft.
    """
    if kind != "shell":
        return []
    targets = shell_write_targets(subject)
    if not targets:
        return []
    return [
        f"a capture holds {', '.join(targets)}",
        "every write target is inside what this launch mounted writable",
    ]


def read_under(
    subject: str,
    kind: str,
    placement: Placement,
    autonomous: bool,
    cwd: Path,
    hooks: HookSet,
) -> PolicyReading:
    """Classify one input under one placement's composition of the policy.

    The placement decides containment as well as the native sandbox, because
    the kernel joins them -- a boundary stands when either does -- and the
    launcher spells them with one flag: `--unsandboxed` opens on the host
    with no container *and* the runtime's own sandbox off. Read separately,
    the unsandboxed row inherited the container measured around this process
    and answered the bounded question twice, under two headings.

    Which is the reading a session is least able to notice and most likely to
    act on: the guidance sends an agent here before it spends a turn, from
    inside a contained session, to find out what happens without the
    boundary -- and got told what happens with it.
    """
    held = measured_containment(cwd)
    policy = semantic_policy_for(
        hooks,
        sandbox_active=placement.sandboxed,
        autonomous=autonomous,
        recovered=True,
        contained=held.contained and placement.sandboxed,
        inside_placement=held.inside_placement and placement.sandboxed,
    )
    match kind:
        case "shell":
            event = ShellCommand(command=subject, cwd=cwd)
        case "fetch":
            event = FetchUrl(url=AnyHttpUrl(subject))
        case _:
            event = EditBatch(
                changes=[EditChange(path=Path(subject), before=None, after="")]
            )
    decision = policy.decide(event)
    return PolicyReading(
        placement=placement.name, effect=decision.effect, reason=decision.reason
    )


def verdict_for(
    subject: str,
    kind: str,
    autonomous: bool,
    cwd: Path,
    hooks: HookSet,
    placements: list[Placement] = PLACEMENTS,
) -> PolicyVerdict:
    """Classify one input under every placement, rather than under one.

    ``edit`` is judged as a whole-file write of unchanged content, which is
    the shape that isolates the path gates from the anti-pattern and size
    ones: the question this command answers is whether a path may be written
    at all, not whether some particular diff passes review.

    Answering both placements is what makes the reading usable. Containment
    settles an unclassified command inside the boundary and refuses it outside,
    so a single answer is only as good as the reader's guess about which
    session it described -- and the guess is invisible, which is the worst
    property an answer can have.

    **What no placement resolves, it says.** A session measures two facts per
    command that no reader of a bare string can: which write targets fall
    outside what the launch mounted writable, and whether the snapshot in front
    of it succeeded. Both are answered optimistically here, because a reader
    asking what they will be asked about is better served by the common answer
    than by a pessimistic one they would learn to discount --
    :func:`unresolved_facts` names them beside the verdict instead.
    """
    return PolicyVerdict(
        input=subject,
        kind=kind,
        readings=[
            read_under(subject, kind, placement, autonomous, cwd, hooks)
            for placement in placements
        ],
        assumed=unresolved_facts(subject, kind),
    )


def chosen_placements(
    sandbox: bool | None, placements: list[Placement] = PLACEMENTS
) -> list[Placement]:
    """Which placements to read, given a caller who may have pinned one.

    ``None`` is both, which is the answer a reader wants and the default. A
    pinned flag narrows rather than switches, so the one thing a caller can ask
    for is a subset of what they would otherwise have been shown -- there is no
    setting under which this reports an answer the unpinned form would not.
    """
    if sandbox is None:
        return placements
    return [placement for placement in placements if placement.sandboxed == sandbox]


def explain(
    subjects: list[str],
    kind: str,
    autonomous: bool,
    as_json: bool,
    hooks: HookSet,
    sandbox: bool | None = None,
    styles: StringMap = EFFECT_STYLES,
) -> None:
    """Print every placement's verdict, exiting non-zero when none of them allow.

    A subject both placements agree on prints once, because repeating an answer
    to say it did not change is how a table teaches its reader to stop reading
    it. One that differs prints both, which is the case the reader came for.
    """
    root = Path.cwd()
    verdicts = [
        verdict_for(subject, kind, autonomous, root, hooks, chosen_placements(sandbox))
        for subject in subjects
    ]
    if as_json:
        output_json([verdict.model_dump() for verdict in verdicts])
        if not any(verdict.allows_anywhere() for verdict in verdicts):
            raise typer.Exit(1)
        return
    for verdict in verdicts:
        shown = verdict.readings[:1] if verdict.settled() else verdict.readings
        head = " / ".join(
            typer.style(reading.effect, fg=styles[reading.effect], bold=True)
            for reading in shown
        )
        typer.echo(f"{head}  {verdict.input}")
        for reading in shown:
            label = "" if verdict.settled() else f"{reading.placement}: "
            typer.echo(f"       {label}{reading.reason}")
        for assumed in verdict.assumed:
            typer.echo(f"       assuming {assumed}")
    if not any(verdict.allows_anywhere() for verdict in verdicts):
        raise typer.Exit(1)


def survey(
    rules: list[ShellCommandRule],
    as_json: bool,
    output: Path | None,
    provenance: bool,
) -> None:
    """Print every command form the shell vocabulary declares, and its verdict.

    Reshaping a table is where verdicts move without anybody deciding to move
    them, so ``output`` exists to capture the whole table before a change and
    diff it against the same capture after — an equality no reading of the
    rules can establish.

    ``provenance`` answers the other question, one row per rule rather than one
    per form: which level of the nesting supplied each axis, so a verdict that
    was inherited from three levels up says so instead of being re-derived.
    """
    lines = (
        [rule.provenance() for rule in survey_shell_rules(rules)]
        if provenance
        else [
            json.dumps(form.model_dump(), sort_keys=True)
            if as_json
            else f"{form.effect:>5} {form.sandbox:>7}  {form.command}"
            for form in classify_forms(rules)
        ]
    )
    if output is None:
        for line in lines:
            typer.echo(line)
        return
    output.write_text("\n".join([*lines, ""]), encoding="utf-8")
    typer.echo(f"{len(lines)} line(s) written: {output}")
