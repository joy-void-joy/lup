"""The testing submodule's promises: what a module's author can count on of how their promises are checked.

Each is checked through the harness over an example module, a counter, whose
own promises the harness checks as the gate does (`Started.checked`). Its count
lives in an object its module holds, made afresh each time lup starts: a
stand-in for the store, which lup doesn't have yet (`README.md` here, *Laws*).
"""

from pydantic import Field

import lup
from lup import (
    Agent,
    Model,
    Module,
    Modules,
    ModuleServing,
    MutableModel,
    Project,
    ProjectError,
    Serving,
)
from lup.testing import (
    Accepted,
    Broken,
    BrokenLawError,
    Kept,
    Step,
    Testing,
    ToolCall,
    raises,
)


class Tally(MutableModel):
    """Where the counter keeps its count while lup runs."""

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


class CounterServing(ModuleServing):
    """The counter's tools: one moves the count, one reads it."""

    module: Counter

    @lup.tool
    async def bump(self, bumping: Bumping) -> Count:
        """Move the count by as much as asked."""
        self.module.tally.count += bumping.by
        return Count(count=self.module.tally.count)

    @lup.tool(reads=True)
    async def counted(self, _asking: Asking) -> Count:
        """Read how far the counter has counted."""
        return Count(count=self.module.tally.count)


class CounterPromises(ModuleServing):
    """The counter's promises: two laws, one it keeps and one it breaks, and two scenarios, one of each."""

    @lup.promise
    def moves_by_what_its_bumped(self, step: Step[Count]) -> bool:
        """The count moves by what an accepted bump asks, and not at all otherwise."""
        moved = step.after.count - step.before.count
        match step.call:
            case ToolCall(tool="bump", arguments=arguments) if isinstance(
                step.answered, Accepted
            ):
                return moved == Bumping.model_validate(arguments).by
            case _:
                return moved == 0

    @lup.promise
    def never_goes_back(self, step: Step[Count]) -> bool:
        """The count never goes down, which a bump by a negative number breaks."""
        return step.after.count >= step.before.count

    @lup.promise
    async def counts_what_its_told(self, by: Testing) -> None:
        """A bump up moves the count up by what it asks."""
        started = await by.started(Project(modules=Modules.default().add(Counter())))
        bumping = by.any(Climbing)
        await started.call("bump", bumping, Agent(id="counting"))
        counted = await started.call("counted", Asking(), Agent(id="counting"))
        assert isinstance(counted, Accepted)
        assert counted.output == Count(count=bumping.by)

    @lup.promise
    async def every_number_is_small(self, by: Testing) -> None:
        """Every number is below ten, which ten breaks."""
        assert by.any(Small).number < 10


class Counter(Module):
    """Counting: an example module the testing submodule's promises check the harness with."""

    name = "counter"
    tally: Tally = Field(default_factory=Tally)
    serving: Serving = Serving.of(CounterServing, CounterPromises)


def counter() -> Project:
    """Return a project of lup's default modules and the counter."""
    return Project(modules=Modules.default().add(Counter()))


class TestingPromises(ModuleServing):
    """What a module's author can count on of how their promises are checked."""

    @lup.promise
    async def a_law_is_checked_after_every_call_a_scenario_makes(
        self, by: Testing
    ) -> None:
        """Every law of every module a scenario starts is checked over each call it makes, and one that doesn't hold fails the scenario there."""
        started = await by.started(counter())
        await started.call("bump", Bumping(by=1), Agent(id="counting"))
        with raises(BrokenLawError) as broken:
            await started.call("bump", Bumping(by=-1), Agent(id="counting"))
        assert broken.raised().step.before.model_dump() == {"count": 1}

    @lup.promise
    async def a_broken_law_is_told_with_the_shortest_run_that_breaks_it(
        self, by: Testing
    ) -> None:
        """A law that a run of calls through its project's doors breaks is reported broken, with the shortest run hypothesis finds, its last call the one that broke it."""
        started = await by.started(counter())
        [broken] = await started.checked("counter", "never_goes_back")
        assert isinstance(broken, Broken)
        assert isinstance(broken.error, BrokenLawError)
        [call] = broken.calls
        assert isinstance(call, ToolCall)
        assert Bumping.model_validate(call.arguments).by == -1

    @lup.promise
    async def a_promise_that_holds_is_kept(self, by: Testing) -> None:
        """A law that holds over every run, and a scenario that holds for every value it draws, are kept."""
        started = await by.started(counter())
        [law] = await started.checked("counter", "moves_by_what_its_bumped")
        [scenario] = await started.checked("counter", "counts_what_its_told")
        assert isinstance(law, Kept)
        assert isinstance(scenario, Kept)

    @lup.promise
    async def a_broken_scenario_is_told_with_the_smallest_values_it_drew(
        self, by: Testing
    ) -> None:
        """A scenario that a value it draws breaks is reported broken, with the smallest values hypothesis finds."""
        started = await by.started(counter())
        [broken] = await started.checked("counter", "every_number_is_small")
        assert isinstance(broken, Broken)
        assert [Small.model_validate(each).number for each in broken.drawn] == [10]

    @lup.promise
    async def a_law_reads_its_state_through_a_door_that_only_reads(
        self, by: Testing
    ) -> None:
        """A law reads its module's state through a door of the module that only reads: a module holding a law with no such door fails to start, rather than its law going unchecked."""

        class Unread(Counter):
            """A counter whose count can't be read."""

            serving: Serving = Serving.of(CounterPromises)

        with raises(ProjectError):
            await by.started(Project(modules=Modules.default().add(Unread())))
