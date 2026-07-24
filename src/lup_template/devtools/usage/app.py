"""Typer app for the usage display: one-shot output and the watch loop."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from lup.adapters.claude.profile_store import ClaudeProfileStore
from lup_template.devtools.usage.api import creds_path, fetch_usage, load_stats
from lup_template.devtools.usage.render import (
    build_display,
    build_error_panel,
    build_snapshot,
)

app = typer.Typer(no_args_is_help=True)
console = Console()


def fetch_and_build(config_dir: Path, detail: bool, bar_width: int) -> Panel:
    """Fetch usage and build the display panel."""
    usage = fetch_usage(config_dir)
    stats = load_stats(config_dir) if detail else None
    return build_display(usage, stats, detail, bar_width)


def emit_json(config_dir: Path, detail: bool) -> None:
    """Print the usage snapshot as JSON so an agent can read counts and limits.

    stdout stays valid JSON on failure too: API errors are reported as an
    ``{"error": ...}`` object with a non-zero exit, never human-formatted text.
    """
    try:
        usage = fetch_usage(config_dir)
    except (httpx.HTTPStatusError, httpx.ConnectError) as e:
        print(json.dumps({"error": str(e)}))
        raise typer.Exit(1) from e
    stats = load_stats(config_dir) if detail else None
    snapshot = build_snapshot(usage, stats)
    print(snapshot.model_dump_json(indent=2))


# ── CLI ────────────────────────────────────────────────────


@app.command("claude")
def claude(
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Claude profile to read usage for (default: active profile).",
        ),
    ] = None,
    detail: Annotated[
        bool,
        typer.Option(
            "--detail/--no-detail",
            help="Show daily breakdown from stats cache.",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-readable usage (counts and limits) instead of bars.",
        ),
    ] = False,
    watch: Annotated[
        bool,
        typer.Option(
            "--watch/--no-watch",
            "-w",
            help="Continuously refresh the display (requires a terminal).",
        ),
    ] = False,
    interval: Annotated[
        int,
        typer.Option(
            "--interval",
            "-n",
            help="Refresh interval in seconds (with --watch).",
        ),
    ] = 600,
) -> None:
    """Show live Claude Code usage with pacing bars (Anthropic OAuth only)."""
    config_dir = ClaudeProfileStore().resolve_config_dir(profile)
    creds = creds_path(config_dir)
    if not creds.exists():
        console.print(f"[red]No credentials at {creds}[/red]")
        console.print(
            "[dim]This command reads Claude Code OAuth usage from "
            "api.anthropic.com; there is no codex/openai equivalent. "
            "For per-session cost/tokens on any backend, see the session "
            "JSON (trace list shows the backend).[/dim]"
        )
        raise typer.Exit(1)

    if json_output:
        emit_json(config_dir, detail)
        return

    bar_width = min(console.width - 10, 58)

    if not watch or not console.is_terminal:
        try:
            panel = fetch_and_build(config_dir, detail, bar_width)
        except httpx.HTTPStatusError as e:
            console.print(
                f"[red]API error: {e.response.status_code}"
                f" {e.response.text[:200]}[/red]"
            )
            raise typer.Exit(1) from e
        except httpx.ConnectError as e:
            console.print(f"[red]Connection failed: {e}[/red]")
            raise typer.Exit(1) from e
        console.print()
        console.print(panel)
        return

    timestamp = Text(
        f"  updated {datetime.now().strftime('%H:%M:%S')}"
        f"  ·  every {interval}s  ·  ctrl-c to quit",
        style="dim",
    )
    try:
        panel = fetch_and_build(config_dir, detail, bar_width)
    except (httpx.HTTPStatusError, httpx.ConnectError):
        panel = build_error_panel("Initial fetch failed")

    with Live(
        Group(panel, timestamp),
        console=console,
        refresh_per_second=1,
        screen=True,
    ) as live:
        while True:
            try:
                time.sleep(interval)
                panel = fetch_and_build(config_dir, detail, bar_width)
            except (httpx.HTTPStatusError, httpx.ConnectError) as e:
                panel = build_error_panel(str(e)[:120])
            except KeyboardInterrupt:
                break
            timestamp = Text(
                f"  updated {datetime.now().strftime('%H:%M:%S')}"
                f"  ·  every {interval}s  ·  ctrl-c to quit",
                style="dim",
            )
            live.update(Group(panel, timestamp))
