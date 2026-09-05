"""One reading of a run, taken from its directory and nothing else.

A run launched detached, from another session, or before this shell existed
is fully observable without being touched: count the units that landed
against the units the manifest scheduled, tally what they concluded, and
re-read the last line the runner wrote. Nothing here consults the process
table, because under a sandbox ``/proc`` is PID-isolated and a healthy run is
indistinguishable there from a dead one — a liveness answer that asks the
process table is no answer at all on the host a long job most often runs on.

What a reading will not do is repeat the runner's own estimate of the time
left. A progress bar smooths its rate over the last few landings, and units
land in bursts — one per worker as a batch of budgets expires — so that
number said twenty-nine seconds about thirty-six two-hour cells. The estimate
here divides everything landed so far by the whole elapsed time, which is the
only estimate bursty landings support.
"""

import time
from collections import Counter, defaultdict
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from lup.channels.models import utc_now
from lup.runs.ledger import RunDirectory, RunningUnit
from lup.runs.models import RunManifest, RunSummary, StepRecord, UnitStatus


class StepState(StrEnum):
    """Where one step of a run stands."""

    BLOCKED = "blocked"
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class StatusCount(BaseModel, frozen=True):
    """How many landed units are tallied under one word."""

    status: str
    count: int

    def render(self) -> str:
        """The tally as ``status=count``."""
        return f"{self.status}={self.count}"


class StepProgress(BaseModel, frozen=True):
    """Where one step stands, and how much of it has landed."""

    id: str
    state: StepState
    landed: int
    width: int
    failed: int

    def render(self) -> str:
        """The step as one reader-facing phrase."""
        return f"{self.id} {self.state.value} {self.landed}/{self.width}"


class RunProgress(BaseModel, frozen=True):
    """One reading: scheduled, landed, how they ended, and what is going on."""

    directory: Path
    name: str
    total: int
    landed: int
    failed: int
    statuses: list[StatusCount] = []
    running: list[RunningUnit] = []
    steps: list[StepProgress] = []
    unreadable: list[Path] = []
    heartbeat: str = ""
    elapsed_seconds: float | None = None
    eta_seconds: float | None = None
    quiet_for: float | None = None
    summary: RunSummary | None = None

    @property
    def complete(self) -> bool:
        """Whether every scheduled unit has landed."""
        return self.total > 0 and self.landed >= self.total

    @property
    def finished(self) -> bool:
        """Whether the runtime recorded an ending, however the run ended.

        A pipeline whose second stage failed never lands its fourth, so
        waiting for the unit count to reach the total waits forever. The
        summary is what says the run is over.
        """
        return self.summary is not None

    @property
    def oldest_running(self) -> RunningUnit | None:
        """The unit claimed longest, which is the one worth looking at."""
        return self.running[0] if self.running else None

    def postfix(self) -> str:
        """The status tally, alphabetical, with what the monitor knows itself."""
        parts = [
            entry.render() for entry in sorted(self.statuses, key=lambda e: e.status)
        ]
        if self.running:
            parts.append(f"running={len(self.running)}")
        if self.unreadable:
            parts.append(f"unreadable={len(self.unreadable)}")
        if self.elapsed_seconds is not None:
            parts.append(f"elapsed={render_span(self.elapsed_seconds)}")
        if self.eta_seconds is not None:
            parts.append(f"eta={render_span(self.eta_seconds)}")
        return " ".join(parts)

    def describe_activity(self) -> str:
        """What the run is doing now, in the monitor's own honest terms.

        Never the runner's own estimate. When units are running, their count
        and the oldest one's age say the useful thing that estimate was
        crowding out; when none are, the runner's last line is the best
        available account of what it is doing.
        """
        if self.summary is not None:
            return describe_summary(self.summary)
        if self.oldest_running is not None:
            span = render_span(self.oldest_running.age_seconds)
            return (
                f"{len(self.running)} running; oldest "
                f"{self.oldest_running.slug} for {span}"
            )
        if self.complete:
            return "every scheduled unit has landed"
        return self.heartbeat or "(no unit running yet)"

    def stalled(self, quiet_limit: float) -> bool:
        """Whether nothing has happened here for longer than a caller accepts.

        A run whose process was killed leaves no summary and no claim it will
        ever release, so silence is the only evidence that nobody is driving
        it. How long counts as silence belongs to the caller: a pipeline of
        shell steps is quiet for seconds, a solver sweep for hours.
        """
        return (
            not self.finished
            and self.quiet_for is not None
            and self.quiet_for > quiet_limit
        )


def units(count: int) -> str:
    """A unit count that still reads as English when there is one of them."""
    return f"{count} unit" if count == 1 else f"{count} units"


def describe_summary(summary: RunSummary) -> str:
    """How a finished run reads to whoever comes back to it."""
    if summary.interrupted:
        return f"run interrupted after {units(summary.landed)}"
    if summary.failed or summary.skipped:
        skipped = ", ".join(step.id for step in summary.skipped)
        tail = f"; skipped {skipped}" if skipped else ""
        return f"run failed: {units(summary.failed)} failed{tail}"
    return f"run complete: {units(summary.landed)} landed"


