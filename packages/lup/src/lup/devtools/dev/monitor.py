"""Following a background run from wherever you happen to be.

The command reads a run directory and nothing else, so it works on a run
launched detached, launched by somebody else, or launched before this shell
existed — and it never writes there, so several people may follow one run and
none of them perturbs it.

Two faces, because a person and an agent want opposite things from a watch: a
screen that stays put and always shows now, or a line at a time that can be
woken for. :mod:`lup.runs.follow` carries both; this module is the seam that
puts them behind flags.
"""

from pathlib import Path

import typer

from lup.runs.follow import follow, follow_events
from lup.runs.ledger import RunDirectory
from lup.runs.progress import read_progress


def once(directory: RunDirectory, log: Path | None) -> str:
    """One reading, rendered as the two lines a person would have watched."""
    reading = read_progress(directory, log)
    return (
        f"{reading.name}: {reading.landed}/{reading.total} units landed "
        f"{reading.postfix()}\n{reading.describe_activity()}"
    )


def stream(
    directory: RunDirectory, log: Path | None, interval: float, quiet_limit: float
) -> None:
    """Print one line per thing that happens, ending when the run does.

    Flushed per line rather than per buffer, because whoever is reading this
    is reading it as it happens: a watcher that only sees the lines once the
    run has exited is a watcher that learned nothing a final report would not
    have told it.
    """
    for event in follow_events(directory, log, interval, quiet_limit):
        typer.echo(event)


def report(directory: RunDirectory, log: Path | None, interval: float) -> str:
    """Watch in place until the run ends, and say how it stood at the end."""
    reading = follow(directory, log, interval)
    return f"{reading.landed}/{reading.total} units landed {reading.postfix()}"
