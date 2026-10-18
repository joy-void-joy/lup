"""The reports the agent reads, in pyright's shape: `path:line:column - rule: message`.

lup's findings on the lines a call changed are told after it, each with its
steer, beside the type errors and ruff's findings, and those on lines no change
touched apart; none refuses (`docs/judging-writes.md`, *Findings*). A refusal is
a change put back that the operator had to see first: one made through the
shell where the runtime asks before a call, or a hold declined or unanswered,
with where the agent's version is saved. A move of `HEAD` is told as its
commits', never put back.

A session hears about several worktrees, from any working directory, so every
report names each file by its absolute path, as pyright's command line does.
The texts name no runtime: each adapter carries them as its runtime hears them.
"""

from pathlib import Path
from typing import Literal

from lup.types import Model
from lup_dev.codescan.contract import Finding
from lup_dev.policy.judge import Ask, RemovedNote


def placed(root: Path, findings: list[Finding]) -> list[Finding]:
    """Name each finding's file by its absolute path, from the worktree at `root`.

    >>> from lup_dev.codescan.contract import Position, Span
    >>> at = Position(line=1, column=1)
    >>> found = Finding(path=Path("a.py"), span=Span(start=at, end=at), owner="ruff",
    ...     rule="E501", message="too long")
    >>> [each.path for each in placed(Path("/work"), [found])]
    [PosixPath('/work/a.py')]
    """
    return [found.model_copy(update={"path": root / found.path}) for found in findings]


class Refused(Model):
    """One file put back before the operator saw it, its version saved: changed through the shell where they'd be asked, or held and declined or unanswered."""

    path: Path
    """The file, by its absolute path."""
    saved: Path
    """Where the agent's version is saved, by its absolute path."""
    new: bool
    """Whether the file didn't exist before the change."""
    bypassed: list[Ask] = []
    """Asks made through the shell, which come back through the file tools."""
    declined: str | None = None
    """The operator's comment on a declined hold; empty when they gave none."""
    unanswered: bool = False
    """Whether it was held and nobody answered in time."""


def finding_lines(finding: Finding, indent: str = "  ") -> list[str]:
    """Spell one finding as pyright does, with lup's steer beneath it.

    >>> from lup_dev.codescan.contract import Position, Span
    >>> at = Position(line=41, column=12)
    >>> found = Finding(path=Path("a.py"), span=Span(start=at, end=at), owner="lup",
    ...     rule="tuple-shape", message="a tuple hides its fields", steer="a model")
    >>> finding_lines(found)
    ['  a.py:41:12 - tuple-shape: a tuple hides its fields', '      steer: a model']
    """
    start = finding.span.start
    place = f"{finding.path}:{start.line}:{start.column}"
    said = f"{indent}{place} - {finding.rule}: {finding.message}"
    steer = [f"{indent}    steer: {finding.steer}"] if finding.steer else []
    return [said, *steer]


def sections(parts: list[str]) -> str:
    """Join the non-empty parts of a report, a blank line between each."""
    return "\n\n".join(part for part in parts if part)


def refusal(refused: list[Refused]) -> str:
    """Report the files put back before the operator saw them, and how to bring each back."""
    if not refused:
        return ""
    count = len(refused)
    header = (
        "lup refused 1 file. It is unchanged; your version is saved."
        if count == 1
        else f"lup refused {count} files. They are unchanged; your versions are saved."
    )

    def block(one: Refused) -> str:
        through = "  Made through the shell, so it comes back through your file tools"
        bypassed = [f"{through}: {ask.reason}" for ask in one.bypassed]
        comment = f": {one.declined}" if one.declined else "."
        declined = (
            [f"  The operator declined it{comment}"] if one.declined is not None else []
        )
        unanswered = (
            ["  Nobody answered in time; the hold stays open (`lup-dev holds`)."]
            if one.unanswered
            else []
        )
        lines = [
            f"{one.path} (saved at {one.saved})",
            *bypassed,
            *declined,
            *unanswered,
        ]
        return "\n".join(lines)

    through_tools = [one for one in refused if one.bypassed]
    tools = (
        [
            (
                "Make these changes with your file tools, which ask the operator, "
                "not through the shell:"
            ),
            *(f"  {one.path} (from {one.saved})" for one in through_tools),
        ]
        if through_tools
        else []
    )
    return sections([header, *(block(one) for one in refused), "\n".join(tools)])


def information(
    reported: list[Finding],
    findings: list[Finding],
    untouched: list[Finding],
    importers: list[Finding],
) -> str:
    """Report what a checkpoint found in the files it judged: lup's findings on the lines changed, type errors and ruff's findings, lup's findings elsewhere, and type errors in the files importing them."""
    ruled = (
        [
            (
                "lup's findings on the lines changed (clear each, or keep it with "
                '`# lup: ignore("<rule>", why="<reason>")` on its line or the line '
                "above, which the operator is asked about; they fail the gate):"
            ),
            *(line for found in reported for line in finding_lines(found)),
        ]
        if reported
        else []
    )
    checked = (
        [
            (
                "Type errors and ruff's findings in the files changed "
                "(clean them before the turn ends):"
            ),
            *(line for found in findings for line in finding_lines(found)),
        ]
        if findings
        else []
    )
    older = (
        [
            "lup's findings on lines no change touched (they fail the gate too):",
            *(line for found in untouched for line in finding_lines(found)),
        ]
        if untouched
        else []
    )
    importing = (
        [
            (
                "Type errors in files that import what changed "
                "(clean them before the turn ends):"
            ),
            *(line for found in importers for line in finding_lines(found)),
        ]
        if importers
        else []
    )
    return sections(["\n".join(part) for part in [ruled, checked, older, importing]])


