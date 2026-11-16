"""The harness as the gate runs it: lup started in this process, its doors called through `Doors`, every law checked after each call, and values drawn by hypothesis.

A law reads its module's state through a door of the module that only reads:
a tool marked `reads=True` answering the state its step names, taking nothing
it must be given and no `by`, since a module's state is the same whoever asks
(`lup/testing/README.md`, *Laws*).
"""

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path

from hypothesis import strategies as st
from pydantic import BaseModel, JsonValue, TypeAdapter

from lup.declaration.errors import ProjectError
from lup.declaration.module import Module
from lup.declaration.project import Project
from lup.doors.door import Accepted, DoorError, Method, Refused
from lup.doors.parties import Party
from lup.doors.serving import Serving
from lup.doors.tool import ToolDoor, ToolSpec
from lup.environment.declaration import load, resolve
from lup.environment.doors import Doors, Entry, Serves
from lup.testing.harness import (
    Acted,
    Broken,
    BrokenLawError,
    Call,
    Kept,
    Ran,
    Reaching,
    Started,
    Step,
    Testing,
    ToolCall,
)
from lup.testing.promise import PromiseDoor
from lup.types import Model, MutableModel


class Run(MutableModel, arbitrary_types_allowed=True):
    """What one run of a promise did: the values it drew and the calls it made, kept to say what broke it."""

    drawn: list[JsonValue] = []
    calls: list[Call] = []
    checking: Callable[[Project, Module, str | None], list[Kept | Broken]] | None = None
    """How the run checks another module's promises, where a promise asks
    (`Started.checked`): the gate's own checking, which this module can't
    import."""


class Law(Model, arbitrary_types_allowed=True):
    """A law a module holds, with the door its state is read through."""

    serves: Serves
    method: Method
    state: Entry

    def said(self) -> str:
        """Name the law, as a broken one is named: `CounterPromises.never_goes_back`."""
        return self.method.taken.qualified

    async def read(self) -> BaseModel:
        """Return the module's state, as its door that only reads answers it."""
        state = self.state.method
        answered = await state.called(
            self.state.serves.made(), state.validated({}), Reader()
        )
        if not isinstance(answered, BaseModel):
            message = f"`{state.taken.qualified}` answers no state"
            raise DoorError(message)
        return answered

    def holds(self, step: Step[BaseModel]) -> bool:
        """Say whether the law holds over `step`."""
        verdict = self.method.function(self.serves.made(), step)
        if not isinstance(verdict, bool):
            message = f"the law `{self.said()}` answers no verdict"
            raise DoorError(message)
        return verdict


class Reader(Party):
    """The harness reading a module's state, through a door that takes no `by`, so no method sees it."""


def laws(doors: Doors) -> list[Law]:
    """Return every law the modules `doors` serve hold, each with the door its state is read through.

    Raise `ProjectError` where a module holding a law has no door that reads,
    answering the state the law's step names, taking nothing it must be given
    and no `by`.
    """
    return [law for entry in doors.entries() if (law := law_of(entry, doors))]


def law_of(entry: Entry, doors: Doors) -> Law | None:
    """Return the law behind `entry`, with the door of its module its state is read through; none where it's no law."""
    door = entry.method.door
    state = door.law(entry.method.taken) if isinstance(door, PromiseDoor) else None
    if state is None:
        return None
    module = entry.serves.module.name
    readers = [
        each
        for each in doors.through(ToolDoor)
        if each.serves.module.name == module and reads(each, state)
    ]
    if not readers:
        message = (
            f"the law `{entry.method.taken.qualified}` reads `{state.__name__}`, "
            f"which no door of `{module}` that only reads answers: a tool marked "
            "`reads=True`, taking nothing it must be given and no `by`"
        )
        raise ProjectError(message)
    return Law(serves=entry.serves, method=entry.method, state=readers[0])


