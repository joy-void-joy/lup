"""Branch analysis: containment, PR status, base detection, PR body generation."""

import json
import logging
from collections import defaultdict
from typing import Required, TypedDict
from urllib.parse import urlparse

import sh
import typer
from pydantic import BaseModel

from lup_template.devtools.utils import git, gh, decode_stderr, output_json

logger = logging.getLogger(__name__)


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


class BranchClassification(TypedDict, total=False):
    branch: Required[str]
    status: Required[str]
    reason: Required[str]
    worktree: str | None
    pr: str | int
    pr_url: str


class ParsedBranch(TypedDict):
    """One row of ``git branch -vv`` output."""

    name: str
    commit: str
    tracking: str | None
    is_current: bool


def parse_branches() -> list[ParsedBranch]:
    """Parse ``git branch -vv`` into structured data.

    Handles prefix markers: ``*`` (current), ``+`` (checked out in another worktree).
    """
    output = str(git("branch", "-vv")).strip()
    results: list[ParsedBranch] = []

    for line in output.splitlines():
        is_current = line.startswith("*")
        # Strip the 2-char prefix column (* /+/space + space)
        line = line[2:].strip()
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

        results.append(
            {
                "name": name,
                "commit": commit,
                "tracking": tracking,
                "is_current": is_current,
            }
        )

    return results


def parse_worktrees() -> dict[str, str]:
    """Map branch name -> worktree path from ``git worktree list --porcelain``."""
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
            gh(
                "pr",
                "list",
                "--state",
                "all",
                "--limit",
                "200",
                "--json",
                "number,title,headRefName,state,mergedAt",
            )
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
        logger.warning("Failed to fetch PR status: %s", decode_stderr(e))

    return mapping


def count_unique_commits(branch: str, integration: str) -> int:
    """Count commits on branch not cherry-picked into integration."""
    try:
        output = str(
            git(
                "rev-list",
                "--count",
                "--cherry-pick",
                "--left-only",
                f"{branch}...{integration}",
                _ok_code=[0],
            )
        ).strip()
        return int(output)
    except (sh.ErrorReturnCode, ValueError):
        return -1


