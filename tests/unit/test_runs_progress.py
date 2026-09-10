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

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from lup.channels.models import utc_now
from lup.runs.follow import UnitLines, phase_events, reporting_units
from lup.runs.directory import RunDirectory, progress_in, stdout_in
from lup.runs.models import (
    RunManifest,
    RunSummary,
    SkippedStep,
    StepRecord,
    UnitAttempt,
    UnitProgress,
    UnitResult,
    UnitStatus,
)
from lup.runs.progress import (
    RateTracker,
    StatusCount,
    StepState,
    UnitRate,
    latest_heartbeat,
    read_progress,
    remaining_estimate,
    render_count,
    render_detail,
    render_span,
    render_unit,
)
from lup.runs.report import ProgressThrottle, report_progress


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
    assert "bounded_unsat=1 unknown=2" in reading.postfix()
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
    assert "unknown=1 running=2" in reading.postfix()


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


def reports(run: RunDirectory, item: str, **fields: object) -> UnitProgress:
    """Publish one unit's reading of itself, past the throttle."""
    record = UnitProgress.model_validate(fields)
    run.write_progress("solve", item, record)
    return record


def test_a_units_own_reading_is_written_where_the_reader_looks(tmp_path: Path) -> None:
    """The path is spelled once, so the two doorways cannot disagree about it."""
    run = scheduled(tmp_path, width=2)
    written = report_progress(
        run.workspace("solve", "cell-0"),
        done=2460,
        total=6000,
        phase="fit",
        detail={"supports": 41},
    )
    assert written is not None
    assert run.progress_path("solve", "cell-0") == progress_in(
        run.workspace("solve", "cell-0")
    )
    assert run.read_progress_record("solve", "cell-0") == written
    assert run.read_progress_record("solve", "cell-1") is None


def test_a_report_inside_the_interval_is_dropped_rather_than_written(
    tmp_path: Path,
) -> None:
    """Progress is a sample, so the cheapest call site has to be the right one."""
    throttle = ProgressThrottle()
    workspace = tmp_path / "unit"
    first = report_progress(workspace, done=1, throttle=throttle)
    second = report_progress(workspace, done=2, throttle=throttle)
    assert first is not None
    assert second is None
    assert (
        UnitProgress.model_validate_json(
            progress_in(workspace).read_text(encoding="utf-8")
        ).done
        == 1
    )
    third = report_progress(workspace, done=3, interval=0.0, throttle=throttle)
    assert third is not None and third.done == 3


def test_one_units_chatter_does_not_silence_another(tmp_path: Path) -> None:
    """The stamp is per workspace, because units run at once and are unrelated."""
    throttle = ProgressThrottle()
    assert report_progress(tmp_path / "one", done=1, throttle=throttle) is not None
    assert report_progress(tmp_path / "two", done=1, throttle=throttle) is not None


def test_a_running_unit_carries_what_it_said_about_itself(tmp_path: Path) -> None:
    run = scheduled(tmp_path, width=3)
    claim(run, "cell-0", age_seconds=90)
    reports(run, "cell-0", done=2460, total=6000, phase="fit", detail={"supports": 41})
    reading = read_progress(run)
    assert reading.running[0].progress is not None
    assert render_unit(reading.running[0]) == (
        "solve/cell-0: 2460/6000 fit · supports=41"
    )


def test_a_unit_that_only_prints_falls_back_to_its_last_line(tmp_path: Path) -> None:
    """A shell step is readable without cooperating at all."""
    run = scheduled(tmp_path, width=3)
    claim(run, "cell-0", age_seconds=90)
    workspace = run.workspace("solve", "cell-0")
    workspace.mkdir(parents=True, exist_ok=True)
    stdout_in(workspace).write_text("solving\niteration 12 of 40\n", encoding="utf-8")
    unit = read_progress(run).running[0]
    assert unit.progress is None
    assert render_unit(unit) == "solve/cell-0: iteration 12 of 40"


def test_a_unit_that_says_nothing_shows_no_placeholder(tmp_path: Path) -> None:
    """All anybody can say about it is how long it has been going."""
    run = scheduled(tmp_path, width=3)
    claim(run, "cell-0", age_seconds=1200)
    unit = read_progress(run).running[0]
    assert unit.progress is None and unit.last_line == ""
    assert render_unit(unit) == "solve/cell-0: running for 0:20:00"


def test_detail_renders_as_sent_in_the_order_the_unit_put_it(tmp_path: Path) -> None:
    """The unit's own vocabulary, nothing filtered and nothing cut."""
    detail = {"supports": 41, "hinge": 0.0123, "ok": True, "note": "alpha"}
    assert render_detail(detail) == "supports=41 hinge=0.0123 ok=true note=alpha"
    assert render_detail({"shape": {"k": [1, 2]}}) == 'shape={"k":[1,2]}'


def test_a_unit_with_no_budget_reads_as_a_count(tmp_path: Path) -> None:
    assert render_count(UnitProgress(done=2460)) == "2460"
    assert render_count(UnitProgress(done=2460, total=6000)) == "2460/6000"
    assert UnitProgress(done=2460).fraction is None
    assert UnitProgress(done=3000, total=6000).fraction == 0.5


def test_the_rate_is_the_readers_because_only_it_holds_two_readings(
    tmp_path: Path,
) -> None:
    """One unit's own work advances steadily, so this estimate is honest."""
    run = scheduled(tmp_path, width=2)
    claim(run, "cell-0", age_seconds=60)
    reports(run, "cell-0", done=1200, total=6000)
    tracker = RateTracker()
    first = read_progress(run).running
    assert tracker.rates(first, now=100.0) == {}
    reports(run, "cell-0", done=1800, total=6000)
    second = read_progress(run).running
    paced = tracker.rates(second, now=160.0)
    assert paced["solve/cell-0"] == UnitRate(per_second=10.0, remaining_seconds=420.0)
    assert paced["solve/cell-0"].render() == "10.0 steps/s · eta 0:07:00"
    assert UnitRate(per_second=41 / 60).render() == "41 steps/min"


