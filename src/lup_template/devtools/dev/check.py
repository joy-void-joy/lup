"""Unified pre-flight checks: ruff, pyright, pytest."""

import sh
import typer
from pydantic import BaseModel

from lup.adapters.harness import claude_prompt_renderer, codex_prompt_renderer
from lup.codescan.markers import find_feedback
from lup.harness.models import GUIDANCE_CHARACTER_BUDGET

from lup_template.devtools.dev.antipatterns import scan_antipatterns
from lup_template.devtools.dev.boundaries import (
    scan_boundaries,
    scan_library_placement,
)
from lup_template.devtools.dev.branches import unlanded_siblings
from lup_template.devtools.dev.comments import FoundComment, scan_tracked
from lup_template.devtools.harness.content.guidance import DOCUMENT as GUIDANCE
from lup_template.devtools.utils import git, uv

# The suite waits on git subprocesses and hook scripts far more than it
# computes, so it parallelizes well — but each worker pays a full interpreter
# boot and package import, and past roughly this many that startup costs more
# than the concurrency returns. `-n auto` on a large host is slower than serial
# arithmetic suggests, so the count is bounded rather than derived from cores.
TEST_WORKERS = 8


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


def changed_paths(since: str) -> list[str]:
    """Every tracked path this tree changed since a ref, as posix strings."""
    named = sh.Command("git")("diff", "--name-only", since, _ok_code=list(range(256)))
    return [line for line in str(named).splitlines() if line]


def owned_comments(
    found: list[FoundComment], scope: list[str] | None
) -> list[FoundComment]:
    """Which unresolved notes this check is answerable for.

    A resolver worker's own notes are already cleared from its worktree
    before it starts, so every note it can still see belongs to a sibling
    concern it has no lease on. Gating the whole tree would fail it for work
    it cannot touch; gating what it changed asks the only question it can
    answer, which is whether it left a note in its own code.
    """
    if scope is None:
        return found
    owned = dict.fromkeys(scope)
    return [item for item in found if str(item.file) in owned]


def run_checks(fix: bool, no_test: bool, scope: list[str] | None = None) -> None:
    """Run ruff format, ruff check, pyright, and pytest in sequence.

    Read-only by default (reports issues without modifying files).
    Pass *fix* to auto-fix formatting and lint issues. ``scope`` narrows the
    note and anti-pattern gates to paths this tree is answerable for.
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
            uv("run", "pytest", "-n", str(TEST_WORKERS))
            typer.echo("pytest: ok")
            results.append(CheckOutcome(name="pytest", passed=True))
        except sh.ErrorReturnCode as e:
            typer.echo("pytest: FAIL")
            if e.stdout:
                typer.echo(e.stdout.decode().rstrip())
            results.append(CheckOutcome(name="pytest", passed=False))

    found = owned_comments(scan_tracked(find_feedback), scope)
    if found:
        for line in comments_gate_lines(found):
            typer.echo(line)
        results.append(CheckOutcome(name="claude comments", passed=False))
    else:
        typer.echo("claude comments: ok")
        results.append(CheckOutcome(name="claude comments", passed=True))

    scan = scan_antipatterns()
    blocking = [f for f in scan.findings if f.kind != "untyped"]
    refined = f", {len(scan.refuted)} refuted" if scan.refuted else ""
    if blocking:
        typer.echo(f"antipatterns: FAIL ({len(blocking)} finding(s){refined})")
        for finding in blocking:
            typer.echo(f"  {finding.file}:{finding.line} [{finding.kind}]")
        results.append(CheckOutcome(name="antipatterns", passed=False))
    else:
        advisory = len(scan.findings) - len(blocking)
        tail = f" ({advisory} untyped, advisory{refined})" if advisory else refined
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

    tables = scan_library_placement()
    if tables:
        typer.echo(f"library placement: FAIL ({len(tables)} baked-in table(s))")
        for table in tables:
            typer.echo(f"  {table.file}:{table.line}  {table.module}")
        results.append(CheckOutcome(name="library placement", passed=False))
    else:
        typer.echo("library placement: ok")
        results.append(CheckOutcome(name="library placement", passed=True))

    used = max(
        len(claude_prompt_renderer().render(GUIDANCE)),
        len(codex_prompt_renderer().render(GUIDANCE)),
    )
    free = GUIDANCE_CHARACTER_BUDGET - used
    state = "ok" if free >= 0 else f"FAIL (over by {-free})"
    typer.echo(
        f"guidance budget: {state} — {used}/{GUIDANCE_CHARACTER_BUDGET}"
        f" characters, {free} free"
    )
    results.append(CheckOutcome(name="guidance budget", passed=free >= 0))

    # advisory — reports another tree's state, so it never gates this one
    unlanded = unlanded_siblings()
    if unlanded:
        typer.echo(f"unlanded siblings: {len(unlanded)} (advisory)")
        for branch in unlanded:
            typer.echo(
                f"  {branch.name}  {branch.unique_commits} commits, "
                f"{branch.source_diff_lines} ln"
            )

    # summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    typer.echo(f"\n{passed}/{total} checks passed")

    failed = [r.name for r in results if not r.passed]
    if failed:
        typer.echo(f"Failed: {', '.join(failed)}")
        raise typer.Exit(1)