def removed_notes(notes: list[RemovedNote]) -> str:
    """Report the notes present when the session started that are gone since."""
    if not notes:
        return ""
    return "\n".join(
        [
            (
                "Notes present when the session started were removed; "
                "list them in your report and in the merge commit's message:"
            ),
            *(f"  {note.path}: # lup: {note.text}" for note in notes),
        ]
    )


class MovedFile(Model):
    """One file a move of `HEAD` brought, judged once as its commits'."""

    path: Path
    """The file, by its absolute path."""
    findings: list[Finding] = []
    """lup's findings on the lines its commits touched."""
    asks: list[Ask] = []
    removed: list[RemovedNote] = []
    """Notes it had before the move that its commits removed."""


class Moved(Model):
    """A move of `HEAD` whose commits brought content no checkpoint had judged."""

    worktree: Path
    head: str | None
    """The commit `HEAD` moved to; none where it names no commit."""
    files: list[MovedFile]
    hold: str | None = None
    """The hold asking the operator about it after the fact, if it asks."""


def moved(moves: list[Moved]) -> str:
    """Tell what moves of `HEAD` brought: judged once, and left as committed."""

    def one(move: Moved) -> str:
        told = [
            each for each in move.files if each.findings or each.asks or each.removed
        ]
        if not told:
            return ""
        files = [
            line
            for each in told
            for line in [
                str(each.path),
                *(line for found in each.findings for line in finding_lines(found)),
                *(f"  asks: {ask.reason}" for ask in each.asks),
                *(f"  removes the note: # lup: {note.text}" for note in each.removed),
            ]
        ]
        gate = (
            ["lup's findings in them fail the gate: fix them in a later commit."]
            if any(each.findings for each in told)
            else []
        )
        asked = (
            [
                (
                    "The operator is asked about the rest after the fact "
                    f"(hold {move.hold}, `lup-dev holds`)."
                )
            ]
            if move.hold
            else []
        )
        header = (
            f"HEAD moved to {move.head or 'no commit'} in {move.worktree}, bringing "
            "content no checkpoint judged. It was judged once, as its commits', "
            "and stays as committed:"
        )
        return "\n".join([header, *files, *gate, *asked])

    return sections([one(move) for move in moves])


def turn_end(findings: list[Finding]) -> str:
    """Say why the turn can't end: what's still wrong in the files it touched."""
    if not findings:
        return ""
    return "\n".join(
        [
            (
                "lup won't end the turn yet: files this conversation touched have "
                "lup's findings, type errors or ruff findings."
            ),
            *(line for found in findings for line in finding_lines(found)),
            (
                "Fix them, or keep one with "
                '`# lup: ignore("<rule>", why="<reason>")` '
                "on its line or the line above (the operator is asked)."
            ),
        ]
    )


def unheld(findings: list[Finding], why: Literal["working", "repeated"]) -> str:
    """Tell what's left in the files touched where it doesn't hold the turn's end.

    It doesn't in a file a subagent at work touched too (`working`), which may be
    its in progress, nor when the turn's end was held just before (`repeated`):
    an end following a hold ends, whatever's left.
    """
    if not findings:
        return ""
    match why:
        case "working":
            header = (
                "A subagent of this session at work touched these files too, so "
                "lup doesn't hold the turn's end on what's left in them "
                "(information; it holds once no subagent touching them is at work):"
            )
        case "repeated":
            header = (
                "lup held the turn's end once already, and lets it end. Left in "
                "files this conversation touched (information; they fail the gate "
                "until cleared, and hold no later turn's end unless they change):"
            )
    return "\n".join(
        [header, *(line for found in findings for line in finding_lines(found))]
    )


def asked(asks: list[Ask]) -> str:
    """Say what a change asks the operator, for the runtime's prompt.

    >>> asked([Ask(kind="new-file", reason="src/a.py is a new production file")])
    'lup asks: src/a.py is a new production file'
    """
    return f"lup asks: {'; '.join(ask.reason for ask in asks)}"


def judge_failed(failure: Exception) -> str:
    """Warn the operator that the judge failed at a turn's end, which ended anyway.

    >>> judge_failed(RuntimeError("the engine crashed")).startswith("lup's judge")
    True
    """
    return (
        f"lup's judge failed at a turn's end, so that end wasn't judged: {failure!r}. "
        "The turn ended, since the agent can't fix the judge: approving `dev`'s "
        "(`lup-dev trust`), or fixing what the error names, is yours. "
        "You're told once for each failure in a session."
    )
