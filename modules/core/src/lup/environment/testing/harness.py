"""The harness as the gate runs it: lup started in this process, its doors called through `Doors`, every invariant checked over each slice of each call, and values drawn by hypothesis.

An invariant reads its module's state from a part's field typed `State[…]`,
copied as it's read; or, for a state too big to copy at each slice, through a
door of the module that only reads: a tool marked `reads=True` answering the
state its step names, taking nothing it must be given, read as the party its
`by` names where one is made with nothing given, the operator above all
(`lup/testing/README.md`, *Invariants*).
"""

import asyncio
import copy
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from pathlib import Path
from typing import get_args, get_origin, override

from hypothesis import strategies as st
from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from lup.core import Core
from lup.declaration.errors import ProjectError
from lup.declaration.layout import MachineLayout, RepositoryLayout
from lup.declaration.module import Module
from lup.declaration.project import Project
from lup.doors.door import Accepted, DoorError, Method, Refused
from lup.doors.parties import Agent, Party
from lup.doors.parts import Finished, Parts, Program, Runs, State, UnrunError
from lup.doors.tool import ToolDoor, ToolSpec
from lup.environment.declaration import read, resolve
from lup.environment.doors import Doors, Entry, Running, Serves
from lup.environment.running.container import answered
from lup.environment.running.planning import plan_of
from lup.environment.shell import viewed
from lup.environment.shell.server import Dashboard, Over, Session, Socket
from lup.environment.told import rendered
from lup.running.plan import Plan
from lup.shell.looks import Looks
from lup.shell.wire import Sent as Frame
from lup.shell.wire import Told
from lup.testing.harness import (
    Acting,
    Broken,
    BrokenInvariantError,
    Call,
    Crossing,
    Heard,
    Kept,
    Opening,
    Page,
    Planning,
    ProgramRun,
    Ran,
    Reaching,
    Repository,
    Responding,
    Scripted,
    Served,
    Started,
    Step,
    Telling,
    Testing,
    ToolCall,
    Viewed,
)
from lup.testing.promise import PromiseDoor
from lup.types import Model, MutableModel
lazy from lup.shell.blocks import Viewing
lazy from lup.told.guidance import Guidance

JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda inner: st.lists(inner) | st.dictionaries(st.text(), inner),
)
"""Every JSON value, as a run draws one where a door or a promise takes pydantic's `JsonValue`: hypothesis can't draw that type itself, which names its own members by a string it doesn't resolve."""

# lup: ignore("reportArgumentType", why="pydantic types `JsonValue` as a union for a type checker, and makes it the type alias hypothesis registers at run time")
st.register_type_strategy(JsonValue, JSON)


class Run(MutableModel, arbitrary_types_allowed=True):
    """What one run of a promise did: the values it drew, the calls it made and the order their slices ran in, kept to say what broke it."""

    # lup: ignore("bare-object", why="a value drawn is of whatever kind its promise asked the harness for, bytes and sets among them, which no one type holds")
    drawn: list[object] = []
    error: Exception | None = None
    """What broke the promise in this run; none where it held."""
    calls: list[Call] = []
    slices: list[Call] = []
    checking: Callable[[Project, Module, str | None], list[Kept | Broken]] | None = None
    """How the run checks another module's promises, where a promise asks
    (`Started.checked`): the gate's own checking, which this module can't
    import."""
    started: list[Running] = []
    """What the run started, stopped once the promise ends."""
    kept: list[tempfile.TemporaryDirectory[str]] = []
    """Where what the run started keeps its data and what lasts while it runs, removed once it's stopped."""

    async def stopped(self) -> None:
        """Stop what the run started, the last first, and remove where it kept its data."""
        for running in reversed(self.started):
            await running.stopped()
        self.started = []
        for each in self.kept:
            each.cleanup()
        self.kept = []


class Stating(ABC):
    """Where an invariant reads its module's state: a part's field typed `State[…]`, or a door of the module that only reads."""

    @abstractmethod
    def read(self, running: Running) -> BaseModel:
        """Return the state as it stands on lup as it runs, at once: it's read between two slices, where nothing else may run."""


class Held(Model, Stating, arbitrary_types_allowed=True):
    """A part's field typed `State[…]`, read as the part made here holds it, a copy, so what a slice changes in place leaves the state read before it as it was."""

    serves: Serves
    name: str

    @override
    def read(self, running: Running) -> BaseModel:
        """Return a copy of the field's value, on the part made here.

        Raise `DoorError` where the part runs elsewhere, or holds no model.
        """
        named = self.serves.named()
        made = next(
            (each.made for each in running.made if each.serves.named() == named), None
        )
        if made is None:
            message = f"{self.serves.said()} runs elsewhere, not here"
            raise DoorError(message, about=[named])
        value = getattr(made, self.name)
        if not isinstance(value, BaseModel):
            message = f"`{named}.{self.name}` holds no model"
            raise DoorError(message, about=[named])
        return copy.deepcopy(value)


