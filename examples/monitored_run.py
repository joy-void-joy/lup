"""A long job declared as a pipeline, so it can be resumed and watched.

Three shapes in one composition: a shell step, a fan-out whose width is read
off what that step found, and a reduce over the fan-out. Nothing here calls a
model, so it runs anywhere.

    uv run -m examples.monitored_run plan
    uv run -m examples.monitored_run run
    uv run lup-devtools dev monitor tmp/runs/monitored-run --events

Run it twice and the second run does nothing: every step's fingerprint still
matches what landed. Edit ``measure`` and run it again, and ``measure`` and
``report`` recompute while ``discover`` does not — the fingerprint of a step
folds in its dependencies', so changing one part invalidates exactly what
rests on it. ``--only``, ``--from`` and ``--force`` reach in by hand when the
declaration has not changed but you want the work done again anyway.
"""

from lup.runs.pipeline import (
    CallableStep,
    ComputedItems,
    FanContext,
    Pipeline,
    ShellStep,
    StepContext,
    StepOutcome,
)


def discovered_words(context: FanContext) -> list[str]:
    """One item per word the discover step printed.

    A fan-out this shape is why the manifest is rewritten rather than written
    once: nobody knows how wide this run is until ``discover`` has landed, and
    a follower watching the total grow is being told the truth as it is known.
    """
    landed = context.dependencies["discover"][0]
    return (
        (context.artifacts_of(landed) / "stdout.txt")
        .read_text(encoding="utf-8")
        .split()
    )


def measure(context: StepContext) -> StepOutcome:
    """Measure one word, and say which bucket it fell in.

    The outcome is the word this unit is tallied under by anybody watching, so
    ``dev monitor`` reports ``long=2 short=3`` rather than ``ok=5``.
    """
    width = len(context.item)
    (context.workspace / "width.txt").write_text(str(width), encoding="utf-8")
    return StepOutcome(
        outcome="long" if width > 5 else "short", detail={"width": width}
    )


def report(context: StepContext) -> StepOutcome:
    """Add up what the fan-out measured."""
    widths = [
        int((context.artifacts_of(result) / "width.txt").read_text(encoding="utf-8"))
        for result in context.dependencies["measure"]
    ]
    (context.workspace / "total.txt").write_text(str(sum(widths)), encoding="utf-8")
    return StepOutcome(outcome="summed", detail={"total": sum(widths)})


pipeline = Pipeline(
    name="monitored-run",
    workers=4,
    steps=[
        ShellStep(id="discover", command="printf 'alpha bravo charlie delta echo'"),
        CallableStep(
            id="measure",
            dependencies=["discover"],
            over=ComputedItems(compute=discovered_words),
            body=measure,
        ),
        CallableStep(id="report", dependencies=["measure"], body=report),
    ],
)


if __name__ == "__main__":
    pipeline.main()
