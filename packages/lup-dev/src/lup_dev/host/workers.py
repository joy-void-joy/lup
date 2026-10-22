"""A launch's own process, of the repository's approved copy: its judge, and its modules.

The host service serves every launch with the `lup-dev` installed for the
operator. The launch's judge, and a module's code, lup's or a project's, run in
each launch's own process instead (`lup_dev.worker`), started from the
repository's approved copy (`Register.judge`): so it's the code the operator
approved for that repository, and one project's module never runs inside the
process serving the others' launches. The service asks it, on a socket beside
the launch's record that the room doesn't mount, what its modules serve, then
passes it each hook the judge reads, each call to one of their tools, each
room's request of a kind they answer, and each moment their hooks run at, one
typed request per connection, one reply, each answered at once whatever the
others wait on.

The process stays running, so a hook costs the judgement alone, not a start of
Python and an import of `lup-dev`. It's started when the launch opens, stopped
when the launch ends, and started again where it died; a request it was
answering when it died is answered as one it couldn't. Each request finds the
copy the repository's approved command names as it's asked (`docs/trust.md`):
where that's another copy than the process runs, a process of the copy approved
starts and answers from then on, and the one before ends once it has answered
what it was asked, a hold waiting for the operator among it.
"""

import asyncio
import secrets
import shlex
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from lup.programs import ProgramError, Running, started
from lup.sessions.terminal import Event
from lup.tools.serving import Answer
from lup.tools.tool import ToolSpec
from lup.types import JsonObject, Model, MutableModel
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import HostError, Refused, Register, Reply, Request
from lup_dev.host.publishing import Published, Refusal
from lup_dev.layout import HostLayout

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


async def exchanged(path: Path, request: Request) -> str:
    """Send `request` on the socket at `path`, its end marked, and return the reply as it came."""
    reader, writer = await asyncio.open_unix_connection(path)
    try:
        writer.write(request.model_dump_json().encode())
        await writer.drain()
        writer.write_eof()
        return (await reader.read()).decode()
    finally:
        writer.close()
        await writer.wait_closed()


class Listing(Request, reads=True):
    """Ask what a launch's modules serve."""

    kind: Literal["module-listing"] = "module-listing"


type Occasion = Event | Literal["launched", "stopped", "publishing"]
"""When a module's hooks may run, as the service tells it: the launch opening, the
launch ending once its session has fully stopped, something about to leave under
the operator's name, and each event a runtime's hooks are read as."""


class Offered(Reply):
    """What a launch's modules serve: each tool, each kind of the room's requests they answer, and each occasion their hooks run at."""

    kind: Literal["module-offered"] = "module-offered"
    tools: list[ToolSpec] = []
    kinds: list[str] = []
    occasions: list[Occasion] = []


class Happening(Request, reads=False):
    """Tell a launch's modules an occasion their hooks run at."""

    kind: Literal["module-happening"] = "module-happening"
    occasion: Occasion
    conversation: Conversation | None = None
    """The conversation it's of, for a session's events."""
    call: str | None = None
    tool: str | None = None
    published: Published | None = None
    """What would leave, at `publishing`."""


class Happened(Reply):
    """The hooks ran: what failed among them, each said whole, and at `publishing` what they refused."""

    kind: Literal["module-happened"] = "module-happened"
    failures: list[str] = []
    refusals: list[Refusal] = []
    """Each hook's refusal at `publishing`, a hook that failed there among them."""


class Calling(Request, reads=False):
    """Call one of a launch's modules' tools, for a conversation of the launch."""

    kind: Literal["module-call"] = "module-call"
    name: str
    arguments: JsonValue
    """The model's arguments, as it sent them: the tool validates them."""
    caller: Conversation


class Called(Reply):
    """What a module's tool answered."""

    kind: Literal["module-called"] = "module-called"
    answer: Answer


class Relaying(Request, reads=False):
    """Pass a room's request to the module answering its kind."""

    kind: Literal["module-request"] = "module-request"
    request: JsonObject
    """The room's request, as it sent it."""


class Relayed(Reply):
    """A module's reply to a room's request, as the room reads it."""

    kind: Literal["module-relayed"] = "module-relayed"
    reply: JsonObject


