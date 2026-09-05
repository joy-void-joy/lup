"""What a declared pipeline does that a script of the same work cannot.

Three claims are pinned here, and they are the reason the runtime exists at
all. A step is not recomputed when nothing it rests on has changed, so a
resumed run costs only what never landed. A step *is* recomputed when its own
declaration changed, and so is everything downstream of it, without anybody
maintaining the list of what that is. And a failure stops at the steps that
read the failed one rather than taking down the run's whole record — the
units that did land stay landed, and the summary says which steps never ran.

The fourth claim is the one the monitor rests on: whatever happens, including
an exception on the way out, the directory ends up holding a manifest, a
result per landed unit, and a summary. A follower that found none of those
would be watching a run it could never report on.
"""

from pathlib import Path

import pytest

from lup.runs.ledger import RunDirectory
from lup.runs.models import UnitStatus
from lup.runs.pipeline import (
    CallableStep,
    ComputedItems,
    FanContext,
    FixedItems,
    Pipeline,
    PipelineError,
    RunRequest,
    ShellStep,
    StepContext,
    StepOutcome,
)

CALLS: dict[str, int] = {}


@pytest.fixture(autouse=True)
def forget_calls() -> None:
    """Each test counts only its own invocations."""
    CALLS.clear()


def counted(context: StepContext) -> StepOutcome:
    """Record that this step ran, and say it worked."""
    CALLS[context.step] = CALLS.get(context.step, 0) + 1
    return StepOutcome(outcome="done")


def refuses(context: StepContext) -> StepOutcome:
    """A body that always raises, for pinning what a failure does downstream."""
    CALLS[context.step] = CALLS.get(context.step, 0) + 1
    raise ValueError(f"{context.step}/{context.item} cannot be done")


def flaky(context: StepContext) -> StepOutcome:
    """Fail once, then succeed, for pinning that retries are recorded."""
    CALLS[context.step] = CALLS.get(context.step, 0) + 1
    if CALLS[context.step] < 2:
        raise ValueError("not yet")
    return StepOutcome(outcome="eventually")


def names(context: FanContext) -> list[str]:
    """Fan out over one item per unit the first step landed."""
    return [f"from-{result.item}" for result in context.dependencies["first"]]


def chain(params: str = "") -> Pipeline:
    """Three steps in a line, the middle one carrying a declared parameter."""
    return Pipeline(
        name="chain",
        steps=[
            CallableStep(id="first", body=counted),
            CallableStep(
                id="middle", dependencies=["first"], body=counted, params=params
            ),
            CallableStep(id="last", dependencies=["middle"], body=counted),
        ],
    )


def test_a_run_lands_every_step_and_records_how_it_ended(tmp_path: Path) -> None:
    summary = chain().execute(RunRequest(directory=tmp_path))
    run = RunDirectory(root=tmp_path)
    assert CALLS == {"first": 1, "middle": 1, "last": 1}
    assert summary.ok
    assert summary.landed == 3
    assert run.read_manifest() is not None
    assert run.read_summary() is not None
    assert [result.step for result in run.read().results] == [
        "first",
        "last",
        "middle",
    ]


def test_nothing_is_recomputed_when_nothing_has_changed(tmp_path: Path) -> None:
    chain().execute(RunRequest(directory=tmp_path))
    CALLS.clear()
    summary = chain().execute(RunRequest(directory=tmp_path))
    assert CALLS == {}
    assert summary.landed == 3


def test_changing_a_step_reruns_it_and_everything_downstream(tmp_path: Path) -> None:
    """And nothing upstream, which is the half a --force flag cannot know."""
    chain().execute(RunRequest(directory=tmp_path))
    CALLS.clear()
    chain(params="widened").execute(RunRequest(directory=tmp_path))
    assert CALLS == {"middle": 1, "last": 1}


def test_forcing_a_current_step_reruns_it_and_everything_downstream(
    tmp_path: Path,
) -> None:
    chain().execute(RunRequest(directory=tmp_path))
    CALLS.clear()
    chain().execute(RunRequest(directory=tmp_path, force=["middle"]))
    assert CALLS == {"middle": 1, "last": 1}


def test_only_runs_exactly_what_it_names(tmp_path: Path) -> None:
    chain().execute(RunRequest(directory=tmp_path))
    CALLS.clear()
    chain().execute(RunRequest(directory=tmp_path, only=["middle"], force=["middle"]))
    assert CALLS == {"middle": 1}


def test_from_picks_up_at_a_step_and_carries_on(tmp_path: Path) -> None:
    chain().execute(RunRequest(directory=tmp_path))
    CALLS.clear()
    chain().execute(
        RunRequest(directory=tmp_path, start_from="middle", force=["middle"])
    )
    assert CALLS == {"middle": 1, "last": 1}


