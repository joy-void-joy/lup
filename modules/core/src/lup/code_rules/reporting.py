"""A check's findings, said as lines a reader acts on: lup's first, since they're about design, then pyright's and ruff's, then what the gate's `--fix` fixes, then what's listed without failing.

Each finding is a line, `path:line:column - lup tuple-shape: what it saw`, its
path from the worktree's root. A rule of lup's says its mistake and steer under
the first of its findings, and the line alone after, since repeated they bury
what's new (`README.md` here, *What a check says*).
"""

from typing import TYPE_CHECKING

from lup.code_rules.checking import Checked, Table
from lup.code_rules.reports import Finding
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Iterator


def line(finding: Finding) -> str:
    """Return a finding's line: where it is, who found it, its rule, and what it saw.

    >>> from lup.code_rules.reports import Position, Span
    >>> at = Span(start=Position(line=3, column=12), end=Position(line=3, column=27))
    >>> line(
    ...     Finding(
    ...         path="a.py",
    ...         span=at,
    ...         owner="lup",
    ...         rule="tuple-shape",
    ...         message="`tuple[str, int]` is a tuple type. A tuple's positions…",
    ...         detail="`tuple[str, int]` is a tuple type",
    ...     )
    ... )
    'a.py:3:12 - lup tuple-shape: `tuple[str, int]` is a tuple type'
    """
    start = finding.span.start
    said = finding.detail or finding.message
    return f"{finding.path}:{start.line}:{start.column} - {finding.owner} {finding.rule}: {said}"


class Report(Model):
    """What a check found in the files it checked, to be said."""

    checked: list[Checked]
    table: Table

    def everything(self) -> list[Finding]:
        """Return every finding standing, file after file."""
        return [each for file in self.checked for each in file.standing]

    def failing(self) -> list[Finding]:
        """Return what fails the gate: every finding standing but a heuristic's guesses."""
        return [each for file in self.checked for each in file.failing()]

    def text(self) -> str:
        """Return what the check found, a section for each kind of finding, or that it found nothing."""
        everything = self.everything()
        designs = [
            each
            for each in everything
            if each.owner == "lup" and each.category != "heuristic" and not each.fixable
        ]
        checks = [
            each for each in everything if each.owner != "lup" and not each.fixable
        ]
        fixable = [each for each in everything if each.fixable]
        listed = [each for each in everything if each.category == "heuristic"]
        sections = [
            self.section(
                "lup's findings (keep one with "
                '`# lup: ignore("<rule>", why="<reason>")` on its line or alone '
                "above it)",
                designs,
                explained=True,
            ),
            self.section("pyright's and ruff's findings", checks),
            self.section("fixed by `lup gate check --fix`", fixable),
            self.section(
                "listed, not failing: guesses over prose, to read again", listed
            ),
        ]
        said = [each for each in sections if each]
        if not said:
            files = len(self.checked)
            return f"No findings in {files} file{'' if files == 1 else 's'}."
        return "\n\n".join(said)

    def section(
        self, title: str, findings: list[Finding], *, explained: bool = False
    ) -> str:
        """Return a section of findings under `title`, each rule's mistake and steer under its first where `explained`; nothing where there are none."""
        if not findings:
            return ""
        first = {each.rule: at for at, each in reversed(list(enumerate(findings)))}

        def said() -> Iterator[str]:
            """Yield each finding's line, and its rule's mistake and steer under the first of its rule's where `explained`."""
            for at, finding in enumerate(findings):
                yield f"  {line(finding)}"
                if not explained or first[finding.rule] != at:
                    continue
                rule = self.table.rules.get(finding.rule)
                yield f"      {rule.mistake if rule else finding.message}"
                steer = rule.steer if rule else finding.steer
                if steer:
                    yield f"      steer: {steer}"

        return "\n".join([f"{title}:", *said()])
