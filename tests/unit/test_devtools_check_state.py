"""A check that has not finished is neither passing nor failing.

``dev pr status`` reported `checks_passing: true` for a PR whose only check
was `IN_PROGRESS`, because filtering to the completed checks left `all()`
nothing to disagree with. The check concluded as a failure minutes later, and
a `/lup:land` sweep had already presented that branch as the clean one of
three. These pin the third answer and the readers that meet it.
"""

import json

import pytest

from lup.devtools.dev import pr
from lup.devtools import utils


class Recorder:
    """A stand-in for the `gh` command answering a scripted body per call."""

    def __init__(self, outputs: list[str]) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.outputs = outputs

    def __call__(self, *arguments: str) -> str:
        self.calls.append(arguments)
        return self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]

    def out(self, *arguments: str) -> str:
        return self(*arguments)


def check(name: str, status: str, conclusion: str) -> pr.CheckInfo:
    return pr.CheckInfo(name=name, status=status, conclusion=conclusion)


def test_a_running_check_is_reported_as_running() -> None:
    """The case that shipped the wrong answer: one check, still going."""
    assert (
        pr.rollup_state([check("check", "IN_PROGRESS", "")]) is pr.ChecksState.running
    )


def test_a_running_check_beside_a_passing_one_holds_the_answer_open() -> None:
    running = [check("lint", "COMPLETED", "SUCCESS"), check("test", "QUEUED", "")]

    assert pr.rollup_state(running) is pr.ChecksState.running


def test_a_concluded_failure_settles_the_run_whatever_else_is_going() -> None:
    """A failure is final, so waiting on the rest would not change it."""
    mixed = [check("lint", "COMPLETED", "FAILURE"), check("test", "IN_PROGRESS", "")]

    assert pr.rollup_state(mixed) is pr.ChecksState.failing


def test_finished_checks_that_did_not_fail_are_passing() -> None:
    settled = [
        check("lint", "COMPLETED", "SUCCESS"),
        check("docs", "COMPLETED", "SKIPPED"),
        check("size", "COMPLETED", "NEUTRAL"),
    ]

    assert pr.rollup_state(settled) is pr.ChecksState.passing
    assert pr.rollup_state([]) is pr.ChecksState.passing


def test_each_state_prints_its_own_marker() -> None:
    """A running check printed with the failing marker is the same lie twice."""
    markers = {state.marker() for state in pr.ChecksState}

    assert len(markers) == len(pr.ChecksState)


def scripted_gh(monkeypatch: pytest.MonkeyPatch, checks: list[dict[str, str]]) -> None:
    """Answer the two `gh` queries `pr.status` makes, in the order it makes them."""
    listing = json.dumps([{"number": 193, "title": "feat: thing", "url": "u"}])
    detail = json.dumps({"statusCheckRollup": checks, "reviews": []})
    monkeypatch.setattr(utils, "repository_slug", lambda: "owner/name")
    monkeypatch.setattr(pr, "gh", Recorder([listing, detail]))


def test_the_status_command_reports_the_unfinished_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The JSON a sweep reads carries `running`, not a truthy field."""
    scripted_gh(
        monkeypatch, [{"name": "check", "status": "IN_PROGRESS", "conclusion": ""}]
    )

    pr.status(branch="fix-rebase-command", as_json=True)

    reported = json.loads(capsys.readouterr().out)
    assert reported["pr"]["checks_state"] == "running"
