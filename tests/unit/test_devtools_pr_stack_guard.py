"""Behavior tests for how `dev pr merge` meets a stacked PR.

A stacked PR's base is its stack parent, so merging it as-is lands the work
in another feature branch while the command pulls the integration branch and
reads nothing arriving. The forge only marks a request merged when a push to
its own base carries its head, and retargeting is refused once the head is
contained — so the retarget has to happen before the merge, and a merge that
would land somewhere unexpected has to say so instead of proceeding.
"""

import json

import pytest
import typer

from lup.devtools.dev import pr


class RecordingGh:
    """A `gh` that answers PR facts from a script and records every call."""

    def __init__(self, base_ref: str) -> None:
        self.base_ref = base_ref
        self.calls: list[tuple[str, ...]] = []

    def out(self, *args: str) -> str:
        self.calls.append(args)
        if "baseRefName" in args:
            return json.dumps({"baseRefName": self.base_ref})
        if "headRefName" in args:
            return json.dumps({"headRefName": ""})
        return "{}"

    def __call__(self, *args: str) -> None:
        self.calls.append(args)
        if args[:2] == ("pr", "edit") and "--base" in args:
            self.base_ref = args[args.index("--base") + 1]

    def verbs(self) -> list[tuple[str, str]]:
        return [call[:2] for call in self.calls if len(call) >= 2]


@pytest.fixture
def forge(monkeypatch: pytest.MonkeyPatch) -> RecordingGh:
    """A merge whose forge is scripted and whose checkout is not consulted."""
    gh = RecordingGh(base_ref="feat-parent")
    monkeypatch.setattr(pr, "gh", gh)
    monkeypatch.setattr(pr, "get_integration_branch", lambda: "main")
    monkeypatch.setattr(pr, "parse_worktrees", lambda: {})
    return gh


def test_a_stacked_pr_is_refused_rather_than_merged_into_its_parent(
    forge: RecordingGh, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(typer.Exit):
        pr.merge(7, dry_run=False, as_json=True)
    assert ("pr", "merge") not in forge.verbs()
    said = capsys.readouterr().err
    assert "feat-parent" in said
    assert "--retarget" in said


def test_retargeting_points_the_base_at_the_integration_branch_first(
    forge: RecordingGh,
) -> None:
    pr.merge(7, dry_run=False, as_json=True, retarget=True)
    verbs = forge.verbs()
    assert verbs.index(("pr", "edit")) < verbs.index(("pr", "merge"))
    assert forge.base_ref == "main"


def test_a_pr_already_aimed_at_the_integration_branch_is_left_alone(
    forge: RecordingGh,
) -> None:
    forge.base_ref = "main"
    pr.merge(7, dry_run=False, as_json=True)
    assert ("pr", "edit") not in forge.verbs()
    assert ("pr", "merge") in forge.verbs()
