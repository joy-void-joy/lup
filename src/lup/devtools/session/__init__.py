"""Session data: traces, metrics, feedback state, and commit operations."""

from pathlib import Path
from typing import Annotated

import typer

from lup.devtools.session import state, traces
from lup.lib.history import resolve_version
from lup.version import AGENT_VERSION

app = typer.Typer(no_args_is_help=True)

VERSION_OPT = Annotated[
    str | None,
    typer.Option("--version", "-v", help="Agent version (default: current)"),
]
ALL_VERSIONS_OPT = Annotated[
    bool,
    typer.Option("--all-versions", help="Include all versions"),
]


# -- trace commands --


@app.command("show")
def show_cmd(
    session_id: str = typer.Argument(..., help="Session ID to show trace for"),
    full: bool = typer.Option(False, "-f", "--full", help="Show full trace"),
    tool_calls: bool = typer.Option(
        False, "--tool-calls", "-t", help="Show only tool call blocks"
    ),
) -> None:
    """Show trace for a session."""
    traces.show(session_id, full, tool_calls)


@app.command("search")
def search_cmd(
    pattern: str = typer.Argument(..., help="Pattern to search for (regex)"),
    context: int = typer.Option(2, "-C", help="Lines of context around match"),
) -> None:
    """Search traces for a pattern."""
    traces.search(pattern, context)


@app.command("list")
def list_cmd(
    limit: int = typer.Option(20, "-n", "--limit", help="Max to show"),
    version: VERSION_OPT = AGENT_VERSION,
    all_versions: ALL_VERSIONS_OPT = False,
) -> None:
    """List available traces."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    traces.list_traces(limit, effective)


@app.command("errors")
def errors_cmd(
    limit: int = typer.Option(20, "-n", "--limit", help="Max errors to show"),
    version: VERSION_OPT = AGENT_VERSION,
    all_versions: ALL_VERSIONS_OPT = False,
) -> None:
    """Show sessions with errors (from metrics and traces)."""
    effective, warning = resolve_version(version, all_versions)
    if warning:
        typer.echo(warning)
    state.errors(limit, version, all_versions)
    traces.errors_in_traces(limit, effective)


@app.command("capabilities")
def capabilities_cmd() -> None:
    """Extract capability requests from traces."""
    traces.capabilities()


# -- state commands --


@app.command("status")
def status_cmd(
    version: VERSION_OPT = AGENT_VERSION,
    all_versions: ALL_VERSIONS_OPT = False,
) -> None:
    """Show feedback status: version, data, analysis state, and aggregate stats."""
    state.status(version, all_versions)


@app.command("collect")
def collect_cmd(
    since: Annotated[
        str | None,
        typer.Option(
            "--since", "-s", help="Only sessions after this date (YYYY-MM-DD)"
        ),
    ] = None,
    all_time: Annotated[
        bool,
        typer.Option("--all-time", help="Include all sessions regardless of date"),
    ] = False,
    version: VERSION_OPT = AGENT_VERSION,
    all_versions: ALL_VERSIONS_OPT = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path"),
    ] = None,
) -> None:
    """Collect feedback metrics from sessions."""
    state.collect(since, all_time, version, all_versions, output)


@app.command("tools")
def tools_cmd(
    version: VERSION_OPT = AGENT_VERSION,
    all_versions: ALL_VERSIONS_OPT = False,
) -> None:
    """Show tool usage aggregates."""
    state.tools(version, all_versions)


@app.command("trends")
def trends_cmd(
    window: Annotated[
        int,
        typer.Option("-w", "--window", help="Rolling window size"),
    ] = 10,
    version: VERSION_OPT = AGENT_VERSION,
    all_versions: ALL_VERSIONS_OPT = False,
) -> None:
    """Show metric trends over time."""
    state.trends(window, version, all_versions)


@app.command("history")
def history_cmd(
    limit: Annotated[
        int,
        typer.Option("-n", "--limit", help="Max to show"),
    ] = 10,
) -> None:
    """Show previous feedback collection runs."""
    state.history(limit)


@app.command("mark")
def mark_cmd(
    session_ids: Annotated[
        list[str], typer.Argument(help="Session IDs to mark as analyzed")
    ],
) -> None:
    """Mark sessions as analyzed in the feedback loop."""
    state.mark(session_ids)


@app.command("unmark")
def unmark_cmd(
    session_ids: Annotated[list[str], typer.Argument(help="Session IDs to unmark")],
) -> None:
    """Remove analysis marks from sessions."""
    state.unmark(session_ids)


@app.command("prompt-health")
def prompt_health_cmd() -> None:
    """Analyze the agent prompt for size and patch accumulation."""
    state.prompt_health()


@app.command("unanalyzed")
def unanalyzed_cmd(
    version: VERSION_OPT = AGENT_VERSION,
    all_versions: ALL_VERSIONS_OPT = False,
) -> None:
    """List unanalyzed session IDs, one per line."""
    state.unanalyzed(version, all_versions)


@app.command("commit")
def commit_cmd(
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be committed"
    ),
) -> None:
    """Commit all uncommitted session result files, one commit per session."""
    state.commit(dry_run)