def reads(entry: Entry, state: type[BaseModel]) -> bool:
    """Say whether `entry` reads `state` as a law needs: a tool marked `reads=True` answering it, needing nothing given."""
    door = entry.method.door
    taken = entry.method.taken
    if not (isinstance(door, ToolDoor) and door.reads and taken.returned is state):
        return False
    if taken.by is not None:
        return False
    try:
        entry.method.validated({})
    except ValueError:
        return False
    return True


class Reached(Model, Reaching, arbitrary_types_allowed=True):
    """A started lup's doors, called through `Doors`, every law its modules hold checked over each call."""

    project: Project
    modules: list[Module]
    doors: Doors
    laws: list[Law]
    run: Run

    def tools(self) -> list[ToolSpec]:
        """Return what a session is told of each tool the modules serve."""
        return self.doors.tools()

    async def answered(self, call: Call) -> Accepted | Refused:
        """Make `call` through its door, every law checked over it.

        Raise `BrokenLawError` where a law doesn't hold over the step it made.
        """
        before = [await law.read() for law in self.laws]
        self.run.calls.append(call)
        answered = await self.reached(call)
        for law, state in zip(self.laws, before, strict=True):
            after = await law.read()
            step = Step[BaseModel](
                before=state, call=call, answered=answered, after=after
            )
            if not law.holds(step):
                raise BrokenLawError(law.said(), step)
        return answered

    async def reached(self, call: Call) -> Accepted | Refused:
        """Make `call` through its door, and say what came of it."""
        match call:
            case ToolCall(tool=tool, arguments=arguments, by=by):
                return await self.doors.call(tool, arguments, by)
            case Acted(module=module, action=action, given=given, by=by):
                return await self.doors.act(module, action, given, by)
            case Ran(module=module, command=command, arguments=arguments, by=by):
                return await self.doors.run(module, command, arguments, by)

    async def checked(self, module: str, promise: str | None) -> list[Kept | Broken]:
        """Check the promise named `promise` of the module named `module`, or every one where none is named, as the gate does, and say how each fared."""
        checking = self.run.checking
        if checking is None:
            message = "this run checks no other module's promises"
            raise DoorError(message)
        [held] = [each for each in self.modules if each.name == module]
        return await asyncio.to_thread(checking, self.project, held, promise)


class Harness(Testing, arbitrary_types_allowed=True):
    """The harness as the gate runs it: lup started in this process, and values drawn by hypothesis."""

    data: st.DataObject
    run: Run

    async def started(self, declared: Project | str) -> Started:
        """Start lup on a declaration: a `Project`, or the text of a declaration's file, loaded as lup loads one.

        Raise `ProjectError` where it doesn't load or resolve, or where a law
        its modules hold has no door to read its state through.
        """
        project = declared if isinstance(declared, Project) else loaded(declared)
        reached = self.reached(project)
        return Started(modules=reached.modules, doors=reached)

    def reached(self, project: Project) -> Reached:
        """Start lup on `project`, and return its doors as this harness reaches them, every law its modules hold checked over each call."""
        resolved = resolve(project)
        return Reached(
            project=project,
            modules=resolved.modules,
            doors=resolved.doors,
            laws=laws(resolved.doors),
            run=self.run,
        )

    def any[T](self, kind: type[T]) -> T:
        """Return a value of `kind`, drawn by hypothesis, which shrinks one that breaks the promise."""
        value = self.data.draw(st.from_type(kind))
        self.run.drawn.append(TypeAdapter(kind).dump_python(value, mode="json"))
        return value


def loaded(text: str) -> Project:
    """Load the declaration whose file holds `text`, as lup loads one.

    Raise `ProjectError` where it doesn't load.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "declaration.py"
        path.write_text(text)
        return load(path)


def promises(module: Module) -> list[Entry]:
    """Return every promise `module` serves, in the order declared."""
    served = Doors(
        served=[Serves(module=module, serving=each) for each in module.held(Serving)]
    )
    return [
        entry
        for entry in served.entries()
        if isinstance(entry.method.door, PromiseDoor)
    ]
