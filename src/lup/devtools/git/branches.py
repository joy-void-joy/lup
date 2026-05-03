"""Branch analysis: containment, PR status, base detection."""

import json

import typer


def get_integration_branch() -> str:
    """Return 'dev' if it exists locally, else 'main'."""
    from lup.devtools.git.worktree import branch_exists

    if branch_exists("dev"):
        return "dev"
    return "main"


def is_ancestor(ancestor: str, descendant: str) -> bool:
    """Check if ancestor is an ancestor of descendant."""
    import sh

    git = sh.Command("git")
    try:
        git("merge-base", "--is-ancestor", ancestor, descendant)
        return True
    except sh.ErrorReturnCode:
        return False


def get_branch_worktree(branch: str) -> str | None:
    """Return the worktree path for a branch, or None."""
    import sh

    git = sh.Command("git")
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
    import sh

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
    import sh

    git = sh.Command("git")

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


def detect_base_branch(branch: str | None = None) -> tuple[str, str, int]:
    """Detect the base branch for the given (or current) branch.

    Returns (base_branch, merge_base_sha, commits_ahead).
    """
    import sh

    git = sh.Command("git")

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
            merge_base = str(git("merge-base", branch, candidate, _ok_code=[0])).strip()
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


# -- CLI functions --


def branch_status(branch: str | None, as_json: bool) -> None:
    """Analyze branch containment, PR status, and worktree info."""
    import sh

    git = sh.Command("git")

    try:
        git("fetch", "--prune", _ok_code=[0])
    except sh.ErrorReturnCode:
        pass

    integration = get_integration_branch()
    current = str(git("branch", "--show-current")).strip()

    if branch:
        branch_list = [branch]
    else:
        branch_list = [
            b.strip().lstrip("* ")
            for b in str(git("branch", "--format=%(refname:short)"))
            .strip()
            .splitlines()
        ]

    results: list[dict[str, str | bool | None]] = []
    for b in branch_list:
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


def base_branch(branch: str | None, as_json: bool) -> None:
    """Detect the base branch for the current (or specified) branch."""
    import sh

    git = sh.Command("git")
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


def pr_status(branch: str | None, as_json: bool) -> None:
    """Show PR review status, checks, and merge readiness."""
    import sh

    git = sh.Command("git")
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