def test_a_lost_result_is_the_only_thing_recomputed(tmp_path: Path) -> None:
    """A run killed halfway resumes at the units that never landed."""
    chain().execute(RunRequest(directory=tmp_path))
    RunDirectory(root=tmp_path).unit_path("last").unlink()
    CALLS.clear()
    chain().execute(RunRequest(directory=tmp_path))
    assert CALLS == {"last": 1}


def test_a_failure_skips_what_reads_it_and_keeps_what_landed(tmp_path: Path) -> None:
    pipeline = Pipeline(
        name="broken",
        steps=[
            CallableStep(id="first", body=counted),
            CallableStep(id="middle", dependencies=["first"], body=refuses),
            CallableStep(id="last", dependencies=["middle"], body=counted),
        ],
    )
    summary = pipeline.execute(RunRequest(directory=tmp_path))
    run = RunDirectory(root=tmp_path)
    assert not summary.ok
    assert summary.failed == 1
    assert [step.id for step in summary.skipped] == ["last"]
    assert CALLS == {"first": 1, "middle": 1}
    failed = run.read_result("middle")
    assert failed is not None
    assert failed.status is UnitStatus.FAILED
    assert "cannot be done" in failed.error
    assert run.read_result("first") is not None


def test_a_fixed_fan_out_lands_one_unit_per_item(tmp_path: Path) -> None:
    pipeline = Pipeline(
        name="sweep",
        workers=2,
        steps=[
            CallableStep(
                id="solve", over=FixedItems(items=["a", "b", "c"]), body=counted
            )
        ],
    )
    summary = pipeline.execute(RunRequest(directory=tmp_path))
    run = RunDirectory(root=tmp_path)
    assert summary.landed == 3
    assert CALLS == {"solve": 3}
    assert sorted(result.item for result in run.read().results) == ["a", "b", "c"]


def test_a_computed_fan_out_widens_the_manifest_once_it_resolves(
    tmp_path: Path,
) -> None:
    """A follower watches the total grow rather than being told a wrong one."""
    pipeline = Pipeline(
        name="discovered",
        steps=[
            CallableStep(id="first", over=FixedItems(items=["x", "y"]), body=counted),
            CallableStep(
                id="second",
                dependencies=["first"],
                over=ComputedItems(compute=names),
                body=counted,
            ),
        ],
    )
    pipeline.execute(RunRequest(directory=tmp_path))
    manifest = RunDirectory(root=tmp_path).read_manifest()
    assert manifest is not None
    second = manifest.step("second")
    assert second is not None
    assert sorted(second.items) == ["from-x", "from-y"]
    assert manifest.total_units == 4


def test_a_shell_step_keeps_the_whole_of_its_output_beside_the_result(
    tmp_path: Path,
) -> None:
    pipeline = Pipeline(
        name="shell",
        steps=[ShellStep(id="say", command='echo "$LUP_RUN_STEP is running"')],
    )
    summary = pipeline.execute(RunRequest(directory=tmp_path))
    assert summary.ok
    stdout = tmp_path / "artifacts" / "say" / "once" / "stdout.txt"
    assert stdout.read_text(encoding="utf-8").strip() == "say is running"


def test_a_failing_shell_step_fails_its_unit(tmp_path: Path) -> None:
    pipeline = Pipeline(name="shell", steps=[ShellStep(id="nope", command="exit 3")])
    summary = pipeline.execute(RunRequest(directory=tmp_path))
    assert not summary.ok
    failed = RunDirectory(root=tmp_path).read_result("nope")
    assert failed is not None
    assert failed.status is UnitStatus.FAILED


def test_a_retried_step_records_the_attempts_it_survived(tmp_path: Path) -> None:
    """A step that passes on its second try is not the same as one that passed."""
    pipeline = Pipeline(
        name="flaky", steps=[CallableStep(id="try", body=flaky, retries=1)]
    )
    summary = pipeline.execute(RunRequest(directory=tmp_path))
    assert summary.ok
    result = RunDirectory(root=tmp_path).read_result("try")
    assert result is not None
    assert result.status is UnitStatus.OK
    assert "not yet" in result.error


def test_fresh_discards_what_landed(tmp_path: Path) -> None:
    chain().execute(RunRequest(directory=tmp_path))
    CALLS.clear()
    chain().execute(RunRequest(directory=tmp_path, fresh=True))
    assert CALLS == {"first": 1, "middle": 1, "last": 1}


def test_naming_a_step_that_does_not_exist_says_so(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="no such step: ghost"):
        chain().execute(RunRequest(directory=tmp_path, only=["ghost"]))


def test_a_step_whose_input_never_landed_refuses_rather_than_guessing(
    tmp_path: Path,
) -> None:
    with pytest.raises(PipelineError, match="cannot run middle: first has landed"):
        chain().execute(RunRequest(directory=tmp_path, only=["middle"]))
