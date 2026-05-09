"""Branch inventory and cleanup.

Mechanical helpers for ``/lup:clean-gone``.

Examples::

    $ uv run lup-devtools branch survey
    $ uv run lup-devtools branch survey --json
    $ uv run lup-devtools branch delete feat-old
    $ uv run lup-devtools branch delete feat-old --dry-run --force
"""

import json
import logging
from typing import Annotated

import sh
import typer
from pydantic import BaseModel

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)

git = sh.Command("git").bake("--no-pager")
gh = sh.Command("gh")


def detect_integration_branch() -> str:
    """Return 'dev' if it exists locally, else 'main'."""
    try:
        git("rev-parse", "--verify", "refs/heads/dev")
        return "dev"
    except sh.ErrorReturnCode:
        return "main"


class PRStatus(BaseModel):
    number: int
    title: str
    state: str
    merged_at: str | None


class BranchInfo(BaseModel):
    name: str
    commit: str
    tracking: str | None
    worktree: str | None
    is_current: bool
    contained_in: list[str]
    pr: PRStatus | None
    unique_commits: int
    source_diff_lines: int


class SurveyResult(BaseModel):
    integration_branch: str
    current_branch: str
    branches: list[BranchInfo]


def parse_branches() -> list[dict[str, str | bool]]:
    """Parse ``git branch -vv`` into structured data."""
    output = str(git("branch", "-vv")).strip()
    results: list[dict[str, str | bool]] = []

    for line in output.splitlines():
        is_current = line.startswith("*")
        line = line.lstrip("* ").strip()
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue

        name = parts[0]
        commit = parts[1]
        tracking: str | None = None

        if len(parts) > 2:
            rest = parts[2]
            if rest.startswith("["):
                bracket_end = rest.find("]")
                if bracket_end != -1:
                    tracking_info = rest[1:bracket_end]
                    tracking = tracking_info.split(":")[0].strip()

        results.append({
            "name": name,
            "commit": commit,
            "tracking": tracking or "",
            "is_current": is_current,
        })

    return results


def parse_worktrees() -> dict[str, str]:
    """Map branch name → worktree path from ``git worktree list --porcelain``."""
    output = str(git("worktree", "list", "--porcelain")).strip()
    mapping: dict[str, str] = {}
    current_path = ""

    for line in output.splitlines():
        if line.startswith("worktree "):
            current_path = line.split(" ", 1)[1]
        elif line.startswith("branch refs/heads/"):
            branch_name = line.split("refs/heads/", 1)[1]
            mapping[branch_name] = current_path

    return mapping


def build_containment(branch_names: list[str]) -> dict[str, list[str]]:
    """For each branch, find which other branches contain it."""
    containment: dict[str, list[str]] = {b: [] for b in branch_names}

    for branch in branch_names:
        for target in branch_names:
            if branch == target:
                continue
            try:
                git("merge-base", "--is-ancestor", branch, target)
                containment[branch].append(target)
            except sh.ErrorReturnCode:
                pass

    return containment


def fetch_pr_status(branch_names: list[str]) -> dict[str, PRStatus]:
    """Query GitHub for PR status of branches."""
    mapping: dict[str, PRStatus] = {}
    try:
        raw = str(
            gh("pr", "list", "--state", "all", "--limit", "200",
               "--json", "number,title,headRefName,state,mergedAt")
        ).strip()
        prs = json.loads(raw)
        for pr in prs:
            ref = pr.get("headRefName", "")
            if ref in branch_names:
                mapping[ref] = PRStatus(
                    number=pr["number"],
                    title=pr.get("title", ""),
                    state=pr.get("state", ""),
                    merged_at=pr.get("mergedAt"),
                )
    except sh.ErrorReturnCode as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        logger.warning("Failed to fetch PR status: %s", stderr)

    return mapping


def count_unique_commits(branch: str, integration: str) -> int:
    """Count commits on branch not cherry-picked into integration."""
    try:
        output = str(
            git("rev-list", "--count", "--cherry-pick", "--left-only",
                f"{branch}...{integration}", _ok_code=[0])
        ).strip()
        return int(output)
    except (sh.ErrorReturnCode, ValueError):
        return -1


def count_source_diff_lines(branch: str, integration: str) -> int:
    """Count lines of source-file diff between branch and integration."""
    try:
        output = str(
            git("diff", "--stat", branch, integration,
                "--", "src/", ".claude/", "tests/", _ok_code=[0, 1])
        ).strip()
        if not output:
            return 0
        last_line = output.splitlines()[-1]
        parts = last_line.split(",")
        total = 0
        for part in parts:
            part = part.strip()
            for word in ("insertion", "deletion"):
                if word in part:
                    tokens = part.split()
                    if tokens and tokens[0].isdigit():
                        total += int(tokens[0])
        return total
    except sh.ErrorReturnCode:
        return -1


