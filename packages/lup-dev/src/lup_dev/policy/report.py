"""The reports the agent reads, in pyright's shape: `path:line:column - rule: message`.

lup's findings on the lines a call changed are told after it, each with its
steer, beside the type errors and ruff's findings, and those on lines no change
touched apart; none refuses (`docs/judging-writes.md`, *Findings*). A refusal
is a held change the operator declined or left unanswered, put back or never
written, with where the agent's version is saved; an approval, one the operator
approved, in a line saying lup held it for their review. A move of `HEAD` is
told as its commits', never put back.

A session hears about several worktrees, from any working directory, so every
report names each file by its absolute path, as pyright's command line does.
The texts name no runtime: each adapter carries them as its runtime hears them.
"""

from pathlib import Path

from lup.types import Model
from lup_dev.codescan.contract import Finding
from lup_dev.policy.judge import PRIVATE, Ask, RemovedNote


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
    """One held file the operator declined or left unanswered, put back or never written, its version saved."""

    path: Path
    """The file, by its absolute path."""
    saved: Path
    """Where the agent's version is saved, by its absolute path."""
    new: bool
    """Whether the file didn't exist before the change."""
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
    """Report the held files the operator declined or left unanswered, each with where the agent's version is saved."""
    if not refused:
        return ""
    count = len(refused)
    header = (
        "lup refused 1 file. It is unchanged; your version is saved."
        if count == 1
        else f"lup refused {count} files. They are unchanged; your versions are saved."
    )

    def block(one: Refused) -> str:
        comment = f": {one.declined}" if one.declined else "."
        declined = (
            [f"  The operator declined it{comment}"] if one.declined is not None else []
        )
        unanswered = (
            ["  Nobody answered in time; the hold stays open in the operator's inbox."]
            if one.unanswered
            else []
        )
        lines = [f"{one.path} (saved at {one.saved})", *declined, *unanswered]
        return "\n".join(lines)

    return sections([header, *(block(one) for one in refused)])


def approval(paths: list[Path], comment: str) -> str:
    """Tell a held change the operator approved, in one line: lup held it for their review, and they approved it, their comment after.

    It says nothing of how long they took: the agent needs to know the
    operator saw the change, not to pace itself on their time.

    >>> approval([Path("/work/AGENTS.md")], "")
    "lup held the write to /work/AGENTS.md for the operator's review, and they approved it."
    >>> approval([Path("/work/a.py"), Path("/work/b.py")], "keep it")
    "lup held the write to /work/a.py, /work/b.py for the operator's review, and they approved it: keep it"
    """
    named = ", ".join(str(path) for path in paths)
    said = f": {comment}" if comment else "."
    return f"lup held the write to {named} for the operator's review, and they approved it{said}"


def information(
    reported: list[Finding],
    findings: list[Finding],
    untouched: list[Finding],
    importers: list[Finding],
) -> str:
    """Report what a checkpoint found in the files it judged: values never published on the lines changed, lup's findings on them, type errors and ruff's findings, lup's findings elsewhere, and type errors in the files importing them.

    A value never published is told apart from a rule's finding, since no
    `ignore` keeps it: each names its kind, never the value.
    """
    private = [found for found in reported if found.rule == PRIVATE]
    elsewhere = [found for found in untouched if found.rule == PRIVATE]
    withheld = (
        [
            (
                "Values never published, on the lines changed (rewrite each before "
                "it's committed: the operator sees this write with them, the gate's "
                "`private` step fails on them, and a push or a post carrying one is "
                "refused):"
            ),
            *(line for found in private for line in finding_lines(found)),
        ]
        if private
        else []
    )
    rules = [found for found in reported if found.rule != PRIVATE]
    ruled = (
        [
            (
                "lup's findings on the lines changed (clear each, or keep it with "
                '`# lup: ignore("<rule>", why="<reason>")` on its line or the line '
                "above, which the operator is asked about; they fail the gate):"
            ),
            *(line for found in rules for line in finding_lines(found)),
        ]
        if rules
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
    others = [found for found in untouched if found.rule != PRIVATE]
    older = (
        [
            "lup's findings on lines no change touched (they fail the gate too):",
            *(line for found in others for line in finding_lines(found)),
        ]
        if others
        else []
    )
    kept = (
        [
            (
                "Values never published, on lines no change touched (the gate's "
                "`private` step fails on them too):"
            ),
            *(line for found in elsewhere for line in finding_lines(found)),
        ]
        if elsewhere
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
    return sections(
        ["\n".join(part) for part in [withheld, ruled, checked, older, kept, importing]]
    )


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
                    "The operator is asked about the rest after the fact, in their "
                    f"inbox (hold {move.hold})."
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
