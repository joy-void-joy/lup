"""Unified pre-flight checks: ruff, pyright, pytest."""

import sh
import typer

from lup_template.devtools.utils import git, uv


def run_checks(fix: bool, no_test: bool) -> None:
    """Run ruff format, ruff check, pyright, and pytest in sequence.

    Read-only by default (reports issues without modifying files).
    Pass *fix* to auto-fix formatting and lint issues.
    """
    results: list[tuple[str, bool]] = []

    # ruff format
    try:
        if not fix:
            uv("run", "ruff", "format", "--check", ".")
            typer.echo("ruff format: ok")
        else:
            uv("run", "ruff", "format", ".")
            typer.echo("ruff format: applied")
        results.append(("ruff format", True))
    except sh.ErrorReturnCode as e:
        typer.echo("ruff format: FAIL")
        if e.stdout:
            typer.echo(e.stdout.decode().rstrip())
        results.append(("ruff format", False))

    # ruff check
    try:
        args = ["run", "ruff", "check", "."]
        if fix:
            args.append("--fix")
        uv(*args)
        typer.echo("ruff check: ok")
        results.append(("ruff check", True))
    except sh.ErrorReturnCode as e:
        typer.echo("ruff check: FAIL")
        if e.stdout:
            typer.echo(e.stdout.decode().rstrip())
        results.append(("ruff check", False))

    if fix:
        modified = str(git("diff", "--name-only", _ok_code=[0])).strip()
        if modified:
            count = len(modified.splitlines())
            typer.echo(f"  auto-fixed {count} file(s)")
            for f in modified.splitlines()[:10]:
                typer.echo(f"    {f}")

    # pyright
    try:
        uv("run", "pyright")
        typer.echo("pyright: ok")
        results.append(("pyright", True))
    except sh.ErrorReturnCode as e:
        typer.echo("pyright: FAIL")
        if e.stdout:
            typer.echo(e.stdout.decode().rstrip())
        results.append(("pyright", False))

    # pytest
    if not no_test:
        try:
            uv("run", "pytest")
            typer.echo("pytest: ok")
            results.append(("pytest", True))
        except sh.ErrorReturnCode as e:
            typer.echo("pytest: FAIL")
            if e.stdout:
                typer.echo(e.stdout.decode().rstrip())
            results.append(("pytest", False))

    # summary
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    typer.echo(f"\n{passed}/{total} checks passed")

    if any(not ok for _, ok in results):
        failed = [name for name, ok in results if not ok]
        typer.echo(f"Failed: {', '.join(failed)}")
        raise typer.Exit(1)
