"""Concurrent dependency joins own their plans, checkpoints and progress."""

from pathlib import Path

import pytest

from lup.resolver.join_desk import JoinDesk, JoinLanding, JoinPlan, JoinTip
from lup.resolver.status import join_bar


def test_two_joins_of_the_same_parent_have_independent_authority(
    tmp_path: Path,
) -> None:
    first = JoinDesk(tmp_path, "first")
    second = JoinDesk(tmp_path, "second")
    for desk in (first, second):
        desk.write_plan(
            JoinPlan(
                concern_id=desk.concern_id,
                worktree=tmp_path / "trees" / desk.concern_id,
                base="base",
                title="join parents",
                purpose="dependency",
                tips=[JoinTip(commit="shared-parent", concern_id="parent")],
            )
        )
    first_plan = first.plan()
    assert first_plan is not None
    assert first_plan.concern_id == "first"
    first.record(
        JoinLanding(commit="shared-parent", head="first-head"), ["shared-parent"]
    )
    bar = join_bar(None, tmp_path)
    assert bar is not None
    assert (bar.done, bar.total) == (1, 2)

    first.clear()
    second_plan = second.plan()
    assert second_plan is not None
    assert second_plan.concern_id == "second"
    second.record(
        JoinLanding(commit="shared-parent", head="second-head"), ["shared-parent"]
    )
    assert second.progress().commit == "second-head"
    assert first.progress().landings == []


def test_join_slot_rejects_another_concerns_plan(tmp_path: Path) -> None:
    desk = JoinDesk(tmp_path, "first")
    with pytest.raises(ValueError, match="different concern"):
        desk.write_plan(
            JoinPlan(
                concern_id="second",
                worktree=tmp_path,
                base="base",
                title="",
                purpose="",
            )
        )


@pytest.mark.parametrize("identity", ["", ".", "..", "../other", "/absolute"])
def test_join_identity_cannot_escape_its_slot(tmp_path: Path, identity: str) -> None:
    with pytest.raises(ValueError, match="path-safe"):
        JoinDesk(tmp_path, identity)