def count_source_diff_lines(branch: str, integration: str) -> int:
    """Count lines of source-file diff between branch and integration."""
    try:
        output = str(
            git(
                "diff",
                "--stat",
                branch,
                integration,
                "--",
                "src/",
                ".claude/",
                "tests/",
                _ok_code=[0, 1],
            )
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


def get_integration_branch() -> str:
    """Return 'dev' if it exists locally, else 'main'."""
    from lup_template.devtools.dev.worktree import branch_exists

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
    return parse_worktrees().get(branch)


def get_pr_info(branch: str) -> dict[str, str]:
    """Get PR info for a branch via gh CLI. Returns empty dict if none."""
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


PROTECTED_BRANCHES = {"main", "master", "dev", "develop"}


def classify_branch(
    branch: str,
    integration: str,
    current: str,
    *,
    has_remote: bool = True,
) -> BranchClassification:
    """Classify a branch as DELETE/STALE/KEEP/CURRENT/NOT_FOUND with reason."""
    from lup_template.devtools.dev.worktree import branch_exists

    if not branch_exists(branch):
        return {
            "branch": branch,
            "status": "NOT_FOUND",
            "reason": "no such local branch",
        }

    if branch == current:
        return {"branch": branch, "status": "CURRENT", "reason": "current branch"}

    if branch in PROTECTED_BRANCHES:
        return {"branch": branch, "status": "KEEP", "reason": "protected branch"}

    merged_into_integration = is_ancestor(branch, integration)
    worktree = get_branch_worktree(branch)
    pr = get_pr_info(branch) if has_remote else {}
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

    Prefers ancestor branches (the natural parent in a two-tier model)
    over siblings. Among ancestors, picks the one with the fewest commits
    ahead. Falls back to non-ancestor heuristics when no ancestor exists.

    Returns (base_branch, merge_base_sha, commits_ahead).
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

    ancestors: list[tuple[str, int, str]] = []
    non_ancestors: list[tuple[str, int, str]] = []

    for candidate in local_branches:
        try:
            merge_base = str(git("merge-base", branch, candidate, _ok_code=[0])).strip()
            distance = int(
                str(git("rev-list", "--count", f"{merge_base}..{branch}")).strip()
            )
            if is_ancestor(candidate, branch):
                ancestors.append((candidate, distance, merge_base))
            else:
                non_ancestors.append((candidate, distance, merge_base))
        except sh.ErrorReturnCode:
            continue

    # Prefer ancestors — they are the natural base
    candidates = ancestors if ancestors else non_ancestors

    if not candidates:
        typer.echo("Could not determine base branch.", err=True)
        raise typer.Exit(1)

    candidates.sort(key=lambda c: c[1])
    best_branch, best_distance, best_merge_base = candidates[0]

    tied = [c for c in candidates[1:] if c[1] == best_distance]
    if tied:
        typer.echo("Ambiguous base branch. Candidates:", err=True)
        for name, dist, _ in [candidates[0], *tied]:
            typer.echo(f"  {name} ({dist} commits ahead)", err=True)
        raise typer.Exit(1)

    return best_branch, best_merge_base, best_distance


def parse_remote(remote_url: str) -> tuple[str, str] | None:
    """Parse a git remote into (scheme, destination) for auth probing.

    URL forms (https://host/org/repo, ssh://git@host/org/repo) are parsed
    with urllib. SCP form ``[user@]host:path`` is git-equivalent to
    ``ssh://[user@]host/path`` and is detected by a colon preceding the
    first slash; it is normalized to ``ssh://`` and parsed the same way.
    Returns None for local paths and unrecognized remotes.
    """
    parsed = urlparse(remote_url)
    if not parsed.scheme:
        colon, slash = remote_url.find(":"), remote_url.find("/")
        if colon == -1 or (slash != -1 and slash < colon):
            return None
        normalized = "ssh://" + remote_url[:colon] + "/" + remote_url[colon + 1 :]
        parsed = urlparse(normalized)
    if parsed.scheme and parsed.hostname:
        user_prefix = f"{parsed.username}@" if parsed.username else ""
        return parsed.scheme, f"{user_prefix}{parsed.hostname}"
    return None


def probe_ssh_auth(destination: str, remote_url: str) -> bool:
    """Probe SSH auth with ``ssh -T``. GitHub answers with exit 1, GitLab with 0."""
    try:
        ssh = sh.Command("ssh").bake(_tty_out=False)
    except sh.CommandNotFound:
        typer.echo("ssh binary not found; skipping remote checks", err=True)
        return False
    probe = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-T", destination]
    try:
        ssh(*probe, _ok_code=[0, 1])
        return True
    except sh.ErrorReturnCode:
        identity = ""
        lines = str(ssh("-G", destination, _ok_code=[0])).splitlines()
        for line in lines:  # claude: ignore
            if line.startswith("identityfile "):
                identity = line.split(" ", 1)[1]  # claude: ignore
                break
        msg = f"SSH authentication failed for remote '{remote_url}'."
        if identity:
            msg += f"\nLoad the key with:  ssh-add {identity}"
        typer.echo(msg, err=True)
        return False


def probe_gh_auth(remote_url: str) -> bool:
    """Verify GitHub CLI auth, used for https remotes where ssh -T means nothing."""
    try:
        gh("auth", "status", _ok_code=[0])
        return True
    except (sh.ErrorReturnCode, sh.CommandNotFound):
        typer.echo(
            f"gh auth failed for remote '{remote_url}'. Run: gh auth login",
            err=True,
        )
        return False


def check_remote_auth() -> bool:
    """Verify auth for the origin remote. Returns True if remote ops can proceed.

    ssh-style remotes are probed with ``ssh -T``; https remotes are verified
    via ``gh auth status``. Local and unrecognized remotes pass.
    """
    remote_url = str(git("remote", "get-url", "origin")).strip()
    remote = parse_remote(remote_url)
    if remote is None:
        return True
    scheme, destination = remote
    match scheme:
        case "ssh" | "git":
            return probe_ssh_auth(destination, remote_url)
        case "http" | "https":
            return probe_gh_auth(remote_url)
        case _:
            return True


# -- CLI functions --


def branch_status(branch: str | None, as_json: bool) -> None:
    """Analyze branch containment, PR status, and worktree info."""
    has_remote = check_remote_auth()

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

    results: list[BranchClassification] = []
    for b in branch_list:
        results.append(classify_branch(b, integration, current, has_remote=has_remote))

    if as_json:
        output_json(results)
        return

    typer.echo(f"\nIntegration branch: {integration}")
    typer.echo(f"Current branch: {current}\n")
    typer.echo(f"{'Branch':<30} {'Status':<10} {'Reason'}")
    typer.echo("-" * 80)

    for r in results:
        status = r["status"]
        marker = {
            "DELETE": "x",
            "STALE": "~",
            "KEEP": " ",
            "CURRENT": "*",
            "NOT_FOUND": "?",
        }.get(str(status), " ")
        wt = " [worktree]" if r.get("worktree") else ""
        typer.echo(f"[{marker}] {r['branch']:<27} {status:<10} {r['reason']}{wt}")

    typer.echo()
    deletable = [r for r in results if r["status"] in ("DELETE", "STALE")]
    if deletable:
        typer.echo(f"{len(deletable)} branch(es) can be cleaned up")


def base_branch(branch: str | None, as_json: bool) -> None:
    """Detect the base branch for the current (or specified) branch."""
    base, merge_base, ahead = detect_base_branch(branch)
    effective = branch or str(git("branch", "--show-current")).strip()

    if as_json:
        output_json(
            {
                "branch": effective,
                "base": base,
                "merge_base": merge_base,
                "commits_ahead": ahead,
            }
        )
    else:
        typer.echo(f"Branch: {effective}")
        typer.echo(f"Base: {base}")
        typer.echo(f"Merge base: {merge_base[:10]}")
        typer.echo(f"Commits ahead: {ahead}")


COMMIT_PREFIX_LABELS = {
    "feat": "Added",
    "fix": "Fixed",
    "refactor": "Refactored",
    "docs": "Updated docs for",
    "test": "Added tests for",
    "chore": "Updated",
    "meta": "Updated",
    "data": "Added data for",
}


def pr_body(base_override: str | None) -> None:
    """Generate a PR body from the current branch's commits against its base."""
    if base_override:
        base = base_override
    else:
        base, _, _ = detect_base_branch()

    log_output = str(
        git(
            "log",
            "--oneline",
            "--no-decorate",
            "--no-merges",
            f"{base}..HEAD",
            _ok_code=[0],
        )
    ).strip()
    if not log_output:
        typer.echo("No commits found since base branch", err=True)
        raise typer.Exit(1)

    groups: dict[str, list[str]] = defaultdict(list)
    for line in log_output.splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        message = parts[1]
        prefix = message.split("(")[0].split(":")[0].lower().strip()
        groups[prefix].append(message)

    summary_lines: list[str] = []
    for prefix, messages in groups.items():
        label = COMMIT_PREFIX_LABELS.get(prefix, prefix.capitalize())
        desc = messages[0].split(":", 1)[-1].strip()
        if len(messages) == 1:
            summary_lines.append(f"- {label} {desc}")
        else:
            summary_lines.append(f"- {label} {desc} (+{len(messages) - 1} more)")

    body_parts = ["## Summary", *summary_lines, "", "## Commits", log_output]
    body_parts.extend(["", "## Test plan", "- [ ] Verify changes work as expected"])

    typer.echo("\n".join(body_parts))


def survey(as_json: bool) -> None:
    """Collect branch, worktree, PR, and containment data."""
    has_remote = check_remote_auth()
    if has_remote:
        if not as_json:
            typer.echo("Fetching and pruning remote...", err=True)
        try:
            git("fetch", "--prune")
        except sh.ErrorReturnCode as e:
            logger.warning("Failed to fetch: %s", decode_stderr(e))

    integration = get_integration_branch()
    cur = str(git("branch", "--show-current")).strip()

    raw_branches = parse_branches()
    worktrees = parse_worktrees()
    branch_names = [b["name"] for b in raw_branches]
    containment = build_containment(branch_names)

    if has_remote:
        if not as_json:
            typer.echo("Querying PR status...", err=True)
        pr_map = fetch_pr_status(branch_names)
    else:
        pr_map: dict[str, PRStatus] = {}

    branches_list: list[BranchInfo] = []
    for b in raw_branches:
        name = b["name"]
        contained_in = containment.get(name, [])
        is_contained = bool(contained_in)
        pr_merged = name in pr_map and pr_map[name].state == "MERGED"

        if is_contained or pr_merged:
            unique = 0
            diff_lines = 0
        else:
            unique = count_unique_commits(name, integration)
            diff_lines = count_source_diff_lines(name, integration)

        branches_list.append(
            BranchInfo(
                name=name,
                commit=b["commit"],
                tracking=b["tracking"],
                worktree=worktrees.get(name),
                is_current=b["is_current"],
                contained_in=contained_in,
                pr=pr_map.get(name),
                unique_commits=unique,
                source_diff_lines=diff_lines,
            )
        )

    result = SurveyResult(
        integration_branch=integration,
        current_branch=cur,
        branches=branches_list,
    )

    if as_json:
        output_json(result)
    else:
        typer.echo(f"\nIntegration: {integration} | Current: {cur}\n")
        typer.echo(
            f"{'Branch':<25} {'Commit':<10} {'Contained In':<25} {'PR':<20} {'Unique':<8} {'Diff'}"
        )
        typer.echo("-" * 100)
        for bi in branches_list:
            contained = ", ".join(bi.contained_in[:3]) if bi.contained_in else "-"
            pr_str = f"#{bi.pr.number} {bi.pr.state}" if bi.pr else "-"
            marker = "* " if bi.is_current else "  "
            typer.echo(
                f"{marker}{bi.name:<23} {bi.commit:<10} {contained:<25} "
                f"{pr_str:<20} {bi.unique_commits:<8} {bi.source_diff_lines}"
            )


def delete_branch(
    name: str,
    dry_run: bool,
    force: bool,
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
            typer.echo(
                f"Warning: worktree removal failed: {decode_stderr(e)}", err=True
            )

    try:
        if force:
            git("branch", "-D", name)
        else:
            git("branch", "-d", name)
        typer.echo(f"Deleted branch: {name}")
    except sh.ErrorReturnCode as e:
        typer.echo(f"Failed to delete branch: {decode_stderr(e)}", err=True)
        typer.echo("Use --force to force delete", err=True)
        raise typer.Exit(1)

    if has_remote:
        try:
            git("push", "origin", "--delete", name)
            typer.echo(f"Deleted remote branch: origin/{name}")
        except sh.ErrorReturnCode as e:
            typer.echo(f"Warning: remote deletion failed: {decode_stderr(e)}", err=True)
