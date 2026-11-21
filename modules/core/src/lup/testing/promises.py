"""The testing submodule's promises: what a module's author can count on of how their promises are checked.

Each is checked through the harness over an example module, a counter, whose
own promises the harness checks as the gate does (`Started.checked`). Its count
is its part's `State`, made afresh each time lup starts; a party reads it
through a tool. Its bump reads the count, waits, then writes it, so two bumps
that overlap lose one: a race an invariant catches only where calls interleave
(`README.md` here, *Invariants*).

The guard's promises run pytest itself on a scratch repository, as the gate
does, since what they promise is how a check fares against the clock and the
processor, which nothing in the process checking them can stand in for.
"""

import asyncio
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from pydantic import Field

import lup
from lup import (
    Agent,
    Model,
    Module,
    Modules,
    Operator,
    Part,
    Parts,
    Project,
    ProjectError,
    State,
)
from lup.programs import run
from lup.testing import (
    Accepted,
    Broken,
    BrokenInvariantError,
    Kept,
    Step,
    Testing,
    ToolCall,
    raises,
)


class Tally(Model):
    """How far the counter has counted, as its part keeps it while lup runs."""

    count: int = 0


class Bumping(Model):
    """How far to move the count."""

    by: int


class Climbing(Model):
    """How far to move the count up."""

    by: int = Field(ge=0)


class Asking(Model):
    """Nothing: what reading the count takes."""


class Count(Model):
    """How far the counter has counted: its state, as a party sees it."""

    count: int


class Small(Model):
    """A number a scenario promises is small, which it isn't always."""

    number: int = Field(ge=0)


class CounterPart(Part):
    """The counter's tools: one moves the count, one reads it."""

    tally: State[Tally] = Tally()
    """How far it has counted."""

    @lup.tool
    async def bump(self, bumping: Bumping) -> Count:
        """Move the count by as much as asked.

        It reads the count, waits, then writes it, so a bump overlapping
        another loses it.
        """
        count = self.tally.count
        await asyncio.sleep(0)
        self.tally = Tally(count=count + bumping.by)
        return Count(count=self.tally.count)

    @lup.tool(reads=True)
    async def counted(self, _asking: Asking) -> Count:
        """Read how far the counter has counted."""
        return Count(count=self.tally.count)


class CounterPromises(Part):
    """The counter's promises: invariants it keeps and invariants it breaks, alone or only where bumps overlap, over its part's state or what its tool reads, and a scenario of each."""

    @lup.promise
    def reading_changes_nothing(self, step: Step[Count]) -> bool:
        """Reading the count never moves it, as its tool reads it."""
        match step.call:
            case ToolCall(tool="counted"):
                return step.after.count == step.before.count
            case _:
                return True

    @lup.promise
    def moves_by_what_its_bumped(self, step: Step[Tally]) -> bool:
        """The count moves by what a bump asks, on the slice that ends it, and not at all otherwise, which two bumps overlapping break."""
        moved = step.after.count - step.before.count
        match step.call:
            case ToolCall(tool="bump", arguments=arguments) if isinstance(
                step.answered, Accepted
            ):
                return moved == Bumping.model_validate(arguments).by
            case _:
                return moved == 0

    @lup.promise
    def never_goes_back(self, step: Step[Tally]) -> bool:
        """The count never goes down, which a bump by a negative number breaks."""
        return step.after.count >= step.before.count

    @lup.promise
    async def counts_what_its_told(self, by: Testing) -> None:
        """A bump up moves the count up by what it asks."""
        started = await by.started(Project(modules=Modules.default().add(Counter())))
        bumping = by.any(Climbing)
        agent = by.any(Agent)
        await started.call("bump", bumping, agent)
        counted = await started.call("counted", Asking(), agent)
        assert isinstance(counted, Accepted)
        assert counted.output == Count(count=bumping.by)

    @lup.promise
    async def every_number_is_small(self, by: Testing) -> None:
        """Every number is below ten, which ten breaks."""
        assert by.any(Small).number < 10

    @lup.promise
    async def every_byte_is_ascii(self, by: Testing) -> None:
        """Every byte drawn is ASCII, which a byte past it, as in `b"\\x80"`, breaks."""
        assert by.any(bytes).isascii()

    @lup.promise(every_project=True)
    async def the_project_counts(self, by: Testing) -> None:
        """Whichever project's gate checks this selects the counter."""
        started = await by.started(by.project())
        assert any(each.name == Counter.name for each in started.modules)