class Answered(Model, Stating, arbitrary_types_allowed=True):
    """A door of the module that only reads, answering its state: for a state too big to copy at each slice, as a whole database."""

    entry: Entry

    @override
    def read(self, running: Running) -> BaseModel:
        """Return what the door answers, as the party it names that's made with nothing given, or no one where it names none.

        Raise `DoorError` where the door waits on something rather than
        answering, or answers no model.
        """
        state = self.entry.method
        reading = state.called(
            running.part(self.entry), state.validated({}), reader(state) or Reader()
        )
        try:
            reading.send(None)
        except StopIteration as read:
            answered = read.value
        else:
            reading.close()
            message = (
                f"`{state.taken.qualified}`, which an invariant reads its state "
                "through, waits rather than answering at once"
            )
            raise DoorError(message)
        if not isinstance(answered, BaseModel):
            message = f"`{state.taken.qualified}` answers no state"
            raise DoorError(message)
        return answered


class Invariant(Model, arbitrary_types_allowed=True):
    """An invariant a module holds, with where its state is read."""

    entry: Entry
    state: Stating

    @property
    def method(self) -> Method:
        """The invariant's method."""
        return self.entry.method

    def said(self) -> str:
        """Name the invariant, as a broken one is named: `CounterPromises.never_goes_back`."""
        return self.method.taken.qualified

    def holds(self, running: Running, step: Step[BaseModel]) -> bool:
        """Say whether the invariant holds over `step`, on lup as it runs."""
        verdict = self.method.function(running.part(self.entry), step)
        if not isinstance(verdict, bool):
            message = f"the invariant `{self.said()}` answers no verdict"
            raise DoorError(message)
        return verdict


class Calling(MutableModel, arbitrary_types_allowed=True):
    """A call in flight: what it is, the invariants checked over each of its slices, and what came of it so far."""

    call: Call
    invariants: list[Invariant]
    running: Running
    run: Run
    states: list[BaseModel] = []
    """Each invariant's state, read before the slice that's running."""
    answered: Accepted | Refused | None = None
    """What the call answered, once it has."""
    broken: BrokenInvariantError | None = None
    """The first invariant a slice of it broke, raised from the call when it ends."""

    def before(self) -> None:
        """Read each invariant's state before a slice of the call runs."""
        self.run.slices.append(self.call)
        self.states = [each.state.read(self.running) for each in self.invariants]

    def after(self) -> None:
        """Check each invariant over the slice that just ran, keeping the first it broke."""
        steps = [
            (
                each,
                Step[BaseModel](
                    before=before,
                    call=self.call,
                    answered=self.answered,
                    after=each.state.read(self.running),
                ),
            )
            for each, before in zip(self.invariants, self.states, strict=True)
        ]
        broken = next(
            (
                BrokenInvariantError(each.said(), step)
                for each, step in steps
                if not each.holds(self.running, step)
            ),
            None,
        )
        self.broken = self.broken or broken


CALLING = ContextVar[Calling | None]("calling", default=None)
"""The call a task runs, which each of its slices belongs to, and the tasks it
starts too."""


def watched(handle: asyncio.Handle) -> Callable[[], None] | None:
    """Read the state before a slice of a call runs, and return what checks its invariants after it; none for a slice of no call."""
    calling = handle.get_context().get(CALLING)
    if calling is None:
        return None
    calling.before()
    return calling.after


class Reader(Party):
    """The harness reading a module's state, through a door that takes no `by`, so no method sees it."""


def invariants(doors: Doors) -> list[Invariant]:
    """Return every invariant the modules `doors` serve hold, each with where its state is read.

    Raise `ProjectError` where a module holding an invariant has nowhere its
    state is read (`stating`).
    """
    return [
        Invariant(entry=entry, state=state)
        for entry in doors.entries()
        if (state := stating(entry, doors)) is not None
    ]


