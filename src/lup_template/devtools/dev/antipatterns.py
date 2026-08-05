"""Audit repository source for missing and spurious `# lup: ignore` markers.

Backs `lup-devtools dev check --antipatterns` (and the standalone
`dev check`-row). Walks every tracked or untracked `.py`/TS-family file and
runs the single `lup.codescan.antipatterns` set over it — the same set the
edit hook enforces — reporting three classes the hook cannot catch after the
fact:

- **missing**: a line trips a rule but carries no `# lup: ignore` covering it
  (it slipped in past the hook, or predates the rule). Blocking.
- **spurious**: a `# lup: ignore[id]` (or a bare one) guards a rule the line
  does not trip — a dead directive to delete. Blocking.
- **untyped**: a bare `# lup: ignore` validly silences a line but names no
  rule. Advisory (does not fail the check) — surfaced so the migration to
  typed `# lup: ignore[id]` directives is gradual.

The set is shared with the hook; the verdicts need not be. This sweep reads
whole parseable files, so it hands `lup.codescan.grammar` a type oracle and
decides some rules more narrowly than a hook judging an untyped edit fragment
ever could. Every finding that narrowing drops is reported as a **refuted**
row carrying the declaration that settled it, and the directive that used to
guard it turns up as spurious on the next line of the report.
"""

from collections import Counter, defaultdict
from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict

from lup.codescan.antipatterns import (
    AntiPattern,
    AntiPatternFinding,
    audit_text,
    patterns_for_suffix,
)
from lup.codescan.capabilities import audit_capabilities
from lup.codescan.boundaries import audit_path_boundaries
from lup.codescan.common import PythonSource, Refutation, module_name
from lup.codescan.grammar import refute
from lup.codescan.registry import RULE_REFERENCE
from lup.policy.kernel.roles import path_role
from lup.policy.kernel.rows import PathRoleRow
from lup_template.devtools.dev.pyright_oracle import default_oracle
from lup_template.devtools.harness.catalog import portable_harness
from lup_template.devtools.harness.composition import application_roots
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


class FoundRefutation(Refutation):
    """A :class:`~lup.codescan.common.Refutation` tagged with its file."""

    file: str


class ScannedFile(BaseModel):
    """One tracked file the sweep reads once and audits against its table."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rel: str
    path: Path
    patterns: list[AntiPattern]
    text: str


class AntiPatternScan(BaseModel):
    """One repository sweep: the findings it kept, and the ones it refuted."""

    findings: list[FoundAntiPattern]
    refuted: list[FoundRefutation]


def scan_antipatterns() -> AntiPatternScan:
    """Every missing/spurious marker across tracked production `.py`/TS files.

    The audit reads the same declared path roles the edit hook does, so a rule
    the hook never enforces in a test or scratch tree is not reported there
    either. A gate that fires only after the fact is a gate agents cannot act
    on.

    The typed grammar resolves receivers before the tables run, so a finding
    a type oracle proved the rule is not about never reaches a verdict — and
    a `# lup: ignore` that guarded one becomes the dead directive the audit
    reports. Resolution costs a language-server session and `dev check` pays
    it every run; where the checker is absent the grammar refutes nothing and
    every broad regex verdict stands.
    """
    roles = declared_path_roles()
    scanned: list[ScannedFile] = []
    sources: list[PythonSource] = []
    for rel in git.lines("ls-files", "--cached", "--others", "--exclude-standard"):
        path = Path(rel)
        patterns = patterns_for_suffix(path.suffix.lower())
        if patterns is None or path_role(rel, roles) != "production":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned.append(ScannedFile(rel=rel, path=path, patterns=patterns, text=text))
        if path.suffix.lower() in {".py", ".pyi"}:
            sources.append(PythonSource(path=path, module=module_name(path), text=text))

    refuted = refute(sources, default_oracle())
    results = [
        FoundAntiPattern(file=item.rel, **finding.model_dump())
        for item in scanned
        for finding in audit_text(
            item.text,
            item.patterns,
            refuted[item.path.as_posix()] if item.path.as_posix() in refuted else None,
        )
    ]
    results.extend(
        FoundAntiPattern(
            file=finding.path.as_posix(),
            kind=finding.kind,
            line=finding.line,
            text="",
            message=finding.message,
            rule_id=finding.rule_id,
        )
        for finding in audit_capabilities(sources)
    )
    roots = application_roots()
    boundary_findings = [
        (source.path, finding)
        for source in sources
        for finding in audit_path_boundaries(source.path, source.text, roots)
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
    return AntiPatternScan(
        findings=results,
        refuted=[
            FoundRefutation(file=file, **refutation.model_dump())
            for file, refutations in sorted(refuted.items())
            for refutation in refutations
        ],
    )


ADVISORY_KINDS = {"untyped"}


def summarize(as_json: bool) -> None:
    """Tally anti-pattern findings by rule and kind — the sweep triage view.

    A per-rule count (most-frequent first, with how many files each spans) and
    a per-kind split, so a cleanup targets the noisiest rules first instead of
    reading the whole listing, plus how many findings the typed grammar
    refuted. ``--json`` emits the same tally for tooling.
    """
    scan = scan_antipatterns()
    found = scan.findings
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
                "refuted": len(scan.refuted),
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
    if scan.refuted:
        typer.echo(f"  refuted by receiver type: {len(scan.refuted)}")
    typer.echo(f"Rule reference: {RULE_REFERENCE} (`uv run lup-devtools dev rules`)")


def report(as_json: bool) -> None:
    """List anti-pattern findings; exit non-zero when a blocking one remains.

    "untyped" findings are advisory (a bare `# lup: ignore` to migrate to a
    typed one) and never fail the command; "missing" and "spurious" do. Every
    finding the typed grammar refuted is listed with the declaration that
    settled it, so a dropped verdict is accountable rather than invisible.
    """
    scan = scan_antipatterns()
    found = scan.findings
    blocking = [finding for finding in found if finding.kind not in ADVISORY_KINDS]
    if as_json:
        output_json(
            {
                "findings": [finding.model_dump() for finding in found],
                "refuted": [refutation.model_dump() for refutation in scan.refuted],
            }
        )
        if blocking:
            raise typer.Exit(1)
        return
    for refutation in scan.refuted:
        typer.echo(
            f"{refutation.file}:{refutation.line} [refuted {refutation.rule_id}] "
            f"{refutation.evidence}"
        )
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
