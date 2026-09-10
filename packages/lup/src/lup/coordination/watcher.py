"""The watcher as a run, for the case where nobody is at the terminal.

A person follows a repository with the foreground command. A watcher meant to
wake idle peers has nobody watching *it*, and a process like that is declared
as a pipeline rather than scripted, so it survives its launcher, can be
resumed, and is followed with `run monitor <dir> --events` like every other
long job here — one line per change, and a stall reported as a stall rather
than left looking like quiet.

**It ends when there is nobody left to watch.** A run has to land, and the
honest landing for a watcher is the roster going empty: the population it
served is gone, and a new one will be started by whoever starts it. Started
against an empty roster it lands at once, which is the truth rather than a
process idling for a population that may never arrive.
"""

from pathlib import Path

from lup.coordination.repository import RepositoryPeers
from lup.coordination.watch import Watcher
from lup.runs.pipeline import CallableStep, Pipeline, StepContext, StepOutcome


def watcher_pipeline(
    root: Path, member: str = "", interval: float = 2.0, nudge: bool = True
) -> Pipeline:
    """One step that follows the repository until its roster is empty.

    Nudging is on by default here and off in the foreground command, because
    that is the whole difference between the two: a person reading a stream
    will act on what they read, and a process nobody reads exists to act.
    """

    def follow(context: StepContext) -> StepOutcome:
        """Write every change to the unit's workspace until nobody is live."""
        peers = RepositoryPeers(root)
        watcher = Watcher(peers, root=root, member=member, nudge=nudge)
        log = context.workspace / "events.log"
        count = 0
        with log.open("a", encoding="utf-8") as out:
            for event in watcher.follow(
                interval=interval, until=lambda: not peers.live_ids()
            ):
                out.write(f"{event.at.isoformat()} {event.line()}\n")
                out.flush()
                count += 1
        return StepOutcome(outcome="ended", detail={"events": count})

    return Pipeline(
        name="coordination-watch",
        steps=[CallableStep(id="watch", body=follow)],
    )
