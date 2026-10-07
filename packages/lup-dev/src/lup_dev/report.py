"""The reports the agent reads, in pyright's shape: `path:line:column - rule: message`.

A refusal lists every finding in each refused file at once, so one pass fixes them
all, then says where the agent's version is saved and how to bring it back
(`docs/judging-writes.md`, *Refusals*). Information (type errors, ruff's findings,
lup's findings on untouched lines) comes in its own sections and never refuses.
The texts name no runtime: each adapter carries them as its runtime hears them.
"""

from pathlib import Path

from lup.types import Model
from lup_dev.checker import Finding
from lup_dev.judge import Ask, RemovedNote


class Refused(Model):
    """One file a judgement refused: put back, or never written, its version saved."""

    path: Path
    saved: Path
    """Where the agent's version is saved, relative to the worktree."""
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

    >>> from lup_dev.checker import Position, Span
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
