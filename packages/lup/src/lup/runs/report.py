"""The one place a unit says how far into its own work it has got.

Three doorways lead here and only here writes, because the three are the same
statement made from different distances: a callable step has a
:class:`~lup.runs.pipeline.StepContext` and names no path, a shell unit with
this library importable calls :func:`report_progress` with the workspace it
was handed, and a shell unit in any language spawns ``run report``, which
reads ``$LUP_RUN_WORKSPACE`` itself. Three writers would be three chances for
the record's shape to drift from the reader's.

What a unit reports is what it has done. It never reports a rate or a time
left: those need two readings and a clock between them, the reader holds
both, and :mod:`lup.runs.progress` is where the arithmetic that refuses a
smoothed estimate already lives.
"""

import threading
import time
from pathlib import Path

from pydantic import BaseModel, Field

from lup.channels.models import publish_atomic
from lup.runs.directory import progress_in
from lup.runs.models import UnitProgress
from lup.types import JsonValue

PROGRESS_INTERVAL_SECONDS = 1.0
"""How close together two reports of the same unit may land before one is dropped.

Progress is a sample rather than a log. A monitor reads every two seconds, so
a report more often than this is written for nobody, and the unit's result
records how it ended whatever the last sample happened to be. The number is
generous against the reader's interval rather than tight against the writer's
loop, because a training step and a solver call differ by orders of magnitude
and neither should have to think about it.
"""


class ProgressThrottle(BaseModel, arbitrary_types_allowed=True):
    """When each workspace's record was last written, so a tight loop is cheap.

    Per workspace rather than per process, because a callable step reporting
    from several threads and a pipeline running eight units at once are the
    ordinary cases, and one unit's chatter must not silence another's. The
    stamps cross threads, which is what the lock is for, and it is taken only
    around the map — never around the write, which would serialise units that
    have nothing to do with each other.

    Monotonic rather than wall clock: this decides an interval, and a clock
    stepped backwards by an NTP correction would drop every report until it
    caught up.
    """

    written: dict[Path, float] = {}
    guard: threading.Lock = Field(default_factory=threading.Lock, exclude=True)

    def due(self, workspace: Path, interval: float, now: float) -> bool:
        """Whether this workspace may write again, stamping it when it may."""
        with self.guard:
            last = self.written.get(workspace)
            if last is not None and now - last < interval:
                return False
            self.written[workspace] = now
            return True


THROTTLE = ProgressThrottle()
"""The stamps this process holds, which is the grain the throttle works at.

A command-line report is its own process and so carries an empty one, which
is right: a spawn per report already costs more than the write it is skipping,
and saying so is the ``run report`` help's job rather than this map's.
"""


def report_progress(
    workspace: Path,
    done: int,
    total: int | None = None,
    phase: str = "",
    detail: dict[str, JsonValue] | None = None,
    interval: float = PROGRESS_INTERVAL_SECONDS,
    throttle: ProgressThrottle = THROTTLE,
) -> UnitProgress | None:
    """Publish how far this unit has got, and say what was written.

    None when the throttle dropped the call, so a caller that wants to know
    whether its sample landed can, and one that does not may ignore it — the
    common loop reports on every iteration and cares only that the cheap case
    is cheap.
    """
    if not throttle.due(workspace, interval, time.monotonic()):
        return None
    progress = UnitProgress(
        done=done, total=total, phase=phase, detail=detail if detail is not None else {}
    )
    publish_progress(workspace, progress)
    return progress


def publish_progress(workspace: Path, progress: UnitProgress) -> None:
    """Write one record where the reader looks for it, atomically.

    Separate from the throttled doorway because the two answer different
    questions — whether to write, and where a write goes — and a caller that
    has already decided the first (a test pinning the reader, a runtime
    landing a final sample) should not have to defeat a stamp to get the
    second.
    """
    publish_atomic(progress_in(workspace), progress)
