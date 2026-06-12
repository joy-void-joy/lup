"""Typer command tree for trace display, search, and analysis."""

from typing import Annotated

import typer

import lup_template.devtools.trace.traces as traces
from lup.history import resolve_version
from lup_template.devtools.utils import VERSION_OPT, ALL_VERSIONS_OPT, JSON_OPT

app = typer.Typer(no_args_is_help=True)


@app.command("show")
def show_cmd(
    session_id: Annotated[str, typer.Argument(help="Session ID to show trace for")],
    full: Annotated[
        bool,
        typer.Option("-f", "--full", help="Show full trace"),
    ] = False,
    tool_calls: Annotated[
        bool,
        typer.Option("--tool-calls", "-t", help="Show only tool call blocks"),
    ] = False,
    as_json: JSON_OPT = False,
) -> None:
    """Show trace for a session."""
    traces.show(session_id, full, tool_calls, as_json)


@app.command("search")
def search_cmd(
    pattern: Annotated[str, typer.Argument(help="Pattern to search for (regex)")],
    context: Annotated[
        int,
        typer.Option("-C", help="Lines of context around match"),
    ] = 2,
    as_json: JSON_OPT = False,
) -> None:
    """Search traces for a pattern."""
    traces.search(pattern, context, as_json)


@app.command("list")
def list_cmd(
    limit: Annotated[
        int,
        typer.Option("-n", "--limit", help="Max to show"),
    ] = 20,
    version: VERSION_OPT = None,
    all_versions: ALL_VERSIONS_OPT = False,
    as_json: JSON_OPT = False,
) -> None:
    """List available traces."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    traces.list_traces(limit, effective, as_json)


@app.command("errors")
def errors_cmd(
    limit: Annotated[
        int,
        typer.Option("-n", "--limit", help="Max errors to show"),
    ] = 20,
    version: VERSION_OPT = None,
    all_versions: ALL_VERSIONS_OPT = False,
    as_json: JSON_OPT = False,
) -> None:
    """Show sessions with errors found in trace files."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    traces.errors_in_traces(limit, effective, as_json)


@app.command("capabilities")
def capabilities_cmd(
    as_json: JSON_OPT = False,
) -> None:
    """Extract capability requests from traces."""
    traces.capabilities(as_json)
