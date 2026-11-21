"""The harness as the gate runs it: lup started in this process, its doors called through `Doors`, every law checked over each slice of each call, and values drawn by hypothesis.

A law reads its module's state through a door of the module that only reads:
a tool marked `reads=True` answering the state its step names, taking nothing
it must be given and no `by`, since a module's state is the same whoever asks
(`lup/testing/README.md`, *Laws*).
"""

import asyncio
import copy
import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from pathlib import Path
from typing import override

from hypothesis import strategies as st
from pydantic import BaseModel, TypeAdapter

from lup.core import Core
from lup.declaration.errors import ProjectError
from lup.declaration.layout import MachineLayout, RepositoryLayout
from lup.declaration.module import Module
from lup.declaration.project import Project
from lup.doors.door import Accepted, DoorError, Method, Refused
from lup.doors.parties import Agent, Party
from lup.doors.parts import Finished, Parts, Program, Runs, UnrunError
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
    BrokenLawError,
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


class Run(MutableModel, arbitrary_types_allowed=True):
    """What one run of a promise did: the values it drew, the calls it made and the order their slices ran in, kept to say what broke it."""

    # lup: ignore("bare-object", why="a value drawn is of whatever kind its promise asked the harness for, bytes and sets among them, which no one type holds")
    drawn: list[object] = []
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


class Law(Model, arbitrary_types_allowed=True):
    """A law a module holds, with the door its state is read through, on lup as it runs."""

    entry: Entry
    state: Entry
    running: Running

    @property
    def method(self) -> Method:
        """The law's method."""
        return self.entry.method

    def said(self) -> str:
        """Name the law, as a broken one is named: `CounterPromises.never_goes_back`."""
        return self.method.taken.qualified

    def read(self) -> BaseModel:
        """Return the module's state, as its door that only reads answers it, at once: it's read between two slices, where nothing else may run.

        Raise `DoorError` where the door waits on something rather than
        answering.
        """
        state = self.state.method
        reading = state.called(
            self.running.part(self.state), state.validated({}), Reader()
        )
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
        verdict = self.method.function(self.running.part(self.entry), step)
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


class Lawful(Model, arbitrary_types_allowed=True):
    """A law a module holds, with the door of its module its state is read through."""

    law: Entry
    state: Entry


def laws(running: Running) -> list[Law]:
    """Return every law the modules `running` serves hold, each with the door its state is read through, on lup as it runs.

    Raise `ProjectError` where a module holding a law has no door that reads
    its state (`readers`).
    """
    return [
        Law(entry=each.law, state=each.state, running=running)
        for each in readers(running.doors)
    ]


def readers(doors: Doors) -> list[Lawful]:
    """Return every law the modules `doors` serve hold, each with the door of its module its state is read through.

    Raise `ProjectError` where a module holding a law has no door that reads,
    answering the state the law's step names, taking nothing it must be given
    and no `by`.
    """
    return [
        Lawful(law=entry, state=state)
        for entry in doors.entries()
        if (state := reader_of(entry, doors)) is not None
    ]


def reader_of(entry: Entry, doors: Doors) -> Entry | None:
    """Return the door the law behind `entry` reads its module's state through; none where it's no law.

    Raise `ProjectError` where its module has none.
    """
    door = entry.method.door
    state = door.law(entry.method.taken) if isinstance(door, PromiseDoor) else None
    if state is None:
        return None
    module = entry.serves.module.name
    reading = [
        each
        for each in doors.through(ToolDoor)
        if each.serves.module.name == module and reads(each, state)
    ]
    if not reading:
        message = (
            f"the law `{entry.method.taken.qualified}` reads `{state.__name__}`, "
            f"which no door of `{module}` that only reads answers: a tool marked "
            "`reads=True`, taking nothing it must be given and no `by`"
        )
        raise ProjectError(message)
    return reading[0]


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
    running: Running
    looks: Looks
    laws: list[Law]
    run: Run

    @property
    def doors(self) -> Doors:
        """What the modules serve."""
        return self.running.doors

    def tools(self) -> list[ToolSpec]:
        """Return what a session is told of each tool the modules serve."""
        return self.running.tools()

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
        class holds isn't given, or where a law its modules hold has no door to
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
        """Start lup on `project`, as the code of `repository`, and return its doors as this harness reaches them, every law its modules hold checked over each call.

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
            laws=laws(running),
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
