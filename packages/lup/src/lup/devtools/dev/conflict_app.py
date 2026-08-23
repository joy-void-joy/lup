"""The import-isolated command tree for merge and rebase repair.

The ordinary ``dev`` app mounts this tree alongside the rest of its workflow.
The console-script dispatcher can also mount it alone, which is what lets the
repair commands start while a project module imported by the ordinary CLI
still contains conflict markers.
"""

from typing import Annotated

import typer

from lup.devtools.dev import conflicts


def create_conflict_app() -> typer.Typer:
    """Build the commands that inspect, audit, and complete a git conflict."""
    app = typer.Typer(no_args_is_help=True)

    @app.command("list")
    def conflict_list_cmd(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Output as JSON"),
        ] = False,
    ) -> None:
        """Show conflicted files with scope classification (in-scope vs out-of-scope)."""
        conflicts.conflicts(as_json)

    @app.command("status")
    def conflict_status_cmd(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Output as JSON"),
        ] = False,
    ) -> None:
        """Detect conflict state, list files, and show both sides' history."""
        conflicts.conflict_status(as_json)

    @app.command("audit")
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

    @app.command("complete")
    def conflict_complete_cmd(
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", "-n", help="Show what would happen"),
        ] = False,
    ) -> None:
        """Finalize the merge/rebase/cherry-pick after all conflicts are resolved."""
        conflicts.conflict_complete(dry_run)

    return app
