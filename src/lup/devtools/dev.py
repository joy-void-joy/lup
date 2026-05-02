"""Worktree management, session git operations, and branch analysis.

Examples::

    $ uv run lup-devtools dev worktree-create feat-search
    $ uv run lup-devtools dev worktree-create fix-bug --base main
    $ uv run lup-devtools dev commit-results
    $ uv run lup-devtools dev commit-results --dry-run
    $ uv run lup-devtools dev base-branch
    $ uv run lup-devtools dev branch-status
    $ uv run lup-devtools dev branch-status my-feature
    $ uv run lup-devtools dev pr-status
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Annotated

import sh
import typer

from lup.lib.history import iter_session_dirs
from lup.lib.paths import traces_path

logger = logging.getLogger(__name__)
app = typer.Typer(no_args_is_help=True)

git = sh.Command("git")

PLUGIN_CACHE_DIR = Path.home() / ".claude" / "plugins" / "cache" / "local" / "lup"

GITIGNORED_EXTRAS = [
    ".env.local",
    "downstream.json.local",
    ".claude/settings.local.json",
    "logs",
    "refs",
]


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    try:
        xclip = sh.Command("xclip")
        xclip("-selection", "clipboard", _in=text)
        return True
    except (sh.ErrorReturnCode, sh.CommandNotFound):
        pass
    try:
        xsel = sh.Command("xsel")
        xsel("--clipboard", "--input", _in=text)
        return True
    except (sh.ErrorReturnCode, sh.CommandNotFound):
        pass
    return False


# ---------------------------------------------------------------------------
# worktree-create
# ---------------------------------------------------------------------------


def branch_exists(branch: str) -> bool:
    """Check if a git branch exists (local only)."""
    try:
        git("rev-parse", "--verify", f"refs/heads/{branch}")
        return True
    except sh.ErrorReturnCode:
        return False


def worktree_is_registered(path: Path) -> bool:
    """Check if a path is registered as a git worktree (even if dir is missing)."""
    output = str(git("worktree", "list", "--porcelain"))
    resolved = str(path.resolve())
    for line in output.splitlines():
        if line.startswith("worktree ") and line.split(" ", 1)[1] == resolved:
            return True
    return False


def get_tree_dir() -> Path:
    """Find the tree/ directory that contains worktrees."""
    cwd = Path.cwd().resolve()

    if cwd.parent.name == "tree":
        return cwd.parent

    tree = cwd / "tree"
    if tree.is_dir():
        return tree

    for parent in cwd.parents:
        tree = parent / "tree"
        if tree.is_dir():
            return tree

    typer.echo("Error: Could not find tree/ directory", err=True)
    raise typer.Exit(1)


@app.command("worktree-create")
def worktree_create_cmd(
    name: Annotated[
        str, typer.Argument(help="Name for the worktree (e.g., feat-name)")
    ],
    no_sync: Annotated[
        bool,
        typer.Option("--no-sync", help="Skip running uv sync"),
    ] = False,
    no_copy_data: Annotated[
        bool,
        typer.Option("--no-copy-data", help="Skip copying gitignored extras"),
    ] = False,
    no_plugin_refresh: Annotated[
        bool,
        typer.Option(
            "--no-plugin-refresh", help="Skip plugin cache refresh and install"
        ),
    ] = False,
    base_branch: Annotated[
        str | None,
        typer.Option("--base", "-b", help="Base branch (default: current branch)"),
    ] = None,
) -> None:
    """Create or re-attach a git worktree."""
    uv = sh.Command("uv")
    current_dir = Path.cwd()

    tree_dir = get_tree_dir()
    worktree_path = tree_dir / name
    already_exists = branch_exists(name)

    if worktree_path.exists():
        if worktree_is_registered(worktree_path):
            typer.echo(f"Worktree already active: {worktree_path}")
            raise typer.Exit(0)
        typer.echo(f"Removing stale worktree directory: {worktree_path}")
        shutil.rmtree(worktree_path)

    git("worktree", "prune")

    if already_exists:
        typer.echo(f"Re-attaching worktree: {worktree_path}")
        typer.echo(f"Existing branch: {name}")
    else:
        typer.echo(f"Creating worktree: {worktree_path}")
        typer.echo(f"New branch: {name}")

    try:
        if already_exists:
            git("worktree", "add", str(worktree_path), name)
        elif base_branch:
            git("worktree", "add", str(worktree_path), "-b", name, base_branch)
        else:
            git("worktree", "add", str(worktree_path), "-b", name)
    except sh.ErrorReturnCode as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        typer.echo(f"Error creating worktree: {stderr}")
        raise typer.Exit(1)

    if not no_copy_data:
        for rel_path in GITIGNORED_EXTRAS:
            src = current_dir / rel_path
            if not src.exists():
                continue
            dst = worktree_path / rel_path
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
                typer.echo(f"Copied {rel_path}/")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                typer.echo(f"Copied {rel_path}")

    if not no_sync:
        typer.echo("Running uv sync...")
        try:
            uv("sync", _cwd=str(worktree_path))
        except sh.ErrorReturnCode as e:
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
            typer.echo(f"Warning: uv sync failed: {stderr}")

    if not no_plugin_refresh:
        if PLUGIN_CACHE_DIR.exists():
            shutil.rmtree(PLUGIN_CACHE_DIR)
            typer.echo("Cleared plugin cache (lup)")

        claude = sh.Command("claude")
        try:
            claude(
                "plugin",
                "install",
                "lup@local",
                "--scope",
                "project",
                _cwd=str(worktree_path),
                _tty_out=False,
            )
            typer.echo("Installed lup plugin (project scope)")
        except sh.ErrorReturnCode as e:
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
            typer.echo(f"Warning: plugin install failed: {stderr}", err=True)

    typer.echo()
    cd_command = f"cd /; cd {worktree_path}; claude"

    if copy_to_clipboard(cd_command):
        typer.echo(f"Copied to clipboard: {cd_command}")
    else:
        typer.echo("Done! To switch to the new worktree:")
        typer.echo(f"  {cd_command}")


# ---------------------------------------------------------------------------
# commit-results
# ---------------------------------------------------------------------------


def get_uncommitted_session_ids() -> set[str]:
    """Find session IDs with uncommitted result files."""
    session_ids: set[str] = set()

    status = str(git.status("--porcelain", "--", "notes/", _ok_code=[0])).strip()
    if not status:
        return session_ids

    for line in status.splitlines():
        file_path = line[3:].split(" -> ")[0].strip()
        parts = Path(file_path).parts

        if (
            len(parts) >= 5
            and parts[0] == "notes"
            and parts[1] == "traces"
            and parts[3] in ("sessions", "logs")
        ):
            session_ids.add(parts[4])

    return session_ids


def get_session_summary(session_id: str) -> str:
    """Read summary from the latest session JSON across all versions."""
    all_json: list[Path] = []
    for session_dir in iter_session_dirs(session_id=session_id):
        all_json.extend(session_dir.glob("*.json"))

    if not all_json:
        return f"session {session_id}"

    latest = sorted(all_json)[-1]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
        output = data.get("output", {})
        if isinstance(output, dict):
            return output.get("summary", f"session {session_id}")[:50]
        return f"session {session_id}"
    except (json.JSONDecodeError, OSError):
        return f"session {session_id}"


def commit_session(session_id: str, *, dry_run: bool = False) -> bool:
    """Stage and commit files for a single session ID."""
    paths: list[str] = []

    for session_dir in iter_session_dirs(session_id=session_id):
        paths.append(str(session_dir))

    if traces_path().exists():
        for ver_dir in traces_path().iterdir():
            if not ver_dir.is_dir():
                continue
            log_dir = ver_dir / "logs" / session_id
            if log_dir.exists():
                paths.append(str(log_dir))

    if not paths:
        return False

    if dry_run:
        summary = get_session_summary(session_id)
        print(f"  Would commit {session_id}: {summary}")
        for p in paths:
            print(f"    {p}")
        return True

    for path in paths:
        try:
            git.add(path)
        except sh.ErrorReturnCode as e:
            logger.warning("Failed to stage %s: %s", path, e)

    diff = str(git.diff("--cached", "--stat", _ok_code=[0, 1])).strip()
    if not diff:
        return False

    summary = get_session_summary(session_id)
    slug = summary[:50].strip().rstrip(".")
    git.commit("-m", f"data(sessions): {slug}")
    print(f"  Committed {session_id}: {slug}")
    return True


@app.command("commit-results")
def commit_results(
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be committed"
    ),
) -> None:
    """Commit all uncommitted session result files, one commit per session."""
    session_ids = get_uncommitted_session_ids()

    if not session_ids:
        print("Nothing to commit.")
        return

    print(f"Found {len(session_ids)} session(s) with uncommitted files")

    committed = 0
    for session_id in sorted(session_ids):
        try:
            if commit_session(session_id, dry_run=dry_run):
                committed += 1
        except sh.ErrorReturnCode as e:
            print(f"  Failed {session_id}: {e}")

    if dry_run:
        print(f"\nWould commit {committed} session(s)")
    else:
        print(f"\nCommitted {committed} session(s)")


# ---------------------------------------------------------------------------
# base-branch
# ---------------------------------------------------------------------------


def detect_base_branch(branch: str | None = None) -> tuple[str, str, int]:
    """Detect the base branch for the given (or current) branch.

    Returns (base_branch, merge_base_sha, commits_ahead).
    Raises typer.Exit(1) when detection is ambiguous.
    """
    if branch is None:
        branch = str(git("branch", "--show-current")).strip()

    local_branches = [
        b.strip().lstrip("* ")
        for b in str(git("branch", "--format=%(refname:short)")).strip().splitlines()
        if b.strip().lstrip("* ") != branch
    ]

    if not local_branches:
        typer.echo("No other local branches to compare against.", err=True)
        raise typer.Exit(1)

    best_branch = ""
    best_distance = -1
    best_merge_base = ""
    candidates: list[tuple[str, int, str]] = []

    for candidate in local_branches:
        try:
            merge_base = str(
                git("merge-base", branch, candidate, _ok_code=[0])
            ).strip()
            distance = int(
                str(git("rev-list", "--count", f"{merge_base}..{branch}")).strip()
            )
            candidates.append((candidate, distance, merge_base))
            if best_distance < 0 or distance < best_distance:
                best_distance = distance
                best_branch = candidate
                best_merge_base = merge_base
        except sh.ErrorReturnCode:
            continue

    if not best_branch:
        typer.echo("Could not determine base branch.", err=True)
        raise typer.Exit(1)

    tied = [c for c in candidates if c[1] == best_distance and c[0] != best_branch]
    if tied:
        typer.echo("Ambiguous base branch. Candidates:", err=True)
        for name, dist, _ in [(best_branch, best_distance, best_merge_base), *tied]:
            typer.echo(f"  {name} ({dist} commits ahead)", err=True)
        raise typer.Exit(1)

    return best_branch, best_merge_base, best_distance


@app.command("base-branch")
def base_branch_cmd(
    branch: Annotated[
        str | None,
        typer.Argument(help="Branch to analyze (default: current)"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Detect the base branch for the current (or specified) branch."""
    base, merge_base, ahead = detect_base_branch(branch)
    effective = branch or str(git("branch", "--show-current")).strip()

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "branch": effective,
                    "base": base,
                    "merge_base": merge_base,
                    "commits_ahead": ahead,
                }
            )
        )
    else:
        typer.echo(f"Branch: {effective}")
        typer.echo(f"Base: {base}")
        typer.echo(f"Merge base: {merge_base[:10]}")
        typer.echo(f"Commits ahead: {ahead}")


