"""Git operations: worktrees, branch analysis, and pre-flight checks."""

from typing import Annotated

import typer

from lup.devtools.git import branches, check, worktree

app = typer.Typer(no_args_is_help=True)
worktree_app = typer.Typer(no_args_is_help=True)
app.add_typer(worktree_app, name="worktree", help="Worktree management")


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
    worktree.create(name, no_sync, no_copy_data, no_plugin_refresh, base_branch)


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
    branches.pr_status(branch, as_json)


# -- check command --


@app.command("check")
def check_cmd(
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Auto-fix ruff issues"),
    ] = False,
    no_test: Annotated[
        bool,
        typer.Option("--no-test", help="Skip pytest"),
    ] = False,
) -> None:
    """Run pyright, ruff, and pytest."""
    check.run_checks(fix, no_test)
