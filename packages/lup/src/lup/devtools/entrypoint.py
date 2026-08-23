"""Import-safe dispatch for a project's composed ``lup-devtools`` CLI.

The conflict workflow repairs source that may not import. Its console script
therefore enters this library module, recognizes that one command family, and
builds only the library-owned repair tree. Every other command loads the
project's full Typer application from installed package metadata.

The metadata is materialized when the environment is synced, so reading it
does not parse a currently conflicted ``pyproject.toml``.
"""

from importlib.metadata import entry_points
import sys

import typer


def project_application() -> typer.Typer:
    """Load the one project application registered for this environment."""
    applications = list(entry_points(group="lup.devtools", name="application"))
    if len(applications) != 1:
        typer.echo(
            "The environment must register exactly one 'lup.devtools' "
            f"application entry point; found {len(applications)}.",
            err=True,
        )
        raise typer.Exit(1)

    application = applications[0].load()
    if not isinstance(application, typer.Typer):
        typer.echo(
            "The 'lup.devtools' application entry point must resolve to a "
            "Typer application.",
            err=True,
        )
        raise typer.Exit(1)
    return application


def conflict_application() -> typer.Typer:
    """Build only the library modules needed to repair a conflicted tree."""
    from lup.devtools.dev import conflicts
    from lup.devtools.dev.conflict_app import create_conflict_app
    from lup.workspace.paths import find_nearest_pyproject

    root_app = typer.Typer(
        help="lup-devtools: conflict-safe repair commands",
        pretty_exceptions_show_locals=False,
        no_args_is_help=True,
    )
    dev_app = typer.Typer(no_args_is_help=True)
    dev_app.add_typer(
        create_conflict_app(),
        name="conflict",
        help="Merge/rebase conflict resolution",
    )
    root_app.add_typer(
        dev_app,
        name="dev",
        help="Conflict-safe development repair",
    )

    @root_app.callback()
    def report_conflicted_manifest() -> None:
        """Name the launcher that remains available when the manifest is broken."""
        project_root = find_nearest_pyproject()
        if project_root is not None and conflicts.manifest_conflicted(project_root):
            typer.echo(conflicts.conflicted_manifest_notice(project_root), err=True)

    return root_app


def main() -> None:
    """Dispatch conflict repair without importing the project's application."""
    match sys.argv:
        case [_, "dev", "conflict", *_]:
            conflict_application()()
        case _:
            project_application()()
