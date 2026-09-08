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


CLAIM_LEASE_SECONDS = 90.0
"""How long a claim stands without being renewed before nobody holds it.

Generous against the renewal interval rather than tight against it, because
the two failures are not symmetric: renewing late costs nothing, and calling a
live unit dead frees a claim somebody is working under. A machine that
suspended, a loaded host, and a runner between renewals all look the same from
here, so the window has to cover the worst of them.
"""


class RunningUnit(BaseModel, frozen=True):
    """A claimed unit, how long it has been going, and whether anybody holds it."""

    attempt: UnitAttempt
    age_seconds: float
    """How long since the unit was first claimed — how long it is taking."""

    since_renewed_seconds: float
    """How long since its holder last said it was still working it."""

    lease_seconds: float = CLAIM_LEASE_SECONDS

    @property
    def slug(self) -> str:
        """How this unit is named to a reader."""
        return self.attempt.slug

    @property
    def stale(self) -> bool:
        """Whether the lease has lapsed, so no runner is holding this unit.

        The one question age alone cannot answer. A unit running for two hours
        and a unit whose runner was killed two hours ago have the same age; only
        the renewal separates them.
        """
        return self.since_renewed_seconds > self.lease_seconds


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

    def renew(self, step: str, item: str = SINGLE_ITEM) -> None:
        """Say this unit is still being worked, without disturbing when it began.

        Re-stamping rather than re-claiming, so ``started_at`` goes on
        answering how long the unit is taking while ``renewed_at`` answers
        whether anybody is still on it. A claim that has since been released —
        the unit landed as this was called — is not resurrected: renewing what
        is gone would put a claim back on a finished unit.
        """
        held = self.parse_attempt(self.attempt_path(step, item))
        if held is None:
            return
        publish_atomic(
            self.attempt_path(step, item),
            held.model_copy(update={"renewed_at": utc_now()}),
        )

    def release(self, step: str, item: str = SINGLE_ITEM) -> None:
        """Drop a unit's claim, whether it landed or its runner gave up."""
        self.attempt_path(step, item).unlink(missing_ok=True)

    def running(self, lease_seconds: float = CLAIM_LEASE_SECONDS) -> list[RunningUnit]:
        """The units claimed and not landed, longest-running first.

        Every claim on disk, stale ones included, because a reader wants to see
        a unit nobody is holding rather than have it quietly omitted — a run
        whose process was killed reads as several stale claims and no live ones,
        which is the diagnosis.
        """
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
                    since_renewed_seconds=max(
                        0.0, (now - attempt.renewed_at).total_seconds()
                    ),
                    lease_seconds=lease_seconds,
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

    def clear_claims(self, lease_seconds: float = CLAIM_LEASE_SECONDS) -> list[str]:
        """Drop the claims nobody is holding, and say which those were.

        A resumed run calls this before starting: a claim left by a process that
        was killed would otherwise report a unit as running for as long as the
        directory survives, and a watcher has no way to see through it.

        Only the lapsed ones. Dropping every claim is right exactly once — when
        this is the only runner and the previous one is gone — and wrong the
        moment two share a directory, where it frees units a live sibling is
        working and lets both run them at once. The lease is what separates the
        cases, so nothing has to assume which it is in.
        """
        if not self.attempts_root.is_dir():
            return []
        lapsed = [unit for unit in self.running(lease_seconds) if unit.stale]
        for unit in lapsed:
            self.release(unit.attempt.step, unit.attempt.item)
        return [unit.slug for unit in lapsed]

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
