"""Audit tracked source for missing and spurious `# lup: ignore` markers.

Backs `lup-devtools dev check --antipatterns` (and the standalone
`dev check`-row). Walks every git-tracked `.py`/TS-family file and runs the
single `lup.review.antipatterns` set over it — the same set the edit hook enforces —
reporting three classes the hook cannot catch after the fact:

- **missing**: a line trips a rule but carries no `# lup: ignore` covering it
  (it slipped in past the hook, or predates the rule). Blocking.
- **spurious**: a `# lup: ignore[id]` (or a bare one) guards a rule the line
  does not trip — a dead directive to delete. Blocking.
- **untyped**: a bare `# lup: ignore` validly silences a line but names no
  rule. Advisory (does not fail the check) — surfaced so the migration to
  typed `# lup: ignore[id]` directives is gradual.
"""

from pathlib import Path

import typer

from lup.review.antipatterns import AntiPatternFinding, audit_text, patterns_for_suffix
from lup_template.devtools.utils import git, output_json


class FoundAntiPattern(AntiPatternFinding):
    """An :class:`~lup.review.antipatterns.AntiPatternFinding` tagged with its file."""

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


ADVISORY_KINDS = {"untyped"}


def report(as_json: bool) -> None:
    """List anti-pattern findings; exit non-zero when a blocking one remains.

    "untyped" findings are advisory (a bare `# lup: ignore` to migrate to a
    typed one) and never fail the command; "missing" and "spurious" do.
    """
    found = scan_antipatterns()
    blocking = [finding for finding in found if finding.kind not in ADVISORY_KINDS]
    if as_json:
        output_json([finding.model_dump() for finding in found])
        if blocking:
            raise typer.Exit(1)
        return
    if not found:
        typer.echo("No anti-pattern findings.")
        return
    for finding in found:
        typer.echo(f"{finding.file}:{finding.line} [{finding.kind}] {finding.message}")
        typer.echo(f"    {finding.text}")
    files = {finding.file for finding in found}
    advisory = len(found) - len(blocking)
    tail = f" (+{advisory} untyped, advisory)" if advisory else ""
    typer.echo(f"\n{len(blocking)} blocking finding(s){tail} in {len(files)} file(s)")
    if blocking:
        raise typer.Exit(1)
