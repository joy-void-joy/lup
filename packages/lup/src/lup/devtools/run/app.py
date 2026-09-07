"""The command tree for work that outlives the tool call that started it.

One command, and its own sub-app anyway. A sub-app is a surface of a module,
and this is the runs module's only one: a project that declines long-running
pipelines should stop being offered a way to watch them, and while ``monitor``
sat under ``dev`` it was owned by ``core`` and every project had it.

It reads only what a runner writes, so a run launched detached, launched by
somebody else, or launched before this shell existed all read back the same —
and reading one cannot perturb it.
"""

from pathlib import Path
from typing import Annotated

import typer

import lup.devtools.dev.monitor as monitor
from lup.runs.ledger import RunDirectory


def create_run_app() -> typer.Typer:
    """Wire the command tree for following a background run."""
    app = typer.Typer(no_args_is_help=True)

    @app.command("monitor")
    def monitor_cmd(
        run_directory: Annotated[
            Path,
            typer.Argument(help="A run directory holding manifest.json and units/"),
        ],
        log: Annotated[
            Path | None,
            typer.Option(
                "--log",
                help="The runner's log; defaults to run.log inside the directory",
            ),
        ] = None,
        interval: Annotated[
            float,
            typer.Option("--interval", help="Seconds between readings"),
        ] = 2.0,
        events: Annotated[
            bool,
            typer.Option("--events", help="One line per change, for a watcher"),
        ] = False,
        one_shot: Annotated[
            bool,
            typer.Option("--once", help="Print one reading and exit"),
        ] = False,
        quiet_limit: Annotated[
            float,
            typer.Option(
                "--quiet-limit", help="Seconds of silence that reads as a stall"
            ),
        ] = 900.0,
    ) -> None:
        """Follow a background run: its landed units, their statuses, its heartbeat.

        Works on a run launched detached or from another session, because it
        reads only what the runner writes. `--events` emits one line per thing
        that happens and ends when the run does, which is the shape a watcher
        is woken by; without it the reading is redrawn in place for a person.
        Nothing about the run is touched either way.
        """
        directory = RunDirectory(root=run_directory)
        if events:
            monitor.stream(directory, log, interval, quiet_limit)
            return
        if one_shot:
            typer.echo(monitor.once(directory, log))
            return
        typer.echo(monitor.report(directory, log, interval))

    return app