def render_span(seconds: float) -> str:
    """A duration as hours, minutes and seconds, whole seconds only."""
    return str(timedelta(seconds=int(seconds)))


def remaining_estimate(total: int, landed: int, elapsed: float | None) -> float | None:
    """The global-average estimate of the time left, the one bursty landings need."""
    if elapsed is None or landed <= 0 or total <= 0:
        return None
    if landed >= total:
        return 0.0
    return elapsed * (total - landed) / landed


def latest_heartbeat(log: Path | None, tail_bytes: int = 16 * 1024) -> str:
    """The last progress line the runner wrote, as it would stand on a terminal.

    A bar rewrites its line with carriage returns rather than newlines;
    ``splitlines`` breaks on both, so the newest heartbeat is the last
    non-empty segment of the log's tail. The tail is bounded because the
    newest line is at the end whatever the log's total size — the rest of the
    file stays on disk, and this is the only reader that does not want it.
    """
    if log is None or not log.is_file():
        return ""
    with log.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - tail_bytes))
        tail = handle.read().decode("utf-8", errors="replace")
    latest = [segment.strip() for segment in tail.splitlines() if segment.strip()]
    return latest[-1] if latest else ""


def default_log(directory: RunDirectory) -> Path | None:
    """The runner's log when it sits inside the run directory."""
    return directory.log_path if directory.log_path.is_file() else None


def silent_for(directory: RunDirectory, log: Path | None) -> float | None:
    """How long since anything in this directory changed.

    Taken from the newest mtime among the manifest, the landed units and the
    log, because those are the three things a working run touches. None when
    the directory holds nothing yet.
    """
    written = [directory.manifest_path, *directory.units_root.glob("*/*.json")]
    candidates = [
        path for path in [*written, log] if path is not None and path.is_file()
    ]
    if not candidates:
        return None
    newest = max(path.stat().st_mtime for path in candidates)
    return max(0.0, time.time() - newest)


def settled_state(statuses: list[UnitStatus], width: int, claimed: int) -> StepState:
    """Which state a step stands in judging only by its own units."""
    if UnitStatus.FAILED in statuses:
        return StepState.FAILED
    if len(statuses) >= width:
        return StepState.DONE
    if claimed or statuses:
        return StepState.RUNNING
    return StepState.PENDING


def step_progress(
    manifest: RunManifest,
    landed: dict[str, list[UnitStatus]],
    running: list[RunningUnit],
) -> list[StepProgress]:
    """Where each declared step stands, given what landed and what is claimed.

    Two passes, because blocked is not a fact about a step's own units: a step
    is blocked when something it rests on has not finished, which can only be
    read once every step's own state is known.
    """
    claimed = Counter(unit.attempt.step for unit in running)
    own = {
        record.id: StepProgress(
            id=record.id,
            state=settled_state(
                landed.get(record.id, []), record.width, claimed[record.id]
            ),
            landed=len(landed.get(record.id, [])),
            width=record.width,
            failed=sum(
                1 for status in landed.get(record.id, []) if status is UnitStatus.FAILED
            ),
        )
        for record in manifest.steps
    }
    return [blocked_or(record, own) for record in manifest.steps]


def blocked_or(record: StepRecord, own: dict[str, StepProgress]) -> StepProgress:
    """A pending step whose dependencies have not all finished reads as blocked."""
    progress = own[record.id]
    waiting = any(
        dependency not in own or own[dependency].state is not StepState.DONE
        for dependency in record.dependencies
    )
    if progress.state is not StepState.PENDING or not waiting:
        return progress
    return StepProgress(
        id=progress.id,
        state=StepState.BLOCKED,
        landed=progress.landed,
        width=progress.width,
        failed=progress.failed,
    )


def read_progress(directory: RunDirectory, log: Path | None = None) -> RunProgress:
    """One reading of the run at ``directory``."""
    manifest = directory.read_manifest()
    reading = directory.read()
    running = directory.running()
    resolved_log = log if log is not None else default_log(directory)
    tally = Counter(result.label for result in reading.results)
    landed_by_step: defaultdict[str, list[UnitStatus]] = defaultdict(list)
    for result in reading.results:
        landed_by_step[result.step].append(result.status)
    total = manifest.total_units if manifest is not None else len(reading.results)
    elapsed = (
        (utc_now() - manifest.started_at).total_seconds()
        if manifest is not None
        else None
    )
    return RunProgress(
        directory=directory.root,
        name=manifest.name if manifest is not None else directory.root.name,
        total=total,
        landed=len(reading.results),
        failed=sum(
            1 for result in reading.results if result.status is UnitStatus.FAILED
        ),
        statuses=[
            StatusCount(status=status, count=count) for status, count in tally.items()
        ],
        running=running,
        steps=(
            step_progress(manifest, landed_by_step, running)
            if manifest is not None
            else []
        ),
        unreadable=reading.unreadable,
        heartbeat=latest_heartbeat(resolved_log),
        elapsed_seconds=elapsed,
        eta_seconds=remaining_estimate(total, len(reading.results), elapsed),
        quiet_for=silent_for(directory, resolved_log),
        summary=directory.read_summary(),
    )
