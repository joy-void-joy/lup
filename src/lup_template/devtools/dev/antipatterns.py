"""Audit tracked source for missing and spurious `# lup: ignore` markers.

Backs `lup-devtools dev check --antipatterns` (and the standalone
`dev check`-row). Walks every git-tracked `.py`/TS-family file and runs the
single `lup.codescan.antipatterns` set over it — the same set the edit hook enforces —
reporting three classes the hook cannot catch after the fact:

- **missing**: a line trips a rule but carries no `# lup: ignore` covering it
  (it slipped in past the hook, or predates the rule). Blocking.
- **spurious**: a `# lup: ignore[id]` (or a bare one) guards a rule the line
  does not trip — a dead directive to delete. Blocking.
- **untyped**: a bare `# lup: ignore` validly silences a line but names no
  rule. Advisory (does not fail the check) — surfaced so the migration to
  typed `# lup: ignore[id]` directives is gradual.
"""

from collections import Counter, defaultdict
from pathlib import Path

import typer

from lup.codescan.antipatterns import (
    AntiPatternFinding,
    audit_text,
    patterns_for_suffix,
)
from lup_template.devtools.utils import git, output_json


class FoundAntiPattern(AntiPatternFinding):
    """An :class:`~lup.codescan.antipatterns.AntiPatternFinding` tagged with its file."""

    file: str


def scan_antipatterns() -> list[FoundAntiPattern]:
    """Every missing/spurious marker across tracked `.py`/TS-family files."""
    results: list[FoundAntiPattern] = []  # lup: ignore[empty-collection] — scan fold
    for rel in git.lines("ls-files"):
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


def summarize(as_json: bool) -> None:
    """Tally anti-pattern findings by rule and kind — the sweep triage view.

    A per-rule count (most-frequent first, with how many files each spans) and
    a per-kind split, so a cleanup targets the noisiest rules first instead of
    reading the whole listing. ``--json`` emits the same tally for tooling.
    """
    found = scan_antipatterns()
    by_rule: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    files_by_rule: defaultdict[str, list[str]] = defaultdict(list)
    for finding in found:
        rule = finding.rule_id or "(bare)"
        by_rule[rule] += 1
        by_kind[finding.kind] += 1
        if finding.file not in files_by_rule[rule]:
            files_by_rule[rule].append(finding.file)

    blocking = sum(1 for finding in found if finding.kind not in ADVISORY_KINDS)
    file_count = len(dict.fromkeys(finding.file for finding in found))

    if as_json:
        output_json(
            {
                "total": len(found),
                "blocking": blocking,
                "files": file_count,
                "by_kind": dict(by_kind),
                "by_rule": {
                    rule: {"count": count, "files": len(files_by_rule[rule])}
                    for rule, count in by_rule.most_common()
                },
            }
        )
        return

    if not found:
        typer.echo("No anti-pattern findings.")
        return
    typer.echo(
        f"{len(found)} findings ({blocking} blocking) across {file_count} file(s)"
    )
    typer.echo("  by kind: " + ", ".join(f"{k}={v}" for k, v in by_kind.most_common()))
    typer.echo("  by rule:")
    for rule, count in by_rule.most_common():
        typer.echo(f"    {count:5}  {rule}  ({len(files_by_rule[rule])} file(s))")


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