def test_a_landed_unit_is_forgotten_rather_than_remembered_forever(
    tmp_path: Path,
) -> None:
    run = scheduled(tmp_path, width=2)
    claim(run, "cell-0", age_seconds=60)
    reports(run, "cell-0", done=1200, total=6000)
    tracker = RateTracker()
    tracker.rates(read_progress(run).running, now=100.0)
    assert "solve/cell-0" in tracker.seen
    land(run, "cell-0")
    tracker.rates(read_progress(run).running, now=160.0)
    assert tracker.seen == {}


def test_the_clock_reads_as_a_bar_does_rather_than_as_two_tallies(
    tmp_path: Path,
) -> None:
    """Elapsed against the time left, where a reader's eye already goes."""
    run = scheduled(tmp_path, width=4)
    land(run, "cell-0", "unknown")
    reading = read_progress(run)
    assert reading.postfix().startswith("[0:00:00<0:00:0")
    assert "eta=" not in reading.postfix()
    empty = read_progress(RunDirectory(root=tmp_path / "nothing"))
    assert empty.render_clock() == ""


def test_a_finished_runs_elapsed_stops_at_its_ending(tmp_path: Path) -> None:
    """Otherwise a directory read a day later reports a day of work."""
    run = scheduled(tmp_path, width=1)
    land(run, "cell-0")
    manifest = run.read_manifest()
    assert manifest is not None
    run.write_summary(
        RunSummary(
            name="sweep",
            finished_at=manifest.started_at + timedelta(seconds=930),
            landed=1,
            failed=0,
        )
    )
    reading = read_progress(run)
    assert reading.elapsed_seconds == 930.0
    assert reading.eta_seconds == 0.0
    assert reading.postfix().startswith("[0:15:30<0:00:00]")


def test_the_watcher_hears_a_phase_change_and_never_a_count(tmp_path: Path) -> None:
    """An agent following a thousand-unit sweep is woken by changes, not samples."""
    run = scheduled(tmp_path, width=2)
    claim(run, "cell-0", age_seconds=30)
    reports(run, "cell-0", done=1200, total=6000, phase="fit")
    entered = read_progress(run)
    assert list(phase_events(entered, {})) == ["solve/cell-0 entered fit at 1200/6000"]
    known = reporting_units(entered)
    reports(run, "cell-0", done=2400, total=6000, phase="fit")
    assert list(phase_events(read_progress(run), known)) == []
    reports(run, "cell-0", done=3000, total=6000, phase="eval")
    assert list(phase_events(read_progress(run), known)) == [
        "solve/cell-0 entered eval at 3000/6000"
    ]


def test_a_unit_naming_no_phase_yields_no_line(tmp_path: Path) -> None:
    run = scheduled(tmp_path, width=2)
    claim(run, "cell-0", age_seconds=30)
    reports(run, "cell-0", done=1200, total=6000)
    assert list(phase_events(read_progress(run), {})) == []


def test_a_budget_draws_a_bar_and_its_absence_draws_a_count(tmp_path: Path) -> None:
    run = scheduled(tmp_path, width=2)
    claim(run, "cell-0", age_seconds=60)
    claim(run, "cell-1", age_seconds=30)
    reports(run, "cell-0", done=10, total=40)
    reports(run, "cell-1", done=10)
    lines = UnitLines(below=3, limit=12)
    assert lines.refresh(read_progress(run).running, {}) == 0
    drawn = {slug: line.bar.bar_format for slug, line in lines.lines.items()}
    assert "{bar}" in drawn["solve/cell-0"]
    assert "{bar}" not in drawn["solve/cell-1"]
    lines.close()


def test_a_landed_units_row_is_the_next_one_handed_out(tmp_path: Path) -> None:
    """A sweep redraws in place rather than walking off the bottom of a screen."""
    run = scheduled(tmp_path, width=3)
    for index, age in enumerate([90.0, 60.0, 30.0]):
        claim(run, f"cell-{index}", age_seconds=age)
        reports(run, f"cell-{index}", done=index, total=10)
    lines = UnitLines(below=3, limit=2)
    running = read_progress(run).running
    assert lines.refresh(running, {}) == 1
    assert {slug: line.position for slug, line in lines.lines.items()} == {
        "solve/cell-0": 3,
        "solve/cell-1": 4,
    }
    assert lines.refresh([running[0], running[2]], {}) == 0
    assert {slug: line.position for slug, line in lines.lines.items()} == {
        "solve/cell-0": 3,
        "solve/cell-2": 4,
    }
    lines.close()
    assert lines.lines == {}


def test_the_throttle_holds_when_a_unit_reports_from_several_threads(
    tmp_path: Path,
) -> None:
    """A step reporting from a worker pool is the ordinary case, not the odd one."""
    throttle = ProgressThrottle()
    shared = tmp_path / "one-unit"
    with ThreadPoolExecutor(max_workers=8) as pool:
        burst = list(
            pool.map(
                lambda done: report_progress(
                    shared, done=done, interval=60.0, throttle=throttle
                ),
                range(400),
            )
        )
    assert len([record for record in burst if record is not None]) == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        spread = list(
            pool.map(
                lambda index: report_progress(
                    tmp_path / f"unit-{index}",
                    done=1,
                    interval=60.0,
                    throttle=ProgressThrottle(),
                ),
                range(8),
            )
        )
    assert len([record for record in spread if record is not None]) == 8
