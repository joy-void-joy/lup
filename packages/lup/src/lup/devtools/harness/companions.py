"""Running a project's host companions for exactly as long as one session.

The declaration is :class:`~lup.harness.companions.HostCompanion`; this is
the launch's half. Each companion starts in a session of its own, so the
signal that stops it reaches what it started too -- a dev server's workers,
a watcher's children -- and its output goes to a log beside the launch's
other launch-owned state, outside the checkout, rather than into the
terminal the session is about to take over.

Each starts from the environment the launch hands its session, less every
host-only name, plus the host-store keys that companion names and no other:
a companion that did not ask for a key does not get it, even where the
operator's shell exported one.

Stopping is gentle first and certain after: a terminate to the whole group,
a grace period, then a kill. A companion that will not stop is not a reason
to leave the operator's terminal hanging after the session has ended.
"""

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sh

from lup.devtools.envfiles import HostSecrets
from lup.devtools.harness.modes import variants_home
from lup.harness.companions import HostCompanion
from lup.harness.notice import Notice
from lup.types import EnvVars


def companions_home(root: Path) -> Path:
    """Where one checkout's companions write their logs, outside the checkout."""
    return variants_home(root, Path.home() / ".cache" / "lup" / "companions")


def host_only_names(declared: list[HostCompanion], hosted: EnvVars) -> list[str]:
    """Every name no session inherits: what a companion names, and what the store holds."""
    return sorted(
        {*(name for companion in declared for name in companion.secrets), *hosted}
    )


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


def missing_secrets(
    companion: HostCompanion, hosted: EnvVars, store: Path
) -> list[Notice]:
    """What the banner says of a key a companion names and the store does not hold.

    The companion starts all the same: it is a convenience beside the session,
    and the one that knows what it cannot do without a key is the companion.
    """
    missing = [name for name in companion.secrets if name not in hosted]
    if not missing:
        return []
    return [
        Notice(
            text=(
                f"Companion {companion.name}: {', '.join(missing)} not in the host "
                f"store ({store}), so it starts without; "
                f"`lup-launch run setup secret {' '.join(missing)}` sets it"
            ),
            urgency="boundary",
        )
    ]


@contextmanager
def companions_running(
    declared: list[HostCompanion],
    root: Path,
    logs: Path,
    store: HostSecrets,
    inherited: EnvVars,
) -> Iterator[list[Notice]]:
    """Start each companion, hand back what the banner says, and stop them all after.

    ``inherited`` is the environment the launch hands its session; ``store``
    is the host store the companions' secrets are read from. A companion that
    cannot start -- its program is not installed here -- is said and skipped,
    since it is a convenience beside the session rather than something the
    session needs; the others still start.
    """
    said: list[Notice] = []
    started: list[sh.RunningCommand] = []
    if declared:
        logs.mkdir(parents=True, exist_ok=True)
    hosted = store.read() if declared else {}
    withheld = host_only_names(declared, hosted)
    base = {name: value for name, value in inherited.items() if name not in withheld}
    for companion in declared:
        log = logs / f"{companion.name}.log"
        program, *arguments = companion.command
        said.extend(missing_secrets(companion, hosted, store.path))
        try:
            running = sh.Command(program)(
                *arguments,
                _bg=True,
                _bg_exc=False,
                _new_session=True,
                _cwd=str(root / companion.directory),
                _env={
                    **base,
                    **{
                        name: hosted[name]
                        for name in companion.secrets
                        if name in hosted
                    },
                },
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
