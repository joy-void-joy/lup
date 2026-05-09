"""Merge conflict assessment and audit.

Mechanical helpers for ``/lup:merge-conflict``.

Examples::

    $ uv run lup-devtools conflict status
    $ uv run lup-devtools conflict status --json
    $ uv run lup-devtools conflict audit src/lup/agent/core.py --json
    $ uv run lup-devtools conflict complete
    $ uv run lup-devtools conflict complete --dry-run
"""

import logging
import re
from typing import Annotated

import sh
import typer
from pydantic import BaseModel

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)

git = sh.Command("git").bake("--no-pager")


class ConflictStatusResult(BaseModel):
    operation: str
    conflicted_files: list[str]
    ours_ref: str
    theirs_ref: str
    ours_commits: list[str]
    theirs_commits: list[str]


class FileAuditResult(BaseModel):
    path: str
    ours_removals: list[str]
    theirs_removals: list[str]
    warning: bool


class AuditResult(BaseModel):
    files: list[FileAuditResult]
    has_warnings: bool


SIGNIFICANT_PATTERN = re.compile(
    r"^-(def |class |async def |@app\.|@[a-z]+_tool|    def )"
)


def detect_operation() -> str:
    """Detect if we're in a merge, rebase, or cherry-pick."""
    git_dir = str(git("rev-parse", "--git-dir")).strip()

    from pathlib import Path
    gd = Path(git_dir)

    if (gd / "MERGE_HEAD").exists():
        return "merge"
    if (gd / "rebase-merge").is_dir() or (gd / "rebase-apply").is_dir():
        return "rebase"
    if (gd / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    return "none"


def list_conflicted_files() -> list[str]:
    output = str(
        git("diff", "--name-only", "--diff-filter=U", _ok_code=[0, 1])
    ).strip()
    return [f for f in output.splitlines() if f]


def extract_removals(diff_output: str) -> list[str]:
    """Find removed functions/classes/decorators in a diff."""
    removals: list[str] = []
    for line in diff_output.splitlines():
        if SIGNIFICANT_PATTERN.match(line):
            removals.append(line.lstrip("-").strip())
    return removals


@app.command("status")
def status_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Detect conflict state, list files, and show both sides' history."""
    operation = detect_operation()

    if operation == "none":
        if as_json:
            result = ConflictStatusResult(
                operation="none",
                conflicted_files=[],
                ours_ref="HEAD",
                theirs_ref="",
                ours_commits=[],
                theirs_commits=[],
            )
            print(result.model_dump_json(indent=2))
        else:
            typer.echo("No merge/rebase/cherry-pick in progress")
        return

    conflicts = list_conflicted_files()

    ours_ref = "HEAD"
    theirs_ref = "MERGE_HEAD" if operation == "merge" else "CHERRY_PICK_HEAD"

    ours_commits: list[str] = []
    theirs_commits: list[str] = []

    if operation == "merge":
        try:
            merge_base = str(
                git("merge-base", "HEAD", "MERGE_HEAD", _ok_code=[0])
            ).strip()
            ours_raw = str(
                git("log", "--oneline", f"{merge_base}..HEAD", _ok_code=[0])
            ).strip()
            ours_commits = [line for line in ours_raw.splitlines() if line][:10]

            theirs_raw = str(
                git("log", "--oneline", f"{merge_base}..MERGE_HEAD", _ok_code=[0])
            ).strip()
            theirs_commits = [line for line in theirs_raw.splitlines() if line][:10]
        except sh.ErrorReturnCode:
            pass

    result = ConflictStatusResult(
        operation=operation,
        conflicted_files=conflicts,
        ours_ref=ours_ref,
        theirs_ref=theirs_ref,
        ours_commits=ours_commits,
        theirs_commits=theirs_commits,
    )

    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        typer.echo(f"Operation: {operation}")
        typer.echo(f"Conflicted files ({len(conflicts)}):")
        for f in conflicts:
            typer.echo(f"  {f}")
        if ours_commits:
            typer.echo(f"\nOurs ({ours_ref}):")
            for c in ours_commits:
                typer.echo(f"  {c}")
        if theirs_commits:
            typer.echo(f"\nTheirs ({theirs_ref}):")
            for c in theirs_commits:
                typer.echo(f"  {c}")


@app.command("audit")
def audit_cmd(
    files: Annotated[
        list[str],
        typer.Argument(help="Files to audit for accidental deletions"),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Post-resolution deletion audit: check for accidentally dropped code."""
    operation = detect_operation()
    if operation == "none":
        typer.echo("No merge/rebase/cherry-pick in progress", err=True)
        raise typer.Exit(1)

    theirs_ref = "MERGE_HEAD" if operation == "merge" else "CHERRY_PICK_HEAD"

    file_results: list[FileAuditResult] = []
    for path in files:
        ours_diff = str(
            git("diff", "HEAD", "--", path, _ok_code=[0, 1])
        ).strip()
        ours_removals = extract_removals(ours_diff)

        theirs_diff = ""
        try:
            theirs_diff = str(
                git("diff", theirs_ref, "--", path, _ok_code=[0, 1])
            ).strip()
        except sh.ErrorReturnCode:
            pass
        theirs_removals = extract_removals(theirs_diff)

        has_warning = bool(ours_removals or theirs_removals)
        file_results.append(FileAuditResult(
            path=path,
            ours_removals=ours_removals,
            theirs_removals=theirs_removals,
            warning=has_warning,
        ))

    result = AuditResult(
        files=file_results,
        has_warnings=any(f.warning for f in file_results),
    )

    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        for f in file_results:
            status = "WARNING" if f.warning else "OK"
            typer.echo(f"  {f.path}: {status}")
            for r in f.ours_removals:
                typer.echo(f"    - [ours] {r}")
            for r in f.theirs_removals:
                typer.echo(f"    - [theirs] {r}")

        if result.has_warnings:
            typer.echo("\nSome files have removals — review before completing.")


@app.command("complete")
def complete_cmd(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would happen"),
    ] = False,
) -> None:
    """Finalize the merge/rebase/cherry-pick after all conflicts are resolved."""
    operation = detect_operation()
    if operation == "none":
        typer.echo("No merge/rebase/cherry-pick in progress")
        return

    remaining = list_conflicted_files()
    if remaining:
        typer.echo(f"Error: {len(remaining)} conflicted file(s) remain:", err=True)
        for f in remaining:
            typer.echo(f"  {f}", err=True)
        raise typer.Exit(1)

    match operation:
        case "merge":
            cmd_desc = "git commit --no-edit"
        case "rebase":
            cmd_desc = "git rebase --continue"
        case "cherry-pick":
            cmd_desc = "git cherry-pick --continue"
        case _:
            typer.echo(f"Error: unknown operation {operation!r}", err=True)
            raise typer.Exit(1)

    if dry_run:
        typer.echo(f"Would run: {cmd_desc}")
        return

    try:
        match operation:
            case "merge":
                git("commit", "--no-edit")
            case "rebase":
                git("rebase", "--continue")
            case "cherry-pick":
                git("cherry-pick", "--continue")
        typer.echo(f"Completed {operation}")
    except sh.ErrorReturnCode as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        typer.echo(f"Failed to complete {operation}: {stderr}", err=True)
        raise typer.Exit(1)
