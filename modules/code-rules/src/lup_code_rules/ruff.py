"""ruff's findings, read from its JSON as lup's own findings are, so an `ignore` keeps either alike.

ruff runs from the worktree's root, so its configuration there applies, with
`--force-exclude`, so a file its configuration excludes is left out even when
named, as a check of the whole worktree leaves it out (`docs/field-notes.md`,
*Tools*). It fixes nothing here: the gate's `--fix` does.
"""

from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from lup import Program
from lup.types import Model
from lup_code_rules.errors import LupCodeRulesError
from lup_code_rules.reports import Finding, Position, Span


class Located(Model):
    """A place in ruff's report: its row and column, each counted from 1."""

    row: int
    column: int


class Fix(Model):
    """A fix ruff offers, and whether it changes what the code does."""

    applicability: Literal["safe", "unsafe", "display-only"]


class Reported(Model):
    """One finding, as `ruff check --output-format json` reports it."""

    code: str | None
    """Its rule's code (`SLF001`), or `invalid-syntax` for code that doesn't
    parse; none from an older ruff, for the same."""
    message: str
    filename: str
    location: Located
    end_location: Located
    fix: Fix | None = None

    def finding(self, root: Path) -> Finding:
        """Return it as a finding, its path from `root`."""
        return Finding(
            path=Path(self.filename).relative_to(root).as_posix(),
            span=Span(
                start=Position(line=self.location.row, column=self.location.column),
                end=Position(
                    line=self.end_location.row, column=self.end_location.column
                ),
            ),
            owner="ruff",
            rule=self.code or "invalid-syntax",
            message=self.message,
            fixable=self.fix is not None and self.fix.applicability == "safe",
        )


async def ruff_findings(
    ruff: Program,
    root: Path,
    paths: list[str],
    content: str | None = None,
    config: Path | None = None,
) -> list[Finding]:
    """Return ruff's findings in `paths`, from the worktree at `root`: each file as it stands on disk, or, for the one path given with `content`, as that content.

    ruff reads its settings where it finds them from `root`, or from `config`
    where it's given, run from the directory `config` is in, which its
    relative settings (`src`) are read from. Raise `LupCodeRulesError` where
    ruff fails rather than reporting.
    """
    if not paths:
        return []
    named = [str(root / each) for each in paths]
    standing = (
        ["--stdin-filename", named[0], "-"] if content is not None else ["--", *named]
    )
    ran = await ruff.ran(
        "check",
        "--output-format",
        "json",
        "--force-exclude",
        "--no-fix",
        "--exit-zero",
        *(["--config", str(config)] if config is not None else []),
        *standing,
        given=content,
        cwd=root if config is None else config.parent,
    )
    if ran.status != 0:
        message = f"ruff failed, ending with status {ran.status}: {ran.said()}"
        raise LupCodeRulesError(message)
    try:
        reported = TypeAdapter(list[Reported]).validate_json(ran.output)
    except ValidationError as unread:
        message = f"ruff answered what lup can't read: {unread}"
        raise LupCodeRulesError(message) from unread
    return [each.finding(root) for each in reported]
