"""The reports the agent reads, in pyright's shape: `path:line:column - rule: message`.

A refusal lists every finding in each refused file at once, so one pass fixes them
all, then says where the agent's version is saved and how to bring it back
(`docs/judging-writes.md`, *Refusals*). Information (type errors, ruff's findings,
lup's findings on untouched lines) comes in its own sections and never refuses.
A move of `HEAD` is told as its commits', never put back.

A session hears about several worktrees, from any working directory, so every
report names each file by its absolute path, as pyright's command line does.
The texts name no runtime: each adapter carries them as its runtime hears them.
"""

from pathlib import Path

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
    """One file a judgement refused: put back, or never written, its version saved."""

    path: Path
    """The file, by its absolute path."""
    saved: Path
    """Where the agent's version is saved, by its absolute path."""
    new: bool
    """Whether the file didn't exist before the change."""
    refusing: list[Finding] = []
    untouched: list[Finding] = []
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
    """Report the refused files, every finding in each, and how to bring them back."""
    if not refused:
        return ""
    count = len(refused)
    header = (
        "lup refused 1 file. It is unchanged; your version is saved."
        if count == 1
        else f"lup refused {count} files. They are unchanged; your versions are saved."
    )

    def block(one: Refused) -> str:
        untouched = (
            [
                "  On lines this change didn't touch, which don't refuse:",
                *(
                    line
                    for found in one.untouched
                    for line in finding_lines(found, "    ")
                ),
            ]
            if one.untouched
            else []
        )
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
            *(line for found in one.refusing for line in finding_lines(found)),
            *untouched,
            *bypassed,
            *declined,
            *unanswered,
        ]
        return "\n".join(lines)

    moved = [
        one for one in refused if one.refusing and not one.new and not one.bypassed
    ]
    rewritten = [
        one for one in refused if one.refusing and one.new and not one.bypassed
    ]
    through_tools = [one for one in refused if one.bypassed]
    move = (
        [
            "Fix these lines in the saved copy, then move it into place:",
            *(f"  mv {one.saved} {one.path}" for one in moved),
        ]
        if moved
        else []
    )
    rewrite = (
        [
            (
                "Fix the saved copy, then write the file again with your file tool, "
                "where the operator sees it whole:"
            ),
            *(f"  {one.path} (from {one.saved})" for one in rewritten),
        ]
        if rewritten
        else []
    )
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
    keep = (
        [
            (
                "To keep a finding, add on its line or the line above "
                "(the operator is asked):"
            ),
            '  # lup: ignore("<rule>", why="<reason>")',
        ]
        if any(one.refusing for one in refused)
        else []
    )
    footer = "\n".join([*move, *rewrite, *tools, *keep])
    return sections([header, *(block(one) for one in refused), footer])


def information(
    findings: list[Finding], untouched: list[Finding], importers: list[Finding]
) -> str:
    """Report what's information, not refusal, about the files a checkpoint judged."""
    checked = (
        [
            (
                "Type errors and ruff's findings in the files changed "
                "(information; clean them before the turn ends):"
            ),
            *(line for found in findings for line in finding_lines(found)),
        ]
        if findings
        else []
    )
    older = (
        [
            "lup's findings on lines no change touched (information):",
            *(line for found in untouched for line in finding_lines(found)),
        ]
        if untouched
        else []
    )
    importing = (
        [
            (
                "Type errors in files that import what changed "
                "(information; clean them before the turn ends):"
            ),
            *(line for found in importers for line in finding_lines(found)),
        ]
        if importers
        else []
    )
    return sections(["\n".join(checked), "\n".join(older), "\n".join(importing)])


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
    """Say why the turn can't end: what's still wrong in the files touched."""
    if not findings:
        return ""
    return "\n".join(
        [
            (
                "lup won't end the turn yet: files touched this session have "
                "type errors or ruff findings."
            ),
            *(line for found in findings for line in finding_lines(found)),
            (
                "Fix them, or keep one with "
                '`# lup: ignore("<rule>", why="<reason>")` '
                "on its line or the line above (the operator is asked)."
            ),
        ]
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
        "The turn ended, since the agent can't fix the judge: reinstalling it from "
        "`dev` (`lup-dev install`), or fixing what the error names, is yours. "
        "You're told once for each failure in a session."
    )
