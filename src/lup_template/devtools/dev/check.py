"""Unified pre-flight checks: ruff, pyright, pytest."""

import sh
import typer
from pydantic import BaseModel

from lup.codescan.markers import find_feedback

from lup_template.devtools.dev.antipatterns import scan_antipatterns
from lup_template.devtools.dev.boundaries import scan_boundaries
from lup_template.devtools.dev.comments import FoundComment, scan_tracked
from lup_template.devtools.utils import git, uv


class CheckOutcome(BaseModel):
    """One pre-flight check's name and whether it passed."""

    name: str
    passed: bool


def comments_gate_lines(found: list[FoundComment]) -> list[str]:
    """The comments gate's FAIL header and detail lines.

    Deferred notes keep the gate red — committed parked work stays visible
    pressure — but their `deferred[<wake condition>]` lines render after the
    unresolved ones, so the red is legible at a glance.
    """
    unresolved = [comment for comment in found if comment.kind != "defer"]
    deferred = [comment for comment in found if comment.kind == "defer"]
    counts = f"{len(unresolved)} unresolved"
    if deferred:
        counts += f", {len(deferred)} deferred"
    lines = [f"claude comments: FAIL ({counts})"]
    lines.extend(
        f"  {comment.file}:{comment.start_line}-{comment.end_line}"
        for comment in unresolved
    )
    lines.extend(
        f"  deferred[{comment.condition}] "
        f"{comment.file}:{comment.start_line}-{comment.end_line}"
        for comment in deferred
    )
    return lines


def run_checks(fix: bool, no_test: bool) -> None:
    """Run ruff format, ruff check, pyright, and pytest in sequence.

    Read-only by default (reports issues without modifying files).
    Pass *fix* to auto-fix formatting and lint issues.
    """
    results: list[CheckOutcome] = []

    # ruff format
    try:
        if not fix:
            uv("run", "ruff", "format", "--check", ".")
            typer.echo("ruff format: ok")
        else:
            uv("run", "ruff", "format", ".")
            typer.echo("ruff format: applied")
        results.append(CheckOutcome(name="ruff format", passed=True))
    except sh.ErrorReturnCode as e:
        typer.echo("ruff format: FAIL")
        if e.stdout:
            typer.echo(e.stdout.decode().rstrip())
        results.append(CheckOutcome(name="ruff format", passed=False))

    # ruff check
    try:
        args = ["run", "ruff", "check", "."]
        if fix:
            args.append("--fix")
        uv(*args)
        typer.echo("ruff check: ok")
        results.append(CheckOutcome(name="ruff check", passed=True))
    except sh.ErrorReturnCode as e:
        typer.echo("ruff check: FAIL")
        if e.stdout:
            typer.echo(e.stdout.decode().rstrip())
        results.append(CheckOutcome(name="ruff check", passed=False))

    if fix:
        changed = git.lines("diff", "--name-only", _ok_code=[0])
        if changed:
            typer.echo(f"  auto-fixed {len(changed)} file(s)")
            for f in changed:
                typer.echo(f"    {f}")

    # pyright
    try:
        uv("run", "pyright")
        typer.echo("pyright: ok")
        results.append(CheckOutcome(name="pyright", passed=True))
    except sh.ErrorReturnCode as e:
        typer.echo("pyright: FAIL")
        if e.stdout:
            typer.echo(e.stdout.decode().rstrip())
        results.append(CheckOutcome(name="pyright", passed=False))

    # pytest
    if not no_test:
        try:
            uv("run", "pytest")
            typer.echo("pytest: ok")
            results.append(CheckOutcome(name="pytest", passed=True))
        except sh.ErrorReturnCode as e:
            typer.echo("pytest: FAIL")
            if e.stdout:
                typer.echo(e.stdout.decode().rstrip())
            results.append(CheckOutcome(name="pytest", passed=False))

    found = scan_tracked(find_feedback)
    if found:
        for line in comments_gate_lines(found):
            typer.echo(line)
        results.append(CheckOutcome(name="claude comments", passed=False))
    else:
        typer.echo("claude comments: ok")
        results.append(CheckOutcome(name="claude comments", passed=True))

    findings = scan_antipatterns()
    blocking = [f for f in findings if f.kind != "untyped"]
    if blocking:
        typer.echo(f"antipatterns: FAIL ({len(blocking)} finding(s))")
        for finding in blocking:
            typer.echo(f"  {finding.file}:{finding.line} [{finding.kind}]")
        results.append(CheckOutcome(name="antipatterns", passed=False))
    else:
        advisory = len(findings) - len(blocking)
        tail = f" ({advisory} untyped, advisory)" if advisory else ""
        typer.echo(f"antipatterns: ok{tail}")
        results.append(CheckOutcome(name="antipatterns", passed=True))

    breaches = scan_boundaries()
    if breaches:
        typer.echo(f"seam boundaries: FAIL ({len(breaches)} breach(es))")
        for breach in breaches:
            typer.echo(f"  {breach.file}:{breach.line}  {breach.module}")
        results.append(CheckOutcome(name="seam boundaries", passed=False))
    else:
        typer.echo("seam boundaries: ok")
        results.append(CheckOutcome(name="seam boundaries", passed=True))

    # summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    typer.echo(f"\n{passed}/{total} checks passed")

    failed = [r.name for r in results if not r.passed]
    if failed:
        typer.echo(f"Failed: {', '.join(failed)}")
        raise typer.Exit(1)
