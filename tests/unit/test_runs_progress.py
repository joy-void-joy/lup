"""What a follower can say about a run it is only allowed to read.

These pin the reading, not the running: a directory in the shape a runtime
produces, and the account a monitor gives of it. Two of them are the point of
the whole reader. The estimate of the time left is taken over the whole run
rather than over the last few landings, because units land in bursts — one
per worker as a batch of budgets expires — and a smoothed rate read off one
burst put the time left for thirty-six two-hour cells at twenty-nine seconds.
And the activity line never repeats a runner's own estimate: what it says
instead is how many units are running and how long the oldest has been at it,
which is the thing that estimate was crowding out.
"""

from datetime import timedelta
from pathlib import Path

from lup.channels.models import utc_now
from lup.runs.ledger import RunDirectory
from lup.runs.models import (
    RunManifest,
    RunSummary,
    SkippedStep,
    StepRecord,
    UnitAttempt,
    UnitResult,
    UnitStatus,
)
from lup.runs.progress import (
    StatusCount,
    StepState,
    latest_heartbeat,
    read_progress,
    remaining_estimate,
    render_span,
)


def scheduled(
    root: Path, width: int, dependencies: list[str] | None = None
) -> RunDirectory:
    """A run directory declaring one fanned-out step, as a runtime would."""
    run = RunDirectory(root=root)
    run.write_manifest(
        RunManifest(
            name="sweep",
            steps=[
                StepRecord(
                    id="solve",
                    fingerprint="f",
                    kind="callable",
                    items=[f"cell-{index}" for index in range(width)],
                    dependencies=dependencies or [],
                )
            ],
        )
    )
    return run


def land(run: RunDirectory, item: str, outcome: str = "") -> None:
    """Land one unit the way the runtime does."""
    now = utc_now()
    run.write_result(
        UnitResult(
            step="solve",
            item=item,
            status=UnitStatus.OK,
            outcome=outcome,
            fingerprint="f",
            started_at=now,
            finished_at=now,
        )
    )


def claim(run: RunDirectory, item: str, age_seconds: float) -> None:
    """Claim a unit as a runner does when it starts, aged into the past."""
    run.claim(
        UnitAttempt(
            step="solve",
            item=item,
            started_at=utc_now() - timedelta(seconds=age_seconds),
            pid=1,
        )
    )


def test_progress_counts_landed_units_against_the_manifest(tmp_path: Path) -> None:
    run = scheduled(tmp_path, width=5)
    land(run, "cell-0", "unknown")
    land(run, "cell-1", "bounded_unsat")
    land(run, "cell-2", "unknown")
    reading = read_progress(run)
    assert reading.total == 5
    assert reading.landed == 3
    assert sorted(reading.statuses, key=lambda entry: entry.status) == [
        StatusCount(status="bounded_unsat", count=1),
        StatusCount(status="unknown", count=2),
    ]
    assert reading.postfix().startswith("bounded_unsat=1 unknown=2 elapsed=")
    assert reading.eta_seconds is not None
    assert not reading.complete
    assert reading.describe_activity() == "(no unit running yet)"


def test_activity_reports_the_oldest_running_unit_not_a_runner_estimate(
    tmp_path: Path,
) -> None:
    run = scheduled(tmp_path, width=4)
    land(run, "cell-0", "unknown")
    claim(run, "cell-1", age_seconds=30)
    claim(run, "cell-2", age_seconds=1200)
    reading = read_progress(run)
    assert [unit.slug for unit in reading.running] == ["solve/cell-2", "solve/cell-1"]
    assert reading.describe_activity() == ("2 running; oldest solve/cell-2 for 0:20:00")
    assert reading.postfix().startswith("unknown=1 running=2 elapsed=")


def test_landing_a_unit_drops_the_claim_that_said_it_was_running(
    tmp_path: Path,
) -> None:
    """No instant exists in which a unit is neither claimed nor landed."""
    run = scheduled(tmp_path, width=2)
    claim(run, "cell-0", age_seconds=5)
    assert len(read_progress(run).running) == 1
    land(run, "cell-0")
    assert read_progress(run).running == []


def test_heartbeat_is_the_last_carriage_return_segment(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_bytes(
        b"sweep:  0%|   | 0/3\rsweep: 33%|#  | 1/3 [00:10]\rsweep: 66%|## | 2/3 [00:20]"
    )
    assert latest_heartbeat(log) == "sweep: 66%|## | 2/3 [00:20]"
    assert latest_heartbeat(tmp_path / "missing.log") == ""
    assert latest_heartbeat(None) == ""


def test_the_heartbeat_is_the_fallback_only_when_nothing_is_running(
    tmp_path: Path,
) -> None:
    run = scheduled(tmp_path, width=3)
    land(run, "cell-0")
    run.append_heartbeat("working: 1 landed, 0 running")
    reading = read_progress(run)
    assert reading.oldest_running is None
    assert reading.describe_activity() == "working: 1 landed, 0 running"


def test_a_finished_run_reads_from_its_summary_not_from_the_count(
    tmp_path: Path,
) -> None:
    """A pipeline that failed never reaches its total, so the count cannot end it."""
    run = scheduled(tmp_path, width=4)
    land(run, "cell-0")
    assert not read_progress(run).finished
    run.write_summary(
        RunSummary(
            name="sweep",
            landed=1,
            failed=1,
            skipped=[SkippedStep(id="report", reason="depends on solve")],
        )
    )
    reading = read_progress(run)
    assert reading.finished
    assert not reading.complete
    assert reading.describe_activity() == "run failed: 1 unit failed; skipped report"


def test_an_unreadable_result_is_named_rather_than_tallied(tmp_path: Path) -> None:
    """A failed unit is the run working; a file that will not parse is not."""
    run = scheduled(tmp_path, width=2)
    land(run, "cell-0")
    (run.units_root / "solve" / "cell-1.json").write_text("{oops", encoding="utf-8")
    reading = read_progress(run)
    assert reading.landed == 1
    assert [path.name for path in reading.unreadable] == ["cell-1.json"]
    assert "unreadable=1" in reading.postfix()


def test_a_step_waiting_on_another_reads_as_blocked(tmp_path: Path) -> None:
    run = RunDirectory(root=tmp_path)
    run.write_manifest(
        RunManifest(
            name="chain",
            steps=[
                StepRecord(id="first", fingerprint="a", kind="shell", items=["once"]),
                StepRecord(
                    id="second",
                    dependencies=["first"],
                    fingerprint="b",
                    kind="shell",
                    items=["once"],
                ),
            ],
        )
    )
    states = {step.id: step.state for step in read_progress(run).steps}
    assert states == {"first": StepState.PENDING, "second": StepState.BLOCKED}


def test_remaining_estimate_is_the_global_average_not_the_last_burst() -> None:
    """Thirty-six two-hour cells over eight workers in nine hours: nine more."""
    assert remaining_estimate(72, 36, 9 * 3600) == 9 * 3600
    assert remaining_estimate(72, 0, 9 * 3600) is None
    assert remaining_estimate(72, 36, None) is None
    assert remaining_estimate(72, 72, 18 * 3600) == 0.0
    assert render_span(9 * 3600 + 61) == "9:01:01"


def test_a_run_gone_quiet_is_distinguishable_from_one_still_working(
    tmp_path: Path,
) -> None:
    run = scheduled(tmp_path, width=3)
    land(run, "cell-0")
    reading = read_progress(run)
    assert not reading.stalled(quiet_limit=60)
    assert reading.stalled(quiet_limit=0)
