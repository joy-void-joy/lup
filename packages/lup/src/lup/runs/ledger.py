"""The one place a run's writer and its readers meet: a directory.

Neither end holds the other. A run writes here and never learns who is
watching; a monitor reads here and never touches what it is watching, so
following a job cannot perturb it and several people may follow the same one.
That is why every path is spelled once, in this class, rather than in the
runtime and again in the reader — the two would drift, and the failure would
be a monitor that quietly reports nothing rather than one that errors.

Every write goes through :func:`lup.channels.models.publish_atomic`, because
a reader holds no lock: it either sees a complete record or none.
"""

import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError

from lup.channels.models import publish_atomic, utc_now
from lup.runs.models import (
    SINGLE_ITEM,
    RunManifest,
    RunSummary,
    UnitAttempt,
    UnitResult,
)

logger = logging.getLogger(__name__)


class RunningUnit(BaseModel, frozen=True):
    """A claimed unit and how long it has been claimed."""

    attempt: UnitAttempt
    age_seconds: float

    @property
    def slug(self) -> str:
        """How this unit is named to a reader."""
        return self.attempt.slug


class LedgerReading(BaseModel, frozen=True):
    """Every unit that has landed, and every file that could not be read.

    Unreadable files are carried rather than counted into a status, because
    the two mean different things to whoever is watching: a failed unit is the
    run working, and a file that will not parse is the run, the disk, or this
    reader being wrong. Naming the paths is what lets somebody go look.
    """

    results: list[UnitResult] = []
    unreadable: list[Path] = []


class RunDirectory(BaseModel, frozen=True):
    """One run's evidence on disk, addressed the same way by both ends."""

    root: Path

    @property
    def manifest_path(self) -> Path:
        """Where the scheduled units are declared."""
        return self.root / "manifest.json"

    @property
    def units_root(self) -> Path:
        """Where one result per landed unit goes."""
        return self.root / "units"

    @property
    def attempts_root(self) -> Path:
        """Where one claim per running unit goes."""
        return self.root / "attempts"

    @property
    def log_path(self) -> Path:
        """Where the run's own heartbeat goes, one line per thing that happened."""
        return self.root / "run.log"

    def unit_path(self, step: str, item: str = SINGLE_ITEM) -> Path:
        """Where one unit's result lives."""
        return self.units_root / step / f"{item}.json"

    def attempt_path(self, step: str, item: str = SINGLE_ITEM) -> Path:
        """Where one unit's claim lives while it runs."""
        return self.attempts_root / step / f"{item}.json"

    def workspace(self, step: str, item: str = SINGLE_ITEM) -> Path:
        """Where one unit puts whatever it produces besides its result.

        Spelled here rather than by whoever wants it, because a later step
        reading what an earlier one wrote is the ordinary case: two ends
        computing the same path by hand is how they stop agreeing.
        """
        return self.root / "artifacts" / step / item

    def write_manifest(self, manifest: RunManifest) -> None:
        """Record what this run scheduled, replacing any earlier declaration."""
        publish_atomic(self.manifest_path, manifest)

    def read_manifest(self) -> RunManifest | None:
        """What this run scheduled, or None when nothing has declared it yet."""
        if not self.manifest_path.is_file():
            return None
        try:
            return RunManifest.model_validate_json(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except (ValidationError, OSError) as error:
            logger.warning("unreadable manifest at %s: %s", self.manifest_path, error)
            return None

    def write_result(self, result: UnitResult) -> None:
        """Land one unit and drop its claim, in that order.

        The claim goes second so no instant exists in which a reader can see
        neither: a unit is running until the moment it has landed.
        """
        publish_atomic(self.unit_path(result.step, result.item), result)
        self.release(result.step, result.item)

    def read_result(self, step: str, item: str = SINGLE_ITEM) -> UnitResult | None:
        """One landed unit, or None when it has not landed or will not parse."""
        path = self.unit_path(step, item)
        if not path.is_file():
            return None
        try:
            return UnitResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError) as error:
            logger.warning("unreadable unit result at %s: %s", path, error)
            return None

    def read(self) -> LedgerReading:
        """Every unit that has landed, in a stable order, with the failures to read."""
        if not self.units_root.is_dir():
            return LedgerReading()
        readings = [
            (path, self.parse_result(path))
            for path in sorted(self.units_root.glob("*/*.json"))
        ]
        return LedgerReading(
            results=[result for _, result in readings if result is not None],
            unreadable=[path for path, result in readings if result is None],
        )

    def parse_result(self, path: Path) -> UnitResult | None:
        """One result file, or None when it will not parse."""
        try:
            return UnitResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError) as error:
            logger.warning("unreadable unit result at %s: %s", path, error)
            return None

    def claim(self, attempt: UnitAttempt) -> None:
        """Record that a unit has started."""
        publish_atomic(self.attempt_path(attempt.step, attempt.item), attempt)

    def release(self, step: str, item: str = SINGLE_ITEM) -> None:
        """Drop a unit's claim, whether it landed or its runner gave up."""
        self.attempt_path(step, item).unlink(missing_ok=True)

    def running(self) -> list[RunningUnit]:
        """The units claimed and not landed, longest-running first."""
        if not self.attempts_root.is_dir():
            return []
        now = utc_now()
        claimed = [
            self.parse_attempt(path)
            for path in sorted(self.attempts_root.glob("*/*.json"))
        ]
        return sorted(
            (
                RunningUnit(
                    attempt=attempt,
                    age_seconds=max(0.0, (now - attempt.started_at).total_seconds()),
                )
                for attempt in claimed
                if attempt is not None
            ),
            key=lambda unit: unit.age_seconds,
            reverse=True,
        )

    def parse_attempt(self, path: Path) -> UnitAttempt | None:
        """One claim file, or None when it will not parse."""
        try:
            return UnitAttempt.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, OSError) as error:
            logger.warning("unreadable attempt at %s: %s", path, error)
            return None

    def clear_claims(self) -> None:
        """Drop every claim left behind by a runner that did not finish.

        A resumed run calls this before starting: the claims on disk belong to
        a process that is gone, and left in place they would report units as
        running for as long as the directory survives.
        """
        if not self.attempts_root.is_dir():
            return
        for path in sorted(self.attempts_root.glob("*/*.json")):
            path.unlink(missing_ok=True)

    def append_heartbeat(self, line: str) -> None:
        """Add one line to the run's log, which is what a follower re-reads.

        The runtime writes this itself rather than relying on the launch line
        redirecting a terminal: a run is monitorable because of what it does,
        not because of how somebody remembered to start it.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    @property
    def summary_path(self) -> Path:
        """Where the runtime records that the run is over, however it ended."""
        return self.root / "summary.json"

    def write_summary(self, summary: RunSummary) -> None:
        """Record that this run has ended."""
        publish_atomic(self.summary_path, summary)

    def read_summary(self) -> RunSummary | None:
        """How the run ended, or None while it is still going or was killed."""
        if not self.summary_path.is_file():
            return None
        try:
            return RunSummary.model_validate_json(
                self.summary_path.read_text(encoding="utf-8")
            )
        except (ValidationError, OSError) as error:
            logger.warning("unreadable summary at %s: %s", self.summary_path, error)
            return None