def stating(entry: Entry, doors: Doors) -> Stating | None:
    """Return where the invariant behind `entry` reads its module's state: a part's field typed `State[…]` of it, else a door of the module that only reads it; none where it's no invariant.

    Raise `ProjectError` where its module has neither.
    """
    door = entry.method.door
    state = (
        door.invariant(entry.method.taken) if isinstance(door, PromiseDoor) else None
    )
    if state is None:
        return None
    module = entry.serves.module.name
    held: list[Stating] = [
        Held(serves=serves, name=name)
        for serves in doors.served
        if serves.module.name == module
        for name, info in serves.part.model_fields.items()
        if stated(info) is state
    ]
    answered: list[Stating] = [
        Answered(entry=each)
        for each in doors.through(ToolDoor)
        if each.serves.module.name == module and reads(each, state)
    ]
    found = [*held, *answered]
    if not found:
        message = (
            f"the invariant `{entry.method.taken.qualified}` reads "
            f"`{state.__name__}`, which no part of `{module}` holds as a field "
            f"typed `State[{state.__name__}]`, and no door of it that only reads "
            "answers"
        )
        raise ProjectError(message, about=[entry.method.taken.qualified])
    return found[0]


def stated(field: FieldInfo) -> type | None:
    """Return the state a part's field says it holds, `Tally` for one typed `State[Tally]`; none where it's no `State`."""
    if get_origin(field.annotation) is not State:
        return None
    [state] = get_args(field.annotation)
    return state if isinstance(state, type) else None


def reader(method: Method) -> Party | None:
    """Return the party the harness reads an invariant's state through `method` as: the first its `by` names that's made with nothing given, as `Operator` is; none where it takes no `by`, or names no such party."""
    if method.taken.by is None:
        return None
    made = (made_alone(party) for party in method.parties())
    return next((each for each in made if each is not None), None)


def made_alone(party: type[Party]) -> Party | None:
    """Return `party` made with nothing given; none where it needs something."""
    try:
        return party()
    except ValidationError:
        return None


def reads(entry: Entry, state: type[BaseModel]) -> bool:
    """Say whether `entry` reads `state` as an invariant needs: a tool marked `reads=True` answering it, needing nothing given, by no one or by a party made with nothing given."""
    door = entry.method.door
    taken = entry.method.taken
    if not (isinstance(door, ToolDoor) and door.reads and taken.returned is state):
        return False
    if taken.by is not None and reader(entry.method) is None:
        return False
    try:
        entry.method.validated({})
    except ValueError:
        return False
    return True


class Reached(Model, Reaching, arbitrary_types_allowed=True):
    """A started lup's doors, called through `Doors`, every invariant its modules hold checked over each call."""

    project: Project
    modules: list[Module]
    running: Running
    looks: Looks
    invariants: list[Invariant]
    run: Run

    @property
    def doors(self) -> Doors:
        """What the modules serve."""
        return self.running.doors

    def tools(self) -> list[ToolSpec]:
        """Return what a session is told of each tool the modules serve."""
        return self.running.tools()

    async def answered(self, call: Call) -> Accepted | Refused:
        """Make `call` through its door, as a task of its own, every invariant checked over each slice of it.

        Raise `BrokenInvariantError` where an invariant doesn't hold over a slice of it,
        once it's ended.
        """
        calling = Calling(
            call=call, invariants=self.invariants, running=self.running, run=self.run
        )
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
        """Make the call, keeping what it answered for the invariants checked over its last slice."""
        answered = await self.reached(calling.call)
        calling.answered = answered
        return answered

    async def reached(self, call: Call) -> Accepted | Refused:
        """Make `call` through its door, and say what came of it."""
        match call:
            case ToolCall(tool=tool, arguments=arguments, by=by):
                return await self.running.call(tool, arguments, by)
            case Ran(module=module, command=command, arguments=arguments, by=by):
                return await self.running.run(module, command, arguments, by)
            case Served(service=service, given=given, by=by):
                return await self.running.serve(service, given, by)
            case Viewed(module=module, view=view, given=given, by=by):
                return await viewed(self.running, self.looks, module, view, given, by)

    async def stopped(self) -> None:
        """Stop the lup this harness started, rather than once the promise ends."""
        await self.running.stopped()
        self.run.started = [
            each for each in self.run.started if each is not self.running
        ]

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


