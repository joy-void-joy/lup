"""Typer command tree for dev operations: worktrees, branches, PRs, checks."""

from pathlib import Path
from typing import Annotated

import typer

import lup_template.devtools.dev.antipatterns as antipatterns_mod
import lup_template.devtools.dev.branches as branches
import lup_template.devtools.dev.check as check
import lup_template.devtools.dev.comments as comments
import lup_template.devtools.dev.conflicts as conflicts
import lup_template.devtools.dev.init as init
import lup_template.devtools.dev.plugin as plugin
import lup_template.devtools.dev.pr as pr
import lup_template.devtools.dev.resolve_review as resolve_review
import lup_template.devtools.dev.worktree as worktree

app = typer.Typer(no_args_is_help=True)
worktree_app = typer.Typer(no_args_is_help=True)
pr_app = typer.Typer(no_args_is_help=True)
conflict_app = typer.Typer(no_args_is_help=True)
init_app = typer.Typer(no_args_is_help=True)
plugin_app = typer.Typer(no_args_is_help=True)
app.add_typer(worktree_app, name="worktree", help="Worktree management")
app.add_typer(pr_app, name="pr", help="PR lifecycle (status, merge, push, checks)")
app.add_typer(conflict_app, name="conflict", help="Merge/rebase conflict resolution")
app.add_typer(init_app, name="init", help="Project initialization")
app.add_typer(plugin_app, name="plugin", help="Local plugin marketplace wiring")


# -- worktree commands --


@worktree_app.command("create")
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
    base_branch: Annotated[
        str | None,
        typer.Option("--base", "-b", help="Base branch (default: current branch)"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Delete an existing unregistered directory at the worktree path",
        ),
    ] = False,
) -> None:
    """Create or re-attach a git worktree."""
    worktree.create(name, no_sync, no_copy_data, base_branch, force)


@worktree_app.command("list")
def worktree_list_cmd() -> None:
    """List all git worktrees with branch and status info."""
    worktree.list_worktrees()


@worktree_app.command("remove")
def worktree_remove_cmd(
    name: Annotated[str, typer.Argument(help="Worktree name or path to remove")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Force removal even if dirty"),
    ] = False,
) -> None:
    """Remove a git worktree."""
    worktree.remove(name, force)


# -- branch commands --


