"""A request budget counted across processes: what one takes, every other sees.

Written against the failure it answers: three individually polite sessions
summing to a rate an operator blocked. Two budgets over one directory stand
in for two processes, and a clock the test moves stands in for time.
"""

from pathlib import Path

import pytest

from lup.execution.resilience.budget import SharedBudget


class Ticking:
    """A clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_two_budgets_over_one_directory_share_one_window(tmp_path: Path) -> None:
    clock = Ticking()
    first = SharedBudget(tmp_path, window_seconds=60.0, clock=clock)
    second = SharedBudget(tmp_path, window_seconds=60.0, clock=clock)

    assert first.reserve("wikiservice.at", 2).taken
    assert second.reserve("wikiservice.at", 2).taken
    refused = second.reserve("wikiservice.at", 2)

    assert not refused.taken and refused.wait_seconds == 60.0 and refused.inside == 2
    assert first.inside("wikiservice.at") == 2
    # Another key never contends.
    assert first.reserve("paste.linuxiarz.pl", 1).taken
    # The oldest leaves the window and one slot frees.
    clock.now += 60.0
    granted = first.reserve("wikiservice.at", 2)
    assert granted.taken and granted.inside == 1


def test_a_closed_key_is_never_granted_and_a_slug_key_is_a_safe_file_name(
    tmp_path: Path,
) -> None:
    budget = SharedBudget(tmp_path, clock=Ticking())

    refused = budget.reserve("moltbook.com", 0)

    assert not refused.taken and refused.wait_seconds == 60.0
    assert budget.path("bitily.in/MYLABI").name == "bitily.in_MYLABI.json"
    assert budget.inside("never-asked") == 0


@pytest.mark.asyncio
async def test_a_slot_waits_for_the_window_and_then_holds(tmp_path: Path) -> None:
    clock = Ticking()
    budget = SharedBudget(tmp_path, window_seconds=0.05, clock=clock)
    assert budget.reserve("h", 1).taken

    async def advance(seconds: float) -> None:
        clock.now += seconds

    # The window is full; the slot sleeps the reported wait and asks again.
    clock.now += 0.06
    async with budget.slot("h", 1) as reservation:
        assert reservation.taken and reservation.inside == 1
    await advance(0)