class StandIn(Model, Runs, arbitrary_types_allowed=True):
    """The programs a started lup's parts run, stood in for as a promise scripts them: each run heard, and answered by the first answer whose `when` its arguments start with, or by the code the promise wrote for it."""

    scripts: dict[str, Scripted | Responding | Acting] = {}
    heard: Heard

    async def ran(
        self,
        program: Program,
        arguments: list[str],
        given: bytes | None,
        env: dict[str, str],
        cwd: Path | None,
    ) -> Finished:
        """Hear the run, and answer it as its program's script says.

        Raise `UnrunError` where no answer of its script fits, as for a
        program that isn't there.
        """
        self.heard.runs.append(
            ProgramRun(
                program=program.name,
                arguments=arguments,
                given=given,
                env=env,
                cwd=cwd,
            )
        )
        match self.scripts.get(program.name, Scripted()):
            case Scripted(answers=answers):
                answer = next(
                    (
                        each
                        for each in answers
                        if arguments[: len(each.when)] == each.when
                    ),
                    None,
                )
            case Responding() as responding:
                answer = responding.answered(arguments, given)
            case Acting() as acting:
                answer = acting.ran(arguments, given, env, cwd)
        if answer is None:
            message = (
                f"`{program.name} {' '.join(arguments)}` has no answer in the "
                "promise's script, so it's run as a program that isn't there"
            )
            raise UnrunError(message, about=[program.name])
        return Finished(
            status=answer.status,
            output=bytes_of(answer.output),
            error=bytes_of(answer.error),
        )

    async def found(self, program: Program) -> bool:
        """Say whether the promise stands `program` in: a program it scripts is there, any other isn't."""
        return program.name in self.scripts


def bytes_of(written: bytes | str) -> bytes:
    """Return what a program stood in for writes, as bytes, text as UTF-8."""
    return written.encode() if isinstance(written, str) else written


class Crosser(Model, Crossing, arbitrary_types_allowed=True):
    """A started lup's parts, a message crossing to them answered as their container answers it."""

    running: Running
    looks: Looks
    """The kinds the parts' modules declare, which their views may name."""

    async def crossed(self, text: bytes) -> bytes:
        """Answer one message as the container running these parts would."""
        return await answered(self.running, text, looks=self.looks)


class Teller(Model, Telling, arbitrary_types_allowed=True):
    """A started lup's guidance, rendered on its parts as made in this process."""

    running: Running

    async def guidance(self, by: Agent) -> Guidance:
        """Render what the session `by` is told at its start of the modules started here."""
        return await rendered(self.running, by)


class Planner(MutableModel, Planning, arbitrary_types_allowed=True):
    """A started lup's plan, made once, where it's first asked for."""

    project: Project
    made: Plan | None = None

    @override
    def plan(self) -> Plan:
        """Return the project's plan, making it the first time."""
        if self.made is None:
            self.made = plan_of(resolve(self.project), [])
        return self.made


class Dashboards(MutableModel, Opening, arbitrary_types_allowed=True):
    """A started lup's one dashboard, as the harness opens its pages: made as the first opens, every page on the same draft."""

    running: Running
    looks: Looks
    planner: Planner
    root: Viewing | None
    """The document's root view, as the core module names it."""
    repository: str
    made: Dashboard | None = None

    def dashboard(self) -> Dashboard:
        """Return the dashboard, making it the first time."""
        if self.made is None:
            self.made = Dashboard(
                answerer=Over(
                    running=self.running, looks=self.looks, plan=self.planner.plan()
                ),
                looks=self.looks,
                root=self.root,
                repository=self.repository,
            )
        return self.made

    @override
    async def page(self) -> Page:
        """Open a page of the dashboard, its socket in memory, served as the server serves one."""
        dashboard = self.dashboard()
        inbound: asyncio.Queue[str | None] = asyncio.Queue()
        outbound: asyncio.Queue[str | None] = asyncio.Queue()
        socket = Queued(inbound=inbound, outbound=outbound)
        session = Session(dashboard=dashboard, socket=socket)
        serving = asyncio.get_running_loop().create_task(session.run())
        return Paged(
            token=dashboard.token,
            inbound=inbound,
            outbound=outbound,
            serving=serving,
        )


class Queued(Socket, Model, arbitrary_types_allowed=True):
    """A page's socket in memory: what the page says, and what it's told, each a queue."""

    inbound: asyncio.Queue[str | None]
    outbound: asyncio.Queue[str | None]

    @override
    async def received(self) -> str | None:
        return await self.inbound.get()

    @override
    async def send(self, text: str) -> None:
        await self.outbound.put(text)

    @override
    async def close(self, code: int, reason: str) -> None:
        del code, reason
        await self.outbound.put(None)


class Paged(Page, arbitrary_types_allowed=True):
    """A page of the dashboard as the harness opens it: its socket in memory, served as the server serves one."""

    inbound: asyncio.Queue[str | None]
    outbound: asyncio.Queue[str | None]
    serving: asyncio.Task[None]
    """The server's session reading the page's socket."""

    @override
    async def say(self, frame: Frame | str) -> None:
        await self.inbound.put(
            frame if isinstance(frame, str) else frame.model_dump_json()
        )

    @override
    async def told(self) -> Told | None:
        text = await self.outbound.get()
        return None if text is None else TypeAdapter[Told](Told).validate_json(text)

    @override
    async def leave(self) -> None:
        await self.inbound.put(None)
        await self.serving