@app.command("branches")
def branches_cmd(
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
    branches.branch_status(branch, as_json)


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
    branches.base_branch(branch, as_json)


# -- pr-body command --


@app.command("pr-body")
def pr_body_cmd(
    base: Annotated[
        str | None,
        typer.Option("--base", "-b", help="Override base branch"),
    ] = None,
) -> None:
    """Generate a PR body (summary, commits, test plan) from branch commits."""
    branches.pr_body(base)


# -- branch survey and delete --


@app.command("survey")
def survey_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Full branch inventory: containment, PRs, unique commits, diff sizes."""
    branches.survey(as_json)


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
    branches.delete_branch(name, dry_run, force)


@app.command("resolve-branch")
def resolve_branch_cmd(
    concern_id: Annotated[
        str, typer.Argument(help="Concern slug; becomes the resolve/<id> branch")
    ],
) -> None:
    """Create + switch to the resolve/<id> branch (a /lup:resolve editor's first step).

    Runs through the allowlisted `uv run lup-devtools` path so the bash hook needs
    no special case for the editor — autonomy for the editor lives in the edit hook.
    """
    branches.create_resolve_branch(concern_id)


@app.command("resolve-review")
def resolve_review_cmd(
    manifest: Annotated[
        Path,
        typer.Argument(help="Manifest JSON: workflow task output or a bare array"),
    ],
    base: Annotated[
        str,
        typer.Option(
            "--base", help="Snapshot base ref the resolve branches diff against"
        ),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Output HTML path"),
    ] = Path("tmp/resolve-review.html"),
    intro: Annotated[
        Path | None,
        typer.Option(
            "--intro", help="HTML fragment prepended as a run-specific header"
        ),
    ] = None,
) -> None:
    """Render a /lup:resolve manifest and its branch diffs into one static HTML review.

    One section per concern: the generalized spec, each original note paired with
    the verifier's per-note finding, the editor summary, the verdict, and the full
    colored diff against the base. The /lup:resolve command runs this in Phase 5
    so the human gate reviews concrete diffs instead of prose.
    """
    resolve_review.build_review(manifest, base, out, intro)


# -- conflict commands --


@conflict_app.command("list")
def conflict_list_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Show conflicted files with scope classification (in-scope vs out-of-scope)."""
    conflicts.conflicts(as_json)


@conflict_app.command("status")
def conflict_status_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Detect conflict state, list files, and show both sides' history."""
    conflicts.conflict_status(as_json)


@conflict_app.command("audit")
def conflict_audit_cmd(
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
    conflicts.conflict_audit(files, as_json)


@conflict_app.command("complete")
def conflict_complete_cmd(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would happen"),
    ] = False,
) -> None:
    """Finalize the merge/rebase/cherry-pick after all conflicts are resolved."""
    conflicts.conflict_complete(dry_run)


# -- check command --


@app.command("check")
def check_cmd(
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Auto-fix formatting and lint issues"),
    ] = False,
    no_test: Annotated[
        bool,
        typer.Option("--no-test", help="Skip pytest"),
    ] = False,
    antipatterns: Annotated[
        bool,
        typer.Option(
            "--antipatterns",
            help="Audit tracked files for missing/spurious `# lup: ignore` markers "
            "only — the same lup.antipatterns rules the edit hook enforces",
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output findings as JSON (with --antipatterns)"),
    ] = False,
) -> None:
    """Run ruff format, ruff check, pyright, and pytest. Read-only by default."""
    if antipatterns:
        antipatterns_mod.report(as_json)
        return
    check.run_checks(fix, no_test)


# -- comments command --


@app.command("comments")
def comments_cmd(
    targets: Annotated[
        list[str] | None,
        typer.Argument(help="file:line markers to remove with --clear"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    commit: Annotated[
        bool,
        typer.Option(
            "--commit", help="Commit comment-bearing files as a prompt snapshot"
        ),
    ] = False,
    clear: Annotated[
        bool,
        typer.Option(
            "--clear",
            help="Strip the file:line markers given (only on a resolve/* worktree branch)",
        ),
    ] = False,
) -> None:
    """List unresolved `# lup:` feedback comments, or clear specific ones.

    With --clear, removes each `file:line` marker named as an argument; used at
    fork time to strip a concern's own notes from an editor's worktree.
    """
    if clear:
        comments.clear_markers(targets or [])
        return
    comments.report(as_json, commit)


@app.command("todos")
def todos_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """List `TEMPLATE:` customization markers — the template's open decision points.

    Every place the template needs a domain decision carries a `# TEMPLATE:`
    comment (or a `TEMPLATE:` docstring line). `/lup:init` runs this to gather
    them all and walk them one by one, so no customization point depends on
    someone remembering to mention it. Same file/line/text/context shape as
    `dev comments`.
    """
    comments.todos(as_json)


# -- init commands --


@init_app.command("rename-package")
def init_rename_package_cmd(
    new_name: Annotated[
        str,
        typer.Argument(
            help="New package name (valid Python identifier, e.g. 'aib', 'forecast_bot')"
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", "-n", help="Show what would change without modifying files"
        ),
    ] = False,
) -> None:
    """Rename the lup Python package to a project-specific name."""
    init.rename_package(new_name, dry_run)


# -- plugin commands --


@plugin_app.command("name")
def plugin_name_cmd(
    name: Annotated[
        str | None,
        typer.Argument(help="Marketplace name (default: pyproject [project].name)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show changes without writing"),
    ] = False,
) -> None:
    """Name this repo's plugin marketplace uniquely (the plugin entry stays 'lup').

    Marketplace names share one global namespace, so a shared name like
    'lup'/'local' collides across repos and worktrees and installs shadow
    each other. Naming the marketplace after the project fixes that.
    """
    plugin.name_marketplace(name, dry_run)


# -- pr commands --


@pr_app.command("status")
def pr_status_detail_cmd(
    branch: Annotated[
        str | None,
        typer.Option("--branch", "-b", help="Branch name (default: current branch)"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Fetch PR review status, checks, and comments for a branch."""
    pr.status(branch, as_json)


@pr_app.command("merge")
def pr_merge_cmd(
    pr_number: Annotated[int, typer.Argument(help="PR number to merge")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would happen"),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Squash-merge a PR and pull changes into the integration branch."""
    pr.merge(pr_number, dry_run, as_json)


@pr_app.command("sync-base")
def pr_sync_base_cmd(
    base: Annotated[
        str | None,
        typer.Option("--base", "-b", help="Base branch (default: auto-detect)"),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Sync the base branch and merge it into the current feature branch."""
    pr.sync_base(base, as_json)


@pr_app.command("push")
def pr_push_cmd(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force push"),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Push the current branch and report any existing PR."""
    pr.push(force, as_json)


@pr_app.command("create")
def pr_create_cmd(
    base: Annotated[str, typer.Option("--base", help="Target branch for PR")],
    title: Annotated[str, typer.Option("--title", help="PR title")],
    body: Annotated[str, typer.Option("--body", help="PR body (markdown)")],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    """Create a new PR."""
    pr.create(base, title, body, as_json)


@pr_app.command("update")
def pr_update_cmd(
    pr_number: Annotated[int, typer.Argument(help="PR number to update")],
    body: Annotated[str, typer.Option("--body", help="New PR body (markdown)")],
) -> None:
    """Update a PR body."""
    pr.update(pr_number, body)