# ---------------------------------------------------------------------------
# branch-status
# ---------------------------------------------------------------------------


def get_integration_branch() -> str:
    """Return 'dev' if it exists locally, else 'main'."""
    if branch_exists("dev"):
        return "dev"
    return "main"


def is_ancestor(ancestor: str, descendant: str) -> bool:
    """Check if ancestor is an ancestor of descendant."""
    try:
        git("merge-base", "--is-ancestor", ancestor, descendant)
        return True
    except sh.ErrorReturnCode:
        return False


def get_branch_worktree(branch: str) -> str | None:
    """Return the worktree path for a branch, or None."""
    output = str(git("worktree", "list", "--porcelain"))
    current_worktree = ""
    for line in output.splitlines():
        if line.startswith("worktree "):
            current_worktree = line.split(" ", 1)[1]
        elif line.startswith("branch ") and line.endswith(f"/{branch}"):
            return current_worktree
    return None


def get_pr_info(branch: str) -> dict[str, str]:
    """Get PR info for a branch via gh CLI. Returns empty dict if none."""
    gh = sh.Command("gh")
    try:
        output = str(
            gh(
                "pr",
                "list",
                "--state=all",
                f"--head={branch}",
                "--json=number,title,state,mergedAt,url",
                "--limit=1",
                _ok_code=[0],
            )
        ).strip()
        items: list[dict[str, str]] = json.loads(output)
        if items:
            return items[0]
    except (sh.ErrorReturnCode, sh.CommandNotFound, json.JSONDecodeError):
        pass
    return {}