class JudgeHook(Request, reads=False):
    """Put one of a launch's hooks the judge reads to its judge."""

    kind: Literal["judge-hook"] = "judge-hook"
    runtime: str
    """The runtime whose hook it is, by its name."""
    payload: str
    """The hook's payload, as the room's hook sent it."""


class HookJudged(Reply):
    """The judge's answer to a hook: what the room's hook prints."""

    kind: Literal["hook-judged"] = "hook-judged"
    printed: str


type Answered = Annotated[
    Offered | Called | Relayed | Happened | HookJudged, Field(discriminator="kind")
]
"""Whatever a launch's process replies, told apart by its `kind`."""

type Replied = Annotated[
    Refused | Offered | Called | Relayed | Happened | HookJudged,
    Field(discriminator="kind"),
]
"""A launch's process's reply, or its refusal, told apart by its `kind`."""


class Sent(Request, reads=False, extra="allow"):
    """A room's request as it sent it: its kind, and the fields of its own model; said to write whatever its kind, since its own model isn't known here."""


class Passed(Reply, extra="allow"):
    """A module's reply, passed to the room whole: its kind, and the fields of its own model."""


class LaunchModules(ABC):
    """Serves each launch's process: what its modules offer, each request to it, and its end."""

    @abstractmethod
    async def open(self, launch: Register) -> Offered:
        """Start serving `launch`'s modules, and return what they offer.

        Raise `HostError` where they can't be served.
        """

    @abstractmethod
    async def ask(self, launch: Register, request: Request) -> Reply:
        """Put `request` to `launch`'s process, starting it again where it's gone, and return its reply.

        Raise `HostError` where it couldn't answer, saying why.
        """

    @abstractmethod
    async def close(self, launch: Register) -> None:
        """Stop serving `launch`'s modules."""


class LaunchJudge(ABC):
    """Judges each launch's hooks the judge reads, by its repository's approved copy."""

    @abstractmethod
    async def judged(self, launch: Register, payload: str) -> str:
        """Return what one of `launch`'s hooks prints, as its judge answers `payload`.

        It waits for as long as judging does, a hold's wait for the operator
        included. Raise `HostError` where the judge couldn't answer, saying why.
        """


class WorkerJudge(Model, LaunchJudge, arbitrary_types_allowed=True):
    """Each launch's judge, in the launch's own process, which serves its modules too (`Workers`)."""

    modules: LaunchModules

    @override
    async def judged(self, launch: Register, payload: str) -> str:
        hook = JudgeHook(runtime=launch.runtime, payload=payload)
        reply = await self.modules.ask(launch, hook)
        match reply:
            case HookJudged(printed=printed):
                return printed
            case _:
                message = f"the launch's process answered a hook with {reply.kind}"
                raise HostError(message)


async def refusals(
    modules: LaunchModules, launch: Register, published: Published
) -> list[Refusal]:
    """Run `launch`'s modules' hooks at `publishing` on `published`, and return their refusals: none lets it leave.

    Raise `HostError` where they can't be asked, so what can't be checked
    doesn't leave.
    """
    reply = await modules.ask(
        launch, Happening(occasion="publishing", published=published)
    )
    match reply:
        case Happened(refusals=refused):
            return refused
        case _:
            message = f"the launch's modules replied {reply.kind} at publishing"
            raise HostError(message)


