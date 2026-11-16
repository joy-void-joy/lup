"""The harness as the gate runs it: lup started in this process, its doors called through `Doors`, every law checked over each slice of each call, and values drawn by hypothesis.

A law reads its module's state through a door of the module that only reads:
a tool marked `reads=True` answering the state its step names, taking nothing
it must be given and no `by`, since a module's state is the same whoever asks
(`lup/testing/README.md`, *Laws*).
"""

import asyncio
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
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
    """What one run of a promise did: the values it drew, the calls it made and the order their slices ran in, kept to say what broke it."""

    drawn: list[JsonValue] = []
    calls: list[Call] = []
    slices: list[Call] = []
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

    def read(self) -> BaseModel:
        """Return the module's state, as its door that only reads answers it, at once: it's read between two slices, where nothing else may run.

        Raise `DoorError` where the door waits on something rather than
        answering.
        """
        state = self.state.method
        reading = state.called(self.state.serves.made(), state.validated({}), Reader())
        try:
            reading.send(None)
        except StopIteration as read:
            answered = read.value
        else:
            reading.close()
            message = (
                f"`{state.taken.qualified}`, which the law `{self.said()}` reads "
                "its state through, waits rather than answering at once"
            )
            raise DoorError(message)
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


class Calling(MutableModel, arbitrary_types_allowed=True):
    """A call in flight: what it is, the laws checked over each of its slices, and what came of it so far."""

    call: Call
    laws: list[Law]
    run: Run
    states: list[BaseModel] = []
    """Each law's state, read before the slice that's running."""
    answered: Accepted | Refused | None = None
    """What the call answered, once it has."""
    broken: BrokenLawError | None = None
    """The first law a slice of it broke, raised from the call when it ends."""

    def before(self) -> None:
        """Read each law's state before a slice of the call runs."""
        self.run.slices.append(self.call)
        self.states = [law.read() for law in self.laws]

    def after(self) -> None:
        """Check each law over the slice that just ran, keeping the first it broke."""
        steps = [
            (
                law,
                Step[BaseModel](
                    before=before,
                    call=self.call,
                    answered=self.answered,
                    after=law.read(),
                ),
            )
            for law, before in zip(self.laws, self.states, strict=True)
        ]
        broken = next(
            (
                BrokenLawError(law.said(), step)
                for law, step in steps
                if not law.holds(step)
            ),
            None,
        )
        self.broken = self.broken or broken


CALLING = ContextVar[Calling | None]("calling", default=None)
"""The call a task runs, which each of its slices belongs to, and the tasks it
starts too."""


def watched(handle: asyncio.Handle) -> Callable[[], None] | None:
    """Read the state before a slice of a call runs, and return what checks its laws after it; none for a slice of no call."""
    calling = handle.get_context().get(CALLING)
    if calling is None:
        return None
    calling.before()
    return calling.after


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
        """Make `call` through its door, as a task of its own, every law checked over each slice of it.

        Raise `BrokenLawError` where a law doesn't hold over a slice of it,
        once it's ended.
        """
        calling = Calling(call=call, laws=self.laws, run=self.run)
        context = copy_context()
        context.run(CALLING.set, calling)
        self.run.calls.append(call)
        task = asyncio.get_running_loop().create_task(
            self.ran(calling), context=context
        )
        answered = await task
        if calling.broken is not None:
            raise calling.broken
        return answered

    async def ran(self, calling: Calling) -> Accepted | Refused:
        """Make the call, keeping what it answered for the laws checked over its last slice."""
        answered = await self.reached(calling.call)
        calling.answered = answered
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
        """Check the promise named `promise` of the module named `module`, or every one where none is named, as the gate does, and say how each fared.

        The check runs in a thread of its own, this run waiting on it: asyncio
        runs one task at a time in a thread, and the check's runs are tasks of
        their own loop.
        """
        checking = self.run.checking
        if checking is None:
            message = "this run checks no other module's promises"
            raise DoorError(message)
        [held] = [each for each in self.modules if each.name == module]
        with ThreadPoolExecutor(max_workers=1) as apart:
            return apart.submit(checking, self.project, held, promise).result()


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
