"""PR lifecycle: status, merge, push, checks, and base sync.

Mechanical helpers for ``/lup:close`` and ``/lup:rebase``.

Examples::

    $ uv run lup-devtools dev pr status --json
    $ uv run lup-devtools dev pr merge 42
    $ uv run lup-devtools dev pr sync-base --json
    $ uv run lup-devtools dev pr push --force --json
    $ uv run lup-devtools dev pr create --base dev --title "feat: search" --body "..."
    $ uv run lup-devtools dev pr update 42 --body "..."
"""

import json
import logging
from urllib.parse import urlparse

import sh
import typer
from pydantic import BaseModel

from lup_template.devtools.dev.branches import (
    detect_base_branch,
    get_integration_branch,
)
from lup_template.devtools.dev.worktree import get_tree_dir

from lup_template.devtools.utils import git, gh, decode_stderr, output_json

logger = logging.getLogger(__name__)


def current_branch() -> str:
    return str(git("branch", "--show-current")).strip()


class ReviewInfo(BaseModel):
    author: str
    state: str
    body: str


class CheckInfo(BaseModel):
    name: str
    status: str
    conclusion: str


class PRInfo(BaseModel):
    number: int
    title: str
    url: str
    review_decision: str
    mergeable: str
    checks_passing: bool
    reviews: list[ReviewInfo]
    checks: list[CheckInfo]


class PRStatusResult(BaseModel):
    branch: str
    pr: PRInfo | None


class MergeResult(BaseModel):
    pr_number: int
    merged: bool
    integration_branch: str
    pulled: bool


class SyncBaseResult(BaseModel):
    feature_branch: str
    base_branch: str
    merged: bool
    conflicts: list[str]


class PushResult(BaseModel):
    branch: str
    pushed: bool
    force: bool
    existing_pr: dict[str, str | int] | None


class CreateResult(BaseModel):
    number: int
    url: str


def output_result(result: BaseModel, as_json: bool) -> None:
    if as_json:
        output_json(result)
        return

    if isinstance(result, PRStatusResult):
        if result.pr:
            format_pr_status(result)
        else:
            typer.echo(f"branch: {result.branch}")
            typer.echo("pr: no open PR")
        return

    for key, value in result.model_dump().items():
        if isinstance(value, list):
            typer.echo(f"{key}:")
            for item in value:
                typer.echo(f"  - {item}")
        elif isinstance(value, dict):
            typer.echo(f"{key}:")
            for k, v in value.items():
                typer.echo(f"  {k}: {v}")
        else:
            typer.echo(f"{key}: {value}")


def format_pr_status(result: PRStatusResult) -> None:
    """Pretty-print PR status with formatted reviews and checks."""
    pr = result.pr
    if not pr:
        return

    typer.echo(f"\n  PR #{pr.number}: {pr.title}")
    typer.echo(f"  {pr.url}")
    typer.echo(f"  Review: {pr.review_decision or 'pending'}")
    typer.echo(f"  Mergeable: {pr.mergeable}")

    if pr.reviews:
        typer.echo(f"\n  Reviews ({len(pr.reviews)}):")
        for r in pr.reviews:
            typer.echo(f"    {r.author:<20} {r.state}")

    if pr.checks:
        typer.echo(f"\n  Checks ({len(pr.checks)}):")
        passed = sum(
            1
            for c in pr.checks
            if c.conclusion.upper() in ("SUCCESS", "NEUTRAL", "SKIPPED")
        )
        typer.echo(f"    {passed}/{len(pr.checks)} passing")
        for c in pr.checks:
            marker = (
                "✓"
                if c.conclusion.upper() in ("SUCCESS", "NEUTRAL", "SKIPPED")
                else "✗"
            )
            typer.echo(f"    {marker} {c.name}: {c.conclusion or c.status}")


def find_base_branch() -> str:
    """Auto-detect the base branch by merge-base proximity to HEAD."""
    try:
        base, _, _ = detect_base_branch()
        return base
    except typer.Exit, SystemExit:
        return get_integration_branch()