class Counter(Module):
    """Counting: an example module the testing submodule's promises check the harness with."""

    name = "counter"
    parts: Parts = Parts.of(CounterPart, CounterPromises)


def counter() -> Project:
    """Return a project of lup's default modules and the counter."""
    return Project(modules=Modules.default().add(Counter()))


class Checked(Model):
    """How one check of a run of pytest ended, as its report says."""

    name: str
    failed: bool
    properties: dict[str, str]
    """What the gate's plugin marked it with, by name: why the guard halted it
    (`lup-halted`), the processor's seconds it took past its `slow`
    (`lup-slow`), or how it failed before it held (`lup-flaky`)."""


def gated(files: dict[str, str], limits: dict[str, float]) -> list[Checked]:
    """Run pytest, as the gate does, on a scratch repository holding `files`, by their names, its guard's limits in seconds `limits`, and say how each check ended."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, text in files.items():
            (root / name).write_text(text)
        report = root / "report.xml"
        settings = [
            each
            for name, value in limits.items()
            for each in ["-o", f"lup_{name}={value}"]
        ]
        run(
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
            *settings,
            cwd=root,
            checked=False,
        )
        # lup: ignore("S314", why="the XML is the report of a run of pytest this promise started")
        cases = ET.parse(report).getroot().iter("testcase")
        return [
            Checked(
                name=case.get("name", ""),
                failed=case.find("failure") is not None,
                properties={
                    each.get("name", ""): each.get("value", "")
                    for each in case.iter("property")
                },
            )
            for case in cases
        ]


STUCK = """
import threading

import pytest


@pytest.mark.unpromised(why="stuck on purpose, for the guard's promise")
def test_stuck():
    held = threading.Lock()
    held.acquire()
    held.acquire()


@pytest.mark.unpromised(why="the check after a stuck one, for the guard's promise")
def test_after():
    pass
"""
"""A check stuck on a lock nothing releases, and one after it."""

SPINNING = """
import time

import pytest


@pytest.mark.unpromised(why="spending the processor's time on purpose, for the guard's promise")
def test_spinning():
    began = time.process_time()
    while time.process_time() - began < {seconds}:
        pass
"""
"""A check spending as many seconds of the processor's time as `seconds` says."""

FLAKY = """
from pathlib import Path

import lup
from lup import Module, Modules, Part, Parts, Project
from lup.testing import Testing

MARK = Path(__file__).parent / "failed"


class FlakyPromises(Part):
    \"\"\"A promise that fails the first time it's checked.\"\"\"

    @lup.promise
    async def holds_once_it_failed(self, by: Testing) -> None:
        \"\"\"It holds once it has failed.\"\"\"
        failed = MARK.exists()
        MARK.touch()
        assert failed


class Flaky(Module):
    \"\"\"A module whose promise depends on more than its tree.\"\"\"

    name = "flaky"
    parts: Parts = Parts.of(FlakyPromises)


project = Project(modules=Modules.default().add(Flaky()))
"""
"""A declaration whose module's promise fails the first time it's checked and holds after, as one depending on more than its tree does."""


