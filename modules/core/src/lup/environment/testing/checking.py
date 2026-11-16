"""Checking a module's promises, as the gate does: a scenario run on hypothesis's draws, a law over runs of calls through every door of its project, and the smallest run that breaks either kept to say so.

The gate's check is repeatable: each promise draws from a seed its own source
fixes, so a tree gets the same values, and the same verdict, every time. An
exploring check draws from a random seed, many more values, to find what the
gate's doesn't; what it finds is written into a scenario by whoever fixes it
(`lup/testing/README.md`, *Checking*).
"""

import asyncio
import hashlib
import inspect
from typing import TYPE_CHECKING

from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from lup.declaration.project import Project
from lup.doors.action import ActionDoor
from lup.doors.command import CommandDoor
from lup.doors.door import DoorError
from lup.doors.tool import ToolDoor
from lup.environment.doors import Entry
from lup.environment.testing.harness import Harness, Run, promises
from lup.testing.harness import Acted, Broken, Kept, Ran, Sent, ToolCall, sent
from lup.testing.promise import PromiseDoor
from lup.types import Model

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy

    from lup.declaration.module import Module
    from lup.doors.parties import Party
    from lup.environment.doors import Doors
    from lup.testing.harness import Call


class Exploring(Model):
    """How a check explores: how many runs it makes of each promise, and whether their values follow from its source."""

    runs: int = 100
    """How many runs it makes of a promise that draws; one that draws nothing
    runs once."""
    seeded: bool = True
    """Whether each promise draws from a seed its source fixes, as the gate's
    check does, rather than a random one, as an exploring check does."""


class Check(Model, arbitrary_types_allowed=True):
    """One promise to check, with the project whose doors a law's runs call."""

    entry: Entry
    project: Project

    def said(self) -> str:
        """Name the promise: `CounterPromises.never_goes_back`."""
        return self.entry.method.taken.qualified

    def checked(self, exploring: Exploring) -> Kept | Broken:
        """Check the promise over as many runs as `exploring` says, and say how it fared: kept, or broken by the smallest run hypothesis found."""
        runs: list[Run] = []
        with asyncio.Runner() as runner:

            def once(data: st.DataObject) -> None:
                run = Run(checking=checked)
                runs.append(run)
                runner.run(self.ran(Harness(data=data, run=run)))

            test = given(st.data())(once)
            if exploring.seeded:
                test = seed(self.seed())(test)
            test = settings(
                database=None,
                deadline=None,
                max_examples=exploring.runs,
                report_multiple_bugs=False,
                suppress_health_check=[HealthCheck.too_slow],
            )(test)
            try:
                test()
            except Exception as error:
                last = runs[-1]
                return Broken(
                    promise=self.said(),
                    drawn=last.drawn,
                    calls=last.calls,
                    error=error,
                )
        return Kept(promise=self.said())

    async def ran(self, harness: Harness) -> None:
        """Run the promise once: a scenario's story, or a run of calls through every door of its project, the law checked after each."""
        method = self.entry.method
        made = self.entry.serves.made()
        door = method.door
        if not (isinstance(door, PromiseDoor) and door.law(method.taken)):
            told = method.function(made, by=harness)
            if isinstance(told, bool):
                message = f"the scenario `{self.said()}` answers a verdict"
                raise DoorError(message)
            await told
            return
        reached = harness.reached(self.project)
        mine = reached.model_copy(
            update={
                "laws": [
                    law
                    for law in reached.laws
                    if law.method is method
                    and law.serves.module.name == self.entry.serves.module.name
                ]
            }
        )
        for each in harness.data.draw(st.lists(calls(reached.doors))):
            await mine.answered(each)

    def seed(self) -> int:
        """Return the seed the promise's own source fixes, its name and its body, so its values change only as it does."""
        function = self.entry.method.function
        try:
            source = inspect.getsource(function)
        except OSError:
            source = ""
        hashed = hashlib.blake2b(f"{self.said()}\n{source}".encode(), digest_size=8)
        return int.from_bytes(hashed.digest())


def checked(
    project: Project, module: Module, promise: str | None
) -> list[Kept | Broken]:
    """Check the promise named `promise` of `module`, in `project`, or every one where none is named, as the gate does, and say how each fared."""
    return [
        Check(entry=entry, project=project).checked(Exploring())
        for entry in promises(module)
        if promise is None or promise == entry.name
    ]


def calls(doors: Doors) -> SearchStrategy[Call]:
    """Return every call a party could make through the doors `doors` serve: each tool, action and command, given a value of what it takes, by a party of any its doors name."""
    entries = [
        entry
        for entry in doors.entries()
        if isinstance(entry.method.door, ToolDoor | ActionDoor | CommandDoor)
    ]
    if not entries:
        return st.nothing()
    parties: list[type[Party]] = list(
        dict.fromkeys(party for entry in entries for party in entry.method.parties())
    )
    by = st.sampled_from(parties).flatmap(st.from_type)
    return st.one_of(*(call(entry, by) for entry in entries))


def call(entry: Entry, by: SearchStrategy[Party]) -> SearchStrategy[Call]:
    """Return a call through `entry`'s door, given a value of what it takes, by a party drawn from `by`."""
    module = entry.serves.module.name
    door = entry.method.door

    def made(value: Sent, party: Party) -> Call:
        match door:
            case ToolDoor():
                return ToolCall(tool=entry.name, arguments=sent(value), by=party)
            case ActionDoor():
                return Acted(
                    module=module, action=entry.name, given=sent(value), by=party
                )
            case _:
                return Ran(
                    module=module, command=entry.name, arguments=sent(value), by=party
                )

    return st.builds(made, st.from_type(entry.method.taken.given().annotation), by)