def classify_branch(
    branch: str,
    integration: str,
    current: str,
) -> dict[str, str | bool | None]:
    """Classify a branch as DELETE/STALE/KEEP/CURRENT with reason."""
    if branch == current:
        return {"branch": branch, "status": "CURRENT", "reason": "current branch"}

    merged_into_integration = is_ancestor(branch, integration)
    worktree = get_branch_worktree(branch)
    pr = get_pr_info(branch)
    pr_state = pr.get("state", "")
    pr_merged = pr_state == "MERGED"
    pr_number = pr.get("number", "")
    pr_url = pr.get("url", "")

    if merged_into_integration:
        return {
            "branch": branch,
            "status": "DELETE",
            "reason": f"merged into {integration}",
            "worktree": worktree,
            "pr": pr_number,
            "pr_url": pr_url,
        }

    if pr_merged:
        return {
            "branch": branch,
            "status": "DELETE",
            "reason": f"PR #{pr_number} merged",
            "worktree": worktree,
            "pr": pr_number,
            "pr_url": pr_url,
        }

    # Check if content reached integration transitively
    try:
        output = str(
            git(
                "log",
                "--oneline",
                "--cherry-pick",
                "--left-only",
                f"{branch}...{integration}",
                _ok_code=[0],
            )
        ).strip()
        unique = len(output.splitlines()) if output else 0
    except sh.ErrorReturnCode:
        unique = 999

    if unique == 0:
        return {
            "branch": branch,
            "status": "STALE",
            "reason": f"all commits cherry-picked into {integration}",
            "worktree": worktree,
            "pr": pr_number,
            "pr_url": pr_url,
        }

    return {
        "branch": branch,
        "status": "KEEP",
        "reason": f"{unique} unique commits, PR: {pr_state or 'none'}",
        "worktree": worktree,
        "pr": pr_number,
        "pr_url": pr_url,
    }