def status(
    branch: str | None,
    as_json: bool,
) -> None:
    """Fetch PR review status, checks, and comments for a branch."""
    branch_name = branch or current_branch()

    try:
        pr_list_raw = str(
            gh(
                "pr",
                "list",
                "--head",
                branch_name,
                "--state",
                "open",
                "--json",
                "number,title,url",
            )
        ).strip()
    except sh.ErrorReturnCode as e:
        typer.echo(f"Failed to query PRs via gh: {decode_stderr(e)}", err=True)
        raise typer.Exit(1)
    prs = json.loads(pr_list_raw)

    if not prs:
        result = PRStatusResult(branch=branch_name, pr=None)
        output_result(result, as_json)
        if not as_json:
            typer.echo(f"No open PR found for branch {branch_name}")
        return

    pr_data = prs[0]
    pr_number = pr_data["number"]

    try:
        detail_raw = str(
            gh(
                "pr",
                "view",
                str(pr_number),
                "--json",
                "reviews,statusCheckRollup,mergeable,mergeStateStatus,reviewDecision",
            )
        ).strip()
    except sh.ErrorReturnCode as e:
        typer.echo(
            f"Failed to fetch PR #{pr_number} via gh: {decode_stderr(e)}", err=True
        )
        raise typer.Exit(1)
    detail = json.loads(detail_raw)

    reviews = [
        ReviewInfo(
            author=r.get("author", {}).get("login", "unknown"),
            state=r.get("state", ""),
            body=r.get("body", ""),
        )
        for r in detail.get("reviews", [])
    ]

    raw_checks = detail.get("statusCheckRollup", []) or []
    checks = [
        CheckInfo(
            name=c.get("name", c.get("context", "unknown")),
            status=c.get("status", ""),
            conclusion=c.get("conclusion", ""),
        )
        for c in raw_checks
    ]

    checks_passing = (
        all(
            c.conclusion.upper() in ("SUCCESS", "NEUTRAL", "SKIPPED")
            for c in checks
            if c.status.upper() == "COMPLETED"
        )
        if checks
        else True
    )

    pr_info = PRInfo(
        number=pr_number,
        title=pr_data["title"],
        url=pr_data["url"],
        review_decision=detail.get("reviewDecision", ""),
        mergeable=detail.get("mergeable", ""),
        checks_passing=checks_passing,
        reviews=reviews,
        checks=checks,
    )

    result = PRStatusResult(branch=branch_name, pr=pr_info)
    output_result(result, as_json)


def merge(
    pr_number: int,
    dry_run: bool,
    as_json: bool = False,
) -> None:
    """Squash-merge a PR and pull changes into the integration branch."""
    integration = get_integration_branch()

    if dry_run:
        typer.echo(f"Would merge PR #{pr_number} (squash)")
        typer.echo(f"Would pull changes into {integration}")
        return

    try:
        gh("pr", "merge", str(pr_number), "--squash", "--delete-branch")
        typer.echo(f"Merged PR #{pr_number}")
    except sh.ErrorReturnCode as e:
        typer.echo(f"Merge failed: {decode_stderr(e)}", err=True)
        raise typer.Exit(1)

    try:
        tree_dir = get_tree_dir()
    except typer.Exit, SystemExit:
        tree_dir = None
    integration_path = tree_dir / integration if tree_dir else None
    pulled = False
    if integration_path and integration_path.is_dir():
        try:
            git("-C", str(integration_path), "pull")
            typer.echo(f"Pulled changes into {integration}")
            pulled = True
        except sh.ErrorReturnCode as e:
            typer.echo(
                f"Warning: pull failed in {integration}: {decode_stderr(e)}", err=True
            )

    result = MergeResult(
        pr_number=pr_number,
        merged=True,
        integration_branch=integration,
        pulled=pulled,
    )
    output_result(result, as_json)