class Harness(Testing, arbitrary_types_allowed=True):
    """The harness as the gate runs it: lup started in this process, and values drawn by hypothesis."""

    data: st.DataObject
    run: Run
    gated: Project
    """The project whose gate checks the promise, as its gate loads it."""

    def project(self) -> Project:
        """Return the project whose gate checks this promise, as its gate loads it."""
        return self.gated

    async def started(
        self,
        declared: Project | Repository,
        secrets: Mapping[str, str] | None = None,
        repository: str = "harness",
        programs: Mapping[str, Scripted | Responding | Acting] | None = None,
        *,
        machine: bool = False,
    ) -> Started:
        """Start lup on a declaration: a `Project`, or a repository's files, read with their layers as lup reads a repository's, each class made once and started.

        Raise `ProjectError` where it doesn't load or resolve, where a secret a
        class holds isn't given, or where an invariant its modules hold has nowhere to
        read its state through.
        """
        project = declared if isinstance(declared, Project) else loaded(declared)
        heard = Heard()
        stand = StandIn(scripts=dict(programs or {}), heard=heard)
        reached = await self.reached(
            project, secrets, repository, stand, machine=machine
        )
        planner = Planner(project=project)
        return Started(
            modules=reached.modules,
            specs=reached.tools(),
            planning=planner,
            doors=reached,
            crossing=Crosser(running=reached.running, looks=reached.looks),
            heard=heard,
            telling=Teller(running=reached.running),
            dashboards=Dashboards(
                running=reached.running,
                looks=reached.looks,
                planner=planner,
                root=document_of(reached.modules),
                repository=repository,
            ),
        )

    async def reached(
        self,
        project: Project,
        secrets: Mapping[str, str] | None = None,
        repository: str = "harness",
        runs: Runs | None = None,
        *,
        machine: bool = False,
    ) -> Reached:
        """Start lup on `project`, as the code of `repository`, and return its doors as this harness reaches them, every invariant its modules hold checked over each call.

        Each secret a class holds is `secrets`'s, or drawn where they're left
        out.
        """
        resolved = resolve(project)
        held = [
            name for each in resolved.doors.served for name in each.part.holds().secrets
        ]
        given = (
            dict(secrets)
            if secrets is not None
            else {name: self.any(str) for name in dict.fromkeys(held)}
        )
        kept = tempfile.TemporaryDirectory(prefix="lup-data-")
        lasting = tempfile.TemporaryDirectory(prefix="lup-run-")
        self.run.kept.extend([kept, lasting])
        running = await resolved.doors.started(
            repository,
            given,
            data=Path(kept.name),
            runtime=Path(lasting.name),
            runs=runs or StandIn(heard=Heard()),
            machine=machine,
        )
        self.run.started.append(running)
        return Reached(
            project=project,
            modules=resolved.modules,
            running=running,
            looks=resolved.looks,
            invariants=invariants(running.doors),
            run=self.run,
        )

    def any[T](self, kind: type[T]) -> T:
        """Return a value of `kind`, drawn by hypothesis, which shrinks one that breaks the promise."""
        value = self.data.draw(st.from_type(kind))
        self.run.drawn.append(copy.deepcopy(value))
        return value


def loaded(files: Repository) -> Project:
    """Read the declaration of a repository holding `files`, with its layers, as lup reads a repository's.

    Raise `ProjectError` where a file that's there doesn't load.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repository"
        configuration = Path(directory) / "configuration"
        layout = RepositoryLayout(root=root, main=root)
        machine = MachineLayout(configuration=configuration)
        for path, text in [
            (layout.declaration, files.declaration),
            (layout.local, files.local),
            (machine.layer, files.machine),
        ]:
            if text is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        return read(layout, machine).project


def promises(module: Module) -> list[Entry]:
    """Return every promise `module` serves, in the order declared."""
    served = Doors(
        served=[Serves(module=module, part=each) for each in module.held(Parts)]
    )
    return [
        entry
        for entry in served.entries()
        if isinstance(entry.method.door, PromiseDoor)
    ]


def document_of(modules: list[Module]) -> Viewing | None:
    """Return the document's root view, as the core module among `modules` names it."""
    return next(
        (module.document for module in modules if isinstance(module, Core)), None
    )
