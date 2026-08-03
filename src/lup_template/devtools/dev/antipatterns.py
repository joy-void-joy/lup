"""Audit repository source for missing and spurious `# lup: ignore` markers.

Backs `lup-devtools dev check --antipatterns` (and the standalone
`dev check`-row). Walks every tracked or untracked `.py`/TS-family file and runs the
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
from lup.codescan.capabilities import audit_capabilities, sources_from_paths
from lup.codescan.boundaries import audit_path_boundaries
from lup.codescan.registry import RULE_REFERENCE
from lup.policy.kernel.roles import path_role
from lup.policy.kernel.rows import PathRoleRow
from lup_template.devtools.harness.catalog import portable_harness
from lup_template.devtools.utils import git, output_json


def declared_path_roles() -> list[PathRoleRow]:
    """The path roles this repository's hook set declares."""
    hooks = portable_harness().plugins[0].hooks
    if hooks is None:
        return []
    return [
        PathRoleRow(root=role.root.as_posix(), role=role.role)
        for role in hooks.path_roles
    ]


class FoundAntiPattern(AntiPatternFinding):
    """An :class:`~lup.codescan.antipatterns.AntiPatternFinding` tagged with its file."""

    file: str


def scan_antipatterns() -> list[FoundAntiPattern]:
    """Every missing/spurious marker across tracked production `.py`/TS files.

    The audit reads the same declared path roles the edit hook does, so a rule
    the hook never enforces in a test or scratch tree is not reported there
    either. A gate that fires only after the fact is a gate agents cannot act
    on.
    """
    roles = declared_path_roles()
    results: list[FoundAntiPattern] = []  # lup: ignore[empty-collection] — scan fold
    python_paths: list[Path] = []
    for rel in git.lines("ls-files", "--cached", "--others", "--exclude-standard"):
        path = Path(rel)
        patterns = patterns_for_suffix(path.suffix.lower())
        if patterns is None or path_role(rel, roles) != "production":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.suffix.lower() in {".py", ".pyi"}:
            python_paths.append(path)
        for finding in audit_text(text, patterns):
            results.append(FoundAntiPattern(file=rel, **finding.model_dump()))
    for finding in audit_capabilities(sources_from_paths(python_paths)):
        results.append(
            FoundAntiPattern(
                file=finding.path.as_posix(),
                kind=finding.kind,
                line=finding.line,
                text="",
                message=finding.message,
                rule_id=finding.rule_id,
            )
        )
    boundary_findings = [
        (path, finding)
        for path in python_paths
        for finding in audit_path_boundaries(path, path.read_text(encoding="utf-8"))
    ]
    foreign_untyped = {
        (path.as_posix(), finding.line)
        for path, finding in boundary_findings
        if finding.kind == "untyped"
    }
    results = [
        finding
        for finding in results
        if not (
            finding.kind == "spurious"
            and not finding.rule_id
            and (finding.file, finding.line) in foreign_untyped
        )
    ]
    results.extend(
        FoundAntiPattern(
            file=path.as_posix(),
            kind=finding.kind,
            line=finding.line,
            text=finding.text,
            message=finding.message,
            rule_id=finding.rule_id,
        )
        for path, finding in boundary_findings
    )
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
    typer.echo(f"Rule reference: {RULE_REFERENCE} (`uv run lup-devtools dev rules`)")


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
    typer.echo(f"Rule reference: {RULE_REFERENCE} (`uv run lup-devtools dev rules`)")
    if blocking:
        raise typer.Exit(1)