class Worker(MutableModel, arbitrary_types_allowed=True):
    """One of a launch's processes: the copy it runs, where it answers, and what it's answering."""

    process: Running
    command: Path
    """The copy's command it was started from, its links followed: which copy
    it runs, whichever the repository's approved command names since."""
    socket: Path
    """Where it answers: its own, so a process ending removes no other's."""
    offered: Offered
    output: asyncio.Task[None]
    """Says what it prints once it's ready, so its pipe never fills."""
    answering: int = 0
    """The requests it's answering, which a process replaced finishes first."""
    idle: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set while it answers nothing."""


class Workers(MutableModel, LaunchModules, arbitrary_types_allowed=True):
    """Each launch's process, of its repository's approved copy: `<copy> worker <socket>`.

    The process reads the launch's registration as its input's first line, says
    it's ready on its output's first line, and ends when its input closes, so a
    service that dies takes its launches' processes with it.
    """

    layout: HostLayout
    say: Callable[[str], None]
    ending: timedelta = timedelta(seconds=5)
    """How long a process told to end has before it's killed."""
    running: dict[str, Worker] = {}
    """The process answering each launch's requests, by the launch's id."""
    replaced: dict[str, list[Worker]] = {}
    """Each launch's processes of a copy the approved one replaced, finishing
    what they were asked."""
    starting: dict[str, Path] = {}
    """The command of each launch's process being started."""
    turns: dict[str, asyncio.Lock] = {}
    """Held while a launch's process is found or started, so one starts at a time."""
    closed: list[str] = []
    """The launches it stopped serving: a request of theirs still on its way
    starts no process."""
    retiring: list[asyncio.Task[None]] = []

    @override
    async def open(self, launch: Register) -> Offered:
        async with self.answering(launch) as worker:
            return worker.offered

    @override
    async def ask(self, launch: Register, request: Request) -> Reply:
        async with self.answering(launch) as worker:
            return await self.exchange(worker, request)

    @override
    async def close(self, launch: Register) -> None:
        async with self.turn(launch.launch):
            self.closed = [*self.closed, launch.launch]
            current = self.running.pop(launch.launch, None)
            ended = [
                *([] if current is None else [current]),
                *self.replaced.pop(launch.launch, []),
            ]
        for worker in ended:
            await self.ended(worker)
        self.turns.pop(launch.launch, None)

    def commands(self) -> list[Path]:
        """List the command of each process it runs or is starting, its links followed: the copies in use."""
        return [
            *(worker.command for worker in self.running.values()),
            *(worker.command for each in self.replaced.values() for worker in each),
            *self.starting.values(),
        ]

    def turn(self, launch: str) -> asyncio.Lock:
        """Return the lock held while launch `launch`'s process is found or started."""
        return self.turns.setdefault(launch, asyncio.Lock())

    @asynccontextmanager
    async def answering(self, launch: Register) -> AsyncGenerator[Worker]:
        """Hold the process answering `launch`, counted as answering one more request while the context is open (`current`)."""
        worker = await self.current(launch)
        try:
            yield worker
        finally:
            worker.answering -= 1
            if not worker.answering:
                worker.idle.set()

    async def current(self, launch: Register) -> Worker:
        """Return the process answering `launch`'s requests, counted as answering one more.

        It's the one running the copy the launch's approved command names as
        it's asked, its links followed. Where none runs it, because none was
        started, the one started died, or the repository's approved copy
        changed, one is started; a process of the copy replaced goes on
        answering what it was asked, then ends (`retired`). Raise `HostError`
        where none can start, or the launch has ended.
        """
        async with self.turn(launch.launch):
            if launch.launch in self.closed:
                message = f"launch {launch.launch} has ended"
                raise HostError(message)
            command = launch.judge.resolve()
            found = self.running.get(launch.launch)
            alive = found is not None and found.process.status is None
            if found is None or not alive or found.command != command:
                if found is not None and not alive:
                    self.say(f"{launch.launch}: its process is gone; starting it again")
                    await self.ended(found)
                if found is not None and alive:
                    self.say(
                        f"{launch.launch}: its repository's approved copy is "
                        f"{command}: its process starts from it, and the one from "
                        f"{found.command} ends once it has answered what it was "
                        "asked"
                    )
                started = await self.started(launch, command)
                self.running[launch.launch] = started
                if found is not None and alive:
                    self.replace(launch.launch, found)
                found = started
            found.answering += 1
            found.idle.clear()
            return found

    async def started(self, launch: Register, command: Path) -> Worker:
        """Start a process of `launch`'s from `command`, and return it once it has said what its modules serve.

        Raise `HostError` where it doesn't start, or ends before it's ready.
        """
        socket = self.layout.modules(launch.launch, secrets.token_hex(4))
        argv = [str(command), "worker", str(socket)]
        self.starting[launch.launch] = command
        try:
            try:
                process = await started(*argv)
            except ProgramError as unstarted:
                raise HostError(str(unstarted)) from unstarted
            worker = await self.readied(launch, argv, process, socket, command)
        finally:
            del self.starting[launch.launch]
        self.say(
            f"{launch.launch}: its modules serve {len(worker.offered.tools)} tools "
            f"and {len(worker.offered.kinds)} kinds of the room's requests, and its "
            f"judge answers its hooks, from {command}"
        )
        return worker

    async def readied(
        self,
        launch: Register,
        argv: list[str],
        process: Running,
        socket: Path,
        command: Path,
    ) -> Worker:
        """Hand the process `launch`'s registration, wait until it's ready, and ask what its modules serve.

        Where it ends first, or doesn't list them, it's ended and `HostError`
        raised.
        """
        process.input.write(f"{launch.model_dump_json()}\n".encode())
        await process.input.drain()
        ready = await process.output.readline()
        if not ready:
            status = await process.ended()
            message = (
                f"`{shlex.join(argv)}` ended with status {status} before it was "
                "ready; what it said is in the host service's output"
            )
            raise HostError(message)
        output = asyncio.create_task(self.printed(launch.launch, process.output))
        worker = Worker(
            process=process,
            command=command,
            socket=socket,
            offered=Offered(),
            output=output,
        )
        worker.idle.set()
        try:
            offered = await self.exchange(worker, Listing())
        except HostError:
            await self.ended(worker)
            raise
        if not isinstance(offered, Offered):
            await self.ended(worker)
            message = f"`{shlex.join(argv)}` listed its modules as {offered.kind}"
            raise HostError(message)
        worker.offered = offered
        return worker

    async def printed(self, launch: str, output: asyncio.StreamReader) -> None:
        """Say what a launch's process prints once it's ready, as it comes, until it ends: a module's or a declaration's `print` reaches the service's output rather than filling a pipe nobody reads."""
        while chunk := await output.read(64 * 1024):
            said = chunk.decode(errors="replace").rstrip()
            self.say(f"{launch}: its process printed: {said}")

    def replace(self, launch: str, worker: Worker) -> None:
        """Keep `worker`, a process of a copy the approved one replaced, until it has answered what it was asked, then end it."""
        self.replaced[launch] = [*self.replaced.get(launch, []), worker]
        task = asyncio.create_task(self.retired(launch, worker))
        self.retiring = [*(each for each in self.retiring if not each.done()), task]

    async def retired(self, launch: str, worker: Worker) -> None:
        """End `worker` once it answers nothing: what it was asked, a hold among it, is answered by the copy it started from."""
        await worker.idle.wait()
        await self.ended(worker)
        self.replaced[launch] = [
            each for each in self.replaced.get(launch, []) if each is not worker
        ]
        self.say(
            f"{launch}: its process from {worker.command} has answered what it was "
            "asked, and ended"
        )

    async def ended(self, worker: Worker) -> None:
        """End `worker`: its input closed, then killed where it's still there after `ending`; its socket removed."""
        await worker.process.ended(within=self.ending)
        # What it printed last is said, unless a program it started holds its
        # output open past it.
        await asyncio.wait([worker.output], timeout=self.ending.total_seconds())
        worker.socket.unlink(missing_ok=True)

    async def exchange(self, worker: Worker, request: Request) -> Answered:
        """Send one request to `worker`, and read its reply by its kind.

        A refusal is raised as the `HostError` it says, and so is a process
        that can't be reached, or ends before it replies.
        """
        try:
            raw = await exchanged(worker.socket, request)
        except OSError as unreached:
            message = (
                f"the launch's process from {worker.command} couldn't be reached: "
                f"{unreached}"
            )
            raise HostError(message) from unreached
        if not raw:
            message = (
                f"the launch's process from {worker.command} ended before it "
                "answered; what it said is in the host service's output"
            )
            raise HostError(message)
        try:
            reply = TypeAdapter[Replied](Replied).validate_json(raw)
        except ValidationError as unread:
            message = (
                f"the launch's process from {worker.command} replied what isn't a "
                f"reply: {unread}"
            )
            raise HostError(message) from unread
        match reply:
            case Refused(error=error):
                raise HostError(error)
            case _:
                return reply
