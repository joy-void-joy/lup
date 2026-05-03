"""Conflict scope classification for merge/rebase conflicts.

After a failed merge or rebase, classifies conflicted files as in-scope
(touched by this branch) or out-of-scope (only changed on the other side).

Examples::

    $ uv run lup-devtools dev conflicts
    $ uv run lup-devtools dev conflicts --json
"""

import json
from pathlib import Path
from typing import TypedDict

import sh
import typer


class ConflictFile(TypedDict):
    path: str
    conflict_count: int
    scope: str
    branch_touched: bool


class ConflictReport(TypedDict):
    state: str
    base: str
    files: list[ConflictFile]
    in_scope_count: int
    out_of_scope_count: int


def find_git_dir() -> Path:
    """Locate the .git directory (works in worktrees too)."""
    git = sh.Command("git")
    return Path(str(git("rev-parse", "--git-dir")).strip())


def detect_conflict_state() -> str | None:
    """Detect whether we're in a merge, rebase, or cherry-pick."""
    git_dir = find_git_dir()
    if (git_dir / "MERGE_HEAD").exists():
        return "merge"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "rebase"
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    return None


def get_branch_files(state: str) -> tuple[str, set[str]]:
    """Return (merge_base, files touched by this branch) for scope classification."""
    git = sh.Command("git")
    git_dir = find_git_dir()

    match state:
        case "merge":
            merge_head = str(git("rev-parse", "MERGE_HEAD")).strip()
            base = str(git("merge-base", "HEAD", merge_head)).strip()
            files_output = str(
                git("diff", "--name-only", f"{base}..HEAD", _ok_code=[0])
            ).strip()

        case "rebase":
            rebase_merge = git_dir / "rebase-merge"
            rebase_apply = git_dir / "rebase-apply"
            if rebase_merge.exists():
                onto = (rebase_merge / "onto").read_text().strip()
                orig_head = (rebase_merge / "head").read_text().strip()
            elif rebase_apply.exists():
                onto = (rebase_apply / "onto").read_text().strip()
                orig_head = (rebase_apply / "orig-head").read_text().strip()
            else:
                typer.echo("Cannot determine rebase state", err=True)
                raise typer.Exit(1)
            base = str(git("merge-base", orig_head, onto)).strip()
            files_output = str(
                git("diff", "--name-only", f"{base}..{orig_head}", _ok_code=[0])
            ).strip()

        case "cherry-pick":
            cherry_head = str(git("rev-parse", "CHERRY_PICK_HEAD")).strip()
            base = str(git("merge-base", "HEAD", cherry_head)).strip()
            files_output = str(
                git("diff", "--name-only", f"{base}..HEAD", _ok_code=[0])
            ).strip()

        case _:
            typer.echo(f"Unknown conflict state: {state}", err=True)
            raise typer.Exit(1)

    files = set(files_output.splitlines()) if files_output else set()
    return base, files


def list_conflicted_files() -> list[str]:
    """List files with unresolved conflicts."""
    git = sh.Command("git")
    output = str(git("diff", "--name-only", "--diff-filter=U", _ok_code=[0])).strip()
    if not output:
        return []
    return output.splitlines()


def count_conflict_markers(path: str) -> int:
    """Count the number of conflict marker blocks in a file."""
    try:
        content = Path(path).read_text(encoding="utf-8")
        return content.count("<<<<<<<")
    except OSError:
        return 0


def build_conflict_report(state: str) -> ConflictReport:
    """Build a structured conflict scope report."""
    conflicted = list_conflicted_files()
    base, branch_files = get_branch_files(state)

    files: list[ConflictFile] = []
    in_scope = 0
    out_of_scope = 0

    for path in conflicted:
        touched = path in branch_files
        scope = "in-scope" if touched else "out-of-scope"
        markers = count_conflict_markers(path)

        if touched:
            in_scope += 1
        else:
            out_of_scope += 1

        files.append(
            {
                "path": path,
                "conflict_count": markers,
                "scope": scope,
                "branch_touched": touched,
            }
        )

    return {
        "state": state,
        "base": base,
        "files": files,
        "in_scope_count": in_scope,
        "out_of_scope_count": out_of_scope,
    }


def conflicts(as_json: bool) -> None:
    """Show conflicted files with scope classification."""
    state = detect_conflict_state()
    if not state:
        typer.echo("Not in a merge, rebase, or cherry-pick state", err=True)
        raise typer.Exit(1)

    conflicted = list_conflicted_files()
    if not conflicted:
        typer.echo("No conflicted files found")
        return

    report = build_conflict_report(state)

    if as_json:
        typer.echo(json.dumps(report, indent=2))
        return

    typer.echo(f"\nConflict state: {report['state']}")
    typer.echo(f"Merge base: {report['base'][:10]}")
    typer.echo(f"\n{'File':<50} {'Conflicts':>10} {'Scope':>15}")
    typer.echo("-" * 78)

    for f in report["files"]:
        typer.echo(f"{f['path']:<50} {f['conflict_count']:>10} {f['scope']:>15}")

    typer.echo(
        f"\nIn-scope: {report['in_scope_count']}, "
        f"Out-of-scope: {report['out_of_scope_count']}"
    )
