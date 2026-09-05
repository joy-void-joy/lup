"""Two ways to watch a run, because two kinds of watcher want opposite things.

A person at a second terminal wants one screen that stays put and always
shows now: a bar that advances, a step line that changes, an activity line
that says what is being worked on. Redrawing in place is exactly right, and a
transcript of every redraw would be unreadable.

An agent wants the opposite. It cannot see a screen, and a bar rewritten in
place is invisible to it; what reaches it is a line at a time, so a watch
that emits one line per thing that happened — and stops when the run is over
— turns a long job into events it is woken for instead of something it has to
keep asking about. Silence is the failure mode there, so this face reports
what it means when nothing has happened for a long time, and reports a
failure as loudly as a landing.
"""

import time
from collections.abc import Iterator
from pathlib import Path

from tqdm import tqdm

from lup.runs.ledger import RunDirectory
from lup.runs.models import UnitResult
from lup.runs.progress import (
    RunProgress,
    StepState,
    default_log,
    describe_summary,
    read_progress,
    render_span,
)


def render_steps(progress: RunProgress) -> str:
    """Every step and where it stands, on one line.

    Empty for a run with a single step, whose bar already says everything a
    step line would repeat.
    """
    if len(progress.steps) <= 1:
        return ""
    return " · ".join(step.render() for step in progress.steps)


def render_landing(result: UnitResult) -> str:
    """One landed unit as a line whoever is following should be able to act on."""
    span = render_span(result.elapsed_seconds)
    head = f"{result.status.value} {result.slug} in {span}"
    if result.outcome:
        head = f"{head} ({result.outcome})"
    if result.error:
        return f"{head}: {result.error}"
    return head


def follow(
    directory: RunDirectory,
    log: Path | None = None,
    interval: float = 2.0,
    once: bool = False,
) -> RunProgress:
    """Render the run in place until it ends; return the last reading.

    Three lines: the units landed against the units scheduled with the
    monitor's own elapsed and time-left, the steps and where each stands, and
    what the run is doing right now. None of them reproduces the runner's own
    smoothed estimate.
    """
    resolved_log = log if log is not None else default_log(directory)
    reading = read_progress(directory, resolved_log)
    units_bar = tqdm(
        total=max(reading.total, reading.landed),
        initial=reading.landed,
        desc=f"{reading.name}: units",
        unit="unit",
        position=0,
        dynamic_ncols=True,
        smoothing=0,
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} {postfix}",
    )
    steps_line = tqdm(total=0, bar_format="{desc}", position=1, dynamic_ncols=True)
    activity_line = tqdm(total=0, bar_format="{desc}", position=2, dynamic_ncols=True)
    try:
        while True:
            units_bar.total = max(reading.total, reading.landed)
            units_bar.n = reading.landed
            units_bar.set_postfix_str(reading.postfix())
            units_bar.refresh()
            steps_line.set_description_str(render_steps(reading))
            activity_line.set_description_str(reading.describe_activity())
            if once or reading.finished:
                break
            time.sleep(interval)
            reading = read_progress(directory, resolved_log)
    finally:
        activity_line.close()
        steps_line.close()
        units_bar.close()
    return reading


def follow_events(
    directory: RunDirectory,
    log: Path | None = None,
    interval: float = 2.0,
    quiet_limit: float = 900.0,
) -> Iterator[str]:
    """Yield one line per thing that happens, ending when the run does.

    The first line is a baseline rather than a replay: attaching to a run that
    already landed four hundred units should say so once, not four hundred
    times. Everything after it is a change — a unit landing, a step moving, the
    run ending, or nothing happening for longer than ``quiet_limit``, which on
    a run whose heartbeat has stopped is the only evidence there will ever be.
    """
    resolved_log = log if log is not None else default_log(directory)
    reading = read_progress(directory, resolved_log)
    landed = {result.slug: result for result in directory.read().results}
    states: dict[str, StepState] = {step.id: step.state for step in reading.steps}
    yield f"attached {reading.landed}/{reading.total} landed · {reading.postfix()}"
    reported_stall = False
    while True:
        summary = reading.summary
        if summary is not None:
            yield describe_summary(summary)
            return
        if reading.stalled(quiet_limit) and not reported_stall:
            reported_stall = True
            quiet = render_span(reading.quiet_for or 0.0)
            yield f"stalled: nothing has changed for {quiet}; the runner may be gone"
        time.sleep(interval)
        reading = read_progress(directory, resolved_log)
        for result in directory.read().results:
            if result.slug not in landed:
                landed[result.slug] = result
                yield render_landing(result)
        for step in reading.steps:
            if states.get(step.id) is not step.state:
                states[step.id] = step.state
                yield f"step {step.render()}"
        reported_stall = reported_stall and reading.stalled(quiet_limit)
