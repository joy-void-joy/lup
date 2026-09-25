"""Running a project's host companions for exactly as long as one session.

The declaration is :class:`~lup.harness.companions.HostCompanion`; this is
the launch's half. Each companion starts in a session of its own, so the
signal that stops it reaches what it started too -- a dev server's workers,
a watcher's children -- and its output goes to a log beside the launch's
other launch-owned state, outside the checkout, rather than into the
terminal the session is about to take over.

Stopping is gentle first and certain after: a terminate to the whole group,
a grace period, then a kill. A companion that will not stop is not a reason
to leave the operator's terminal hanging after the session has ended.
"""

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sh

from lup.devtools.harness.modes import variants_home
from lup.harness.companions import HostCompanion
from lup.harness.notice import Notice


def companions_home(root: Path) -> Path:
    """Where one checkout's companions write their logs, outside the checkout."""
    return variants_home(root, Path.home() / ".cache" / "lup" / "companions")


def stopped(running: sh.RunningCommand, grace: float = 5.0) -> None:
    """Stop one companion and everything it started, gently and then surely."""
    try:
        running.signal_group(signal.SIGTERM)
        running.wait(timeout=grace)
    except sh.TimeoutException:
        running.kill_group()
    except (ProcessLookupError, sh.ErrorReturnCode, sh.SignalException):
        # Already gone, or ended by the signal just sent: stopped either way.
        return


@contextmanager
def companions_running(
    declared: list[HostCompanion], root: Path, logs: Path
) -> Iterator[list[Notice]]:
    """Start each companion, hand back what the banner says, and stop them all after.

    A companion that cannot start -- its program is not installed here -- is
    said and skipped, since it is a convenience beside the session rather
    than something the session needs; the others still start.
    """
    said: list[Notice] = []
    started: list[sh.RunningCommand] = []
    if declared:
        logs.mkdir(parents=True, exist_ok=True)
    for companion in declared:
        log = logs / f"{companion.name}.log"
        program, *arguments = companion.command
        try:
            running = sh.Command(program)(
                *arguments,
                _bg=True,
                _bg_exc=False,
                _new_session=True,
                _cwd=str(root / companion.directory),
                _out=str(log),
                _err_to_out=True,
                _return_cmd=True,
            )
        except sh.CommandNotFound:
            said.append(
                Notice(
                    text=(
                        f"Companion {companion.name}: {program} is not installed "
                        "here, so it was not started"
                    ),
                    urgency="boundary",
                )
            )
            continue
        started.append(running)
        where = f"{companion.url} " if companion.url else ""
        said.append(
            Notice(
                text=f"Companion {companion.name}: {where}(log: {log})",
                urgency="detail",
            )
        )
    try:
        yield said
    finally:
        for running in started:
            stopped(running)
