"""Audit tracked source for missing and spurious `# claude: ignore` markers.

Backs `lup-devtools dev check --antipatterns` (and the standalone
`dev check`-row). Walks every git-tracked `.py`/TS-family file and runs the
single `lup.antipatterns` set over it — the same set the edit hook enforces —
reporting two classes the hook cannot catch after the fact:

- **missing**: a line trips an anti-pattern but carries no `# claude: ignore`
  (it slipped in past the hook, or predates the pattern).
- **spurious**: an inline `# claude: ignore` guards a line that trips nothing
  (a dead marker to delete).
"""

from pathlib import Path

import typer

from lup.antipatterns import AntiPatternFinding, audit_text, patterns_for_suffix
from lup_template.devtools.utils import git, output_json


class FoundAntiPattern(AntiPatternFinding):
    """An :class:`~lup.antipatterns.AntiPatternFinding` tagged with its file."""

    file: str


def scan_antipatterns() -> list[FoundAntiPattern]:
    """Every missing/spurious marker across tracked `.py`/TS-family files."""
    results: list[FoundAntiPattern] = []
    for rel in str(git("ls-files")).splitlines():
        path = Path(rel)
        patterns = patterns_for_suffix(path.suffix.lower())
        if patterns is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for finding in audit_text(text, patterns):
            results.append(FoundAntiPattern(file=rel, **finding.model_dump()))
    return results


def report(as_json: bool) -> None:
    """List anti-pattern findings; exit non-zero when any remain."""
    found = scan_antipatterns()
    if as_json:
        output_json([finding.model_dump() for finding in found])
        if found:
            raise typer.Exit(1)
        return
    if not found:
        typer.echo("No anti-pattern findings.")
        return
    for finding in found:
        typer.echo(f"{finding.file}:{finding.line} [{finding.kind}] {finding.message}")
        typer.echo(f"    {finding.text}")
    files = {finding.file for finding in found}
    typer.echo(f"\n{len(found)} finding(s) in {len(files)} file(s)")
    raise typer.Exit(1)