def sync_base(
    base: str | None,
    as_json: bool,
) -> None:
    """Sync the base branch and merge it into the current feature branch."""
    feature = current_branch()
    base_branch = base or find_base_branch()

    if not as_json:
        typer.echo(f"Feature branch: {feature}", err=True)
        typer.echo(f"Base branch: {base_branch}", err=True)

    try:
        tree_dir = get_tree_dir()
    except typer.Exit, SystemExit:
        tree_dir = None
    base_path = tree_dir / base_branch if tree_dir else None

    if base_path and base_path.is_dir():
        if not as_json:
            typer.echo(f"Syncing {base_branch}...", err=True)
        try:
            git("-C", str(base_path), "pull")
            git("-C", str(base_path), "push")
        except sh.ErrorReturnCode as e:
            typer.echo(
                f"Warning: sync of {base_branch} failed: {decode_stderr(e)}", err=True
            )

    if not as_json:
        typer.echo(f"Merging {base_branch} into {feature}...", err=True)

    try:
        git("merge", base_branch)
        result = SyncBaseResult(
            feature_branch=feature,
            base_branch=base_branch,
            merged=True,
            conflicts=[],
        )
    except sh.ErrorReturnCode:
        conflict_output = str(
            git("diff", "--name-only", "--diff-filter=U", _ok_code=[0, 1])
        ).strip()
        conflicts = [f for f in conflict_output.splitlines() if f]
        result = SyncBaseResult(
            feature_branch=feature,
            base_branch=base_branch,
            merged=False,
            conflicts=conflicts,
        )
        if not as_json:
            typer.echo(f"Merge conflicts in {len(conflicts)} file(s):", err=True)
            for f in conflicts:
                typer.echo(f"  {f}", err=True)

    output_result(result, as_json)
    if not result.merged:
        raise typer.Exit(1)


def push(
    force: bool,
    as_json: bool,
) -> None:
    """Push the current branch and report any existing PR."""
    branch_name = current_branch()

    try:
        if force:
            git("push", "--force")
        else:
            git("push", "-u", "origin", branch_name)
        pushed = True
    except sh.ErrorReturnCode as e:
        typer.echo(f"Push failed: {decode_stderr(e)}", err=True)
        pushed = False

    existing_pr = None
    try:
        pr_raw = str(
            gh(
                "pr",
                "list",
                "--head",
                branch_name,
                "--state",
                "open",
                "--json",
                "number,url",
            )
        ).strip()
        prs = json.loads(pr_raw) if pr_raw else []
        if prs:
            existing_pr = {"number": prs[0]["number"], "url": prs[0]["url"]}
    except sh.ErrorReturnCode:
        pass

    result = PushResult(
        branch=branch_name,
        pushed=pushed,
        force=force,
        existing_pr=existing_pr,
    )
    output_result(result, as_json)
    if not pushed:
        raise typer.Exit(1)


def parse_pr_url(stdout: str) -> str:
    """Extract the PR URL from ``gh pr create`` stdout (last URL-like line)."""
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if urlparse(candidate).scheme in ("http", "https"):
            return candidate
    return ""


def create(
    base: str,
    title: str,
    body: str,
    as_json: bool,
) -> None:
    """Create a new PR.

    ``gh pr create`` has no ``--json`` flag — on success it prints the new
    PR's URL to stdout. The PR number is the final path segment of that URL.
    """
    try:
        raw = str(
            gh(
                "pr",
                "create",
                "--base",
                base,
                "--title",
                title,
                "--body",
                body,
            )
        ).strip()
    except sh.ErrorReturnCode as e:
        typer.echo(f"Failed to create PR: {decode_stderr(e)}", err=True)
        raise typer.Exit(1)

    url = parse_pr_url(raw)
    if not url:
        typer.echo(f"PR created but URL not found in output:\n{raw}", err=True)
        raise typer.Exit(1)

    number_segment = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if not number_segment.isdigit():
        typer.echo(f"PR created at {url} but could not parse number", err=True)
        raise typer.Exit(1)

    result = CreateResult(number=int(number_segment), url=url)
    output_result(result, as_json)


def update(
    pr_number: int,
    body: str,
) -> None:
    """Update a PR body."""
    try:
        gh("pr", "edit", str(pr_number), "--body", body)
        typer.echo(f"Updated PR #{pr_number}")
    except sh.ErrorReturnCode as e:
        typer.echo(f"Failed to update PR: {decode_stderr(e)}", err=True)
        raise typer.Exit(1)