class TestingPromises(Part):
    """What a module's author can count on of how their promises are checked."""

    @lup.promise
    async def an_invariant_is_checked_after_every_call_a_scenario_makes(
        self, by: Testing
    ) -> None:
        """Every invariant of every module a scenario starts is checked over each call it makes, and one that doesn't hold fails the scenario there."""
        started = await by.started(counter())
        agent = by.any(Agent)
        await started.call("bump", Bumping(by=1), agent)
        with raises(BrokenInvariantError) as broken:
            await started.call("bump", Bumping(by=-1), agent)
        before = broken.raised().step.before
        assert isinstance(before, Tally)
        assert before.count == 1

    @lup.promise
    async def a_broken_invariant_is_told_with_the_shortest_run_that_breaks_it(
        self, by: Testing
    ) -> None:
        """An invariant that a run of calls through its project's doors breaks is reported broken, with the shortest run hypothesis finds, its last call the one that broke it."""
        started = await by.started(counter())
        [broken] = await started.checked("counter", "never_goes_back")
        assert isinstance(broken, Broken)
        assert isinstance(broken.error, BrokenInvariantError)
        [call] = broken.calls
        assert isinstance(call, ToolCall)
        assert Bumping.model_validate(call.arguments).by == -1

    @lup.promise
    async def an_invariant_broken_only_where_calls_overlap_is_told_with_how_they_interleaved(
        self, by: Testing
    ) -> None:
        """An invariant that only calls overlapping break, each slice of a call a step of its own, is reported broken with the calls and the order their slices ran in."""
        started = await by.started(counter())
        [broken] = await started.checked("counter", "moves_by_what_its_bumped")
        assert isinstance(broken, Broken)
        assert isinstance(broken.error, BrokenInvariantError)
        first, second = broken.calls
        assert all(isinstance(each, ToolCall) for each in (first, second))
        ends = max(at for at, each in enumerate(broken.slices) if each == first)
        assert broken.slices.index(second) < ends

    @lup.promise
    async def a_run_never_waits_on_real_time(self, by: Testing) -> None:
        """A run's clock moves only when nothing else can run, straight to the next timer: an hour's sleep passes at once, its clock an hour on."""
        loop = asyncio.get_running_loop()
        began = loop.time()
        await asyncio.sleep(3600)
        assert loop.time() - began >= 3600

    @lup.promise
    async def work_handed_to_a_thread_runs_within_a_run(self, by: Testing) -> None:
        """Work handed to a thread (`asyncio.to_thread`), as code moving blocking file work off the loop does, runs within a run, taking no time on its clock: what it gives is what's awaited, and what it raises is raised there."""
        loop = asyncio.get_running_loop()
        began = loop.time()
        number = by.any(int)
        assert await asyncio.to_thread(abs, number) == abs(number)
        with raises(ValueError):
            await asyncio.to_thread(int, "not a number")
        assert loop.time() == began

    @lup.promise
    async def a_promise_that_holds_is_kept(self, by: Testing) -> None:
        """An invariant that holds over every run, and a scenario that holds for every value it draws, are kept."""
        started = await by.started(counter())
        [invariant] = await started.checked("counter", "reading_changes_nothing")
        [scenario] = await started.checked("counter", "counts_what_its_told")
        assert isinstance(invariant, Kept)
        assert isinstance(scenario, Kept)

    @lup.promise
    async def a_promise_about_every_project_is_checked_over_the_one_checking_it(
        self, by: Testing
    ) -> None:
        """A promise about every project is checked over the project whose gate checks it, as that project declares it."""
        started = await by.started(counter())
        [kept] = await started.checked("counter", "the_project_counts")
        assert isinstance(kept, Kept)

    @lup.promise
    async def a_broken_scenario_is_told_with_the_smallest_values_it_drew(
        self, by: Testing
    ) -> None:
        """A scenario that a value it draws breaks is reported broken, with the smallest values hypothesis finds."""
        started = await by.started(counter())
        [broken] = await started.checked("counter", "every_number_is_small")
        assert isinstance(broken, Broken)
        [small] = broken.drawn
        assert isinstance(small, Small)
        assert small.number == 10

    @lup.promise
    async def a_promise_may_draw_a_value_of_any_kind(self, by: Testing) -> None:
        """A scenario may draw a value of any kind, bytes that aren't text among them, and is told broken with the smallest it drew, as drawn."""
        started = await by.started(counter())
        [broken] = await started.checked("counter", "every_byte_is_ascii")
        assert isinstance(broken, Broken)
        [drawn] = broken.drawn
        assert drawn == b"\x80"

    @lup.promise
    async def an_invariant_with_nowhere_to_read_its_state_fails_to_start(
        self, by: Testing
    ) -> None:
        """An invariant reads its module's state from a part's field typed `State[…]`, or through a door of the module that only reads: a module holding an invariant with neither fails to start, naming it, rather than its invariant going unchecked."""

        class Unread(Counter):
            """A counter whose count is neither held nor read."""

            parts: Parts = Parts.of(CounterPromises)

        with raises(ProjectError) as failed:
            await by.started(Project(modules=Modules.default().add(Unread())))
        invariants = [
            "CounterPromises.reading_changes_nothing",
            "CounterPromises.moves_by_what_its_bumped",
            "CounterPromises.never_goes_back",
        ]
        assert any(each in failed.raised().about for each in invariants)

    @lup.promise
    async def an_invariant_reads_a_state_only_the_operator_may(
        self, by: Testing
    ) -> None:
        """An invariant reads its module's state through a door only the operator may call, as through any door that only reads, so a module's whole state needn't be every agent's to read."""

        class OperatorsCount(CounterPart):
            """The counter's tools, its count the operator's alone to read."""

            @lup.tool(reads=True)
            async def counted(self, _asking: Asking, by: Operator) -> Count:
                """Read how far the counter has counted."""
                return Count(count=self.tally.count)

        class Guarded(Counter):
            """A counter whose count only the operator reads."""

            parts: Parts = Parts.of(OperatorsCount, CounterPromises)

        started = await by.started(Project(modules=Modules.default().add(Guarded())))
        [kept] = await started.checked("counter", "reading_changes_nothing")
        assert isinstance(kept, Kept)

    @lup.promise
    async def a_stuck_check_fails_and_the_run_goes_on(self, by: Testing) -> None:
        """A check in which nothing runs for the guard's `stalled`, as one stuck on a lock, fails, saying why, and the run goes on to the next check, rather than hanging the gate."""
        stuck, after = gated({"test_stuck.py": STUCK}, {"stalled": 1})
        assert stuck.failed
        assert "lup-halted" in stuck.properties
        assert not after.failed

    @lup.promise
    async def a_check_past_its_ceiling_fails(self, by: Testing) -> None:
        """A check taking more of the processor's time than the guard's `ceiling` fails as too slow, though it goes on moving."""
        [spinning] = gated(
            {"test_spinning.py": SPINNING.format(seconds=30)},
            {"stalled": 60, "ceiling": 1},
        )
        assert spinning.failed
        assert "lup-halted" in spinning.properties

    @lup.promise
    async def a_slow_check_passes_marked_to_fix(self, by: Testing) -> None:
        """A check taking more of the processor's time than the guard's `slow`, within its ceiling, passes, marked as slow to fix."""
        [spinning] = gated(
            {"test_spinning.py": SPINNING.format(seconds=0.5)},
            {"stalled": 60, "slow": 0.2},
        )
        assert not spinning.failed
        assert "lup-slow" in spinning.properties

    @lup.promise
    async def a_promise_failing_then_holding_passes_marked_to_fix(
        self, by: Testing
    ) -> None:
        """A promise that fails, then holds when checked again on the same values, depends on more than its tree: it passes, marked with how it failed, to fix, rather than failing a branch it may have nothing to do with."""
        checked = gated({"lup_project.py": FLAKY}, {})
        [flaky] = [
            each
            for each in checked
            if each.name == "FlakyPromises.holds_once_it_failed"
        ]
        assert not flaky.failed
        assert "lup-flaky" in flaky.properties