@app.command("survey")
def survey_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Collect branch, worktree, PR, and containment data."""
    if not as_json:
        typer.echo("Fetching and pruning remote...", err=True)
    git("fetch", "--prune")

    integration = detect_integration_branch()
    cur = str(git("branch", "--show-current")).strip()

    raw_branches = parse_branches()
    worktrees = parse_worktrees()
    branch_names = [str(b["name"]) for b in raw_branches]
    containment = build_containment(branch_names)

    if not as_json:
        typer.echo("Querying PR status...", err=True)
    pr_map = fetch_pr_status(branch_names)

    branches: list[BranchInfo] = []
    for b in raw_branches:
        name = str(b["name"])
        contained_in = containment.get(name, [])
        is_contained = bool(contained_in)
        pr_merged = name in pr_map and pr_map[name].state == "MERGED"

        if is_contained or pr_merged:
            unique = 0
            diff_lines = 0
        else:
            unique = count_unique_commits(name, integration)
            diff_lines = count_source_diff_lines(name, integration)

        branches.append(BranchInfo(
            name=name,
            commit=str(b["commit"]),
            tracking=str(b["tracking"]) or None,
            worktree=worktrees.get(name),
            is_current=bool(b["is_current"]),
            contained_in=contained_in,
            pr=pr_map.get(name),
            unique_commits=unique,
            source_diff_lines=diff_lines,
        ))

    result = SurveyResult(
        integration_branch=integration,
        current_branch=cur,
        branches=branches,
    )

    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        typer.echo(f"\nIntegration: {integration} | Current: {cur}\n")
        typer.echo(f"{'Branch':<25} {'Commit':<10} {'Contained In':<25} {'PR':<20} {'Unique':<8} {'Diff'}")
        typer.echo("-" * 100)
        for b in branches:
            contained = ", ".join(b.contained_in[:3]) if b.contained_in else "-"
            pr_str = f"#{b.pr.number} {b.pr.state}" if b.pr else "-"
            marker = "* " if b.is_current else "  "
            typer.echo(
                f"{marker}{b.name:<23} {b.commit:<10} {contained:<25} "
                f"{pr_str:<20} {b.unique_commits:<8} {b.source_diff_lines}"
            )


@app.command("delete")
def delete_cmd(
    name: Annotated[str, typer.Argument(help="Branch name to delete")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would happen"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force delete (git branch -D)"),
    ] = False,
) -> None:
    """Delete a branch, its worktree, and remote tracking branch."""
    cur = str(git("branch", "--show-current")).strip()
    if name == cur:
        typer.echo(f"Error: cannot delete the current branch ({name})", err=True)
        raise typer.Exit(1)

    worktrees = parse_worktrees()
    worktree_path = worktrees.get(name)

    actions: list[str] = []

    if worktree_path:
        actions.append(f"Remove worktree: {worktree_path}")
    actions.append(f"Delete local branch: {name} ({'force' if force else 'safe'})")

    has_remote = False
    try:
        git("rev-parse", "--verify", f"refs/remotes/origin/{name}")
        has_remote = True
        actions.append(f"Delete remote branch: origin/{name}")
    except sh.ErrorReturnCode:
        pass

    if dry_run:
        typer.echo(f"Would perform {len(actions)} action(s):")
        for action in actions:
            typer.echo(f"  {action}")
        return

    if worktree_path:
        try:
            git("worktree", "remove", worktree_path)
            typer.echo(f"Removed worktree: {worktree_path}")
        except sh.ErrorReturnCode as e:
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
            typer.echo(f"Warning: worktree removal failed: {stderr}", err=True)

    try:
        if force:
            git("branch", "-D", name)
        else:
            git("branch", "-d", name)
        typer.echo(f"Deleted branch: {name}")
    except sh.ErrorReturnCode as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        typer.echo(f"Failed to delete branch: {stderr}", err=True)
        typer.echo("Use --force to force delete", err=True)
        raise typer.Exit(1)

    if has_remote:
        try:
            git("push", "origin", "--delete", name)
            typer.echo(f"Deleted remote branch: origin/{name}")
        except sh.ErrorReturnCode as e:
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
            typer.echo(f"Warning: remote deletion failed: {stderr}", err=True)