@app.command("branch-status")
def branch_status_cmd(
    branch: Annotated[
        str | None,
        typer.Argument(help="Specific branch to check (default: all)"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Analyze branch containment, PR status, and worktree info."""
    try:
        git("fetch", "--prune", _ok_code=[0])
    except sh.ErrorReturnCode:
        pass

    integration = get_integration_branch()
    current = str(git("branch", "--show-current")).strip()

    if branch:
        branches = [branch]
    else:
        branches = [
            b.strip().lstrip("* ")
            for b in str(git("branch", "--format=%(refname:short)")).strip().splitlines()
        ]

    results: list[dict[str, str | bool | None]] = []
    for b in branches:
        results.append(classify_branch(b, integration, current))

    if as_json:
        typer.echo(json.dumps(results, indent=2))
        return

    typer.echo(f"\nIntegration branch: {integration}")
    typer.echo(f"Current branch: {current}\n")
    typer.echo(f"{'Branch':<30} {'Status':<10} {'Reason'}")
    typer.echo("-" * 80)

    for r in results:
        status = r["status"]
        marker = {"DELETE": "x", "STALE": "~", "KEEP": " ", "CURRENT": "*"}.get(
            str(status), " "
        )
        wt = " [worktree]" if r.get("worktree") else ""
        typer.echo(f"[{marker}] {r['branch']:<27} {status:<10} {r['reason']}{wt}")

    typer.echo()
    deletable = [r for r in results if r["status"] in ("DELETE", "STALE")]
    if deletable:
        typer.echo(f"{len(deletable)} branch(es) can be cleaned up")


# ---------------------------------------------------------------------------
# pr-status
# ---------------------------------------------------------------------------


@app.command("pr-status")
def pr_status_cmd(
    branch: Annotated[
        str | None,
        typer.Argument(help="Branch to check PR for (default: current)"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show PR review status, checks, and merge readiness."""
    gh = sh.Command("gh")
    effective = branch or str(git("branch", "--show-current")).strip()

    try:
        output = str(
            gh(
                "pr",
                "list",
                f"--head={effective}",
                "--state=open",
                "--json=number,title,url,reviewDecision,statusCheckRollup,mergeable,mergeStateStatus",
                "--limit=1",
                _ok_code=[0],
            )
        ).strip()
        items: list[dict[str, object]] = json.loads(output)
    except (sh.ErrorReturnCode, sh.CommandNotFound) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if not items:
        typer.echo(f"No open PR found for branch '{effective}'")
        raise typer.Exit(1)

    pr = items[0]

    if as_json:
        typer.echo(json.dumps(pr, indent=2))
        return

    typer.echo(f"\nPR #{pr['number']}: {pr['title']}")
    typer.echo(f"URL: {pr['url']}")
    typer.echo(f"Review decision: {pr.get('reviewDecision') or 'none'}")
    typer.echo(f"Mergeable: {pr.get('mergeable', '?')}")
    typer.echo(f"Merge state: {pr.get('mergeStateStatus', '?')}")

    checks = pr.get("statusCheckRollup")
    if isinstance(checks, list):
        passed = sum(1 for c in checks if c.get("conclusion") == "SUCCESS")
        failed = sum(1 for c in checks if c.get("conclusion") == "FAILURE")
        pending = len(checks) - passed - failed
        typer.echo(f"Checks: {passed} passed, {failed} failed, {pending} pending")
