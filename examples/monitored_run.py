"""A long job declared as a pipeline, so it can be resumed and watched.

Three shapes in one composition: a shell step, a fan-out whose width is read
off what that step found, and a reduce over the fan-out. Nothing here calls a
model, so it runs anywhere.

    uv run -m examples.monitored_run plan
    uv run -m examples.monitored_run run
    uv run lup-devtools run monitor tmp/runs/monitored-run --events

Run it twice and the second run does nothing: every step's fingerprint still
matches what landed. Edit ``measure`` and run it again, and ``measure`` and
``report`` recompute while ``discover`` does not — the fingerprint of a step
folds in its dependencies', so changing one part invalidates exactly what
rests on it. ``--only``, ``--from`` and ``--force`` reach in by hand when the
declaration has not changed but you want the work done again anyway.

Both progress doorways are exercised: ``measure`` calls ``context.report``
from inside its own loop, and ``discover`` — a shell step — spawns
``run report``. Watch it while it runs and each unit shows how far into its
own work it is, rather than only how long it has been claimed.
"""

import time

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
    """Measure one word, saying how far in it is as it goes.

    The outcome is the word this unit is tallied under by anybody watching, so
    ``dev monitor`` reports ``long=2 short=3`` rather than ``ok=5``.

    ``report`` is the other half: without it a unit that takes a while is, to
    a watcher, only a claim and an age. Called from the loop that does the
    work rather than at chosen milestones — a report landing inside a second
    of the one before it is dropped, so the cheapest call site is the right
    one. The sleep is what makes this example worth watching at all; real work
    supplies its own.
    """
    for index, letter in enumerate(context.item):
        time.sleep(0.2)
        context.report(
            done=index + 1,
            total=len(context.item),
            phase="scan",
            detail={"letter": letter},
        )
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
        ShellStep(
            id="discover",
            # The doorway for a unit that cannot import this library: it reads
            # $LUP_RUN_WORKSPACE itself, so the command names no path either.
            command=(
                "uv run lup-devtools run report --done 1 --total 1 --phase list\n"
                "printf 'alpha bravo charlie delta echo'"
            ),
        ),
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
