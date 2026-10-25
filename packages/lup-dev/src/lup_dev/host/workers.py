"""Each repository's process, of its approved copy: the judge, and the modules, for every launch of it.

The host service serves every launch with the `lup-dev` installed for the
operator. A launch's judge, and a module's code, lup's or a project's, run in
its repository's process instead (`lup_dev.worker`), started from the
repository's approved copy (`Register.judge`): so it's the code the operator
approved for that repository, and one project's module never runs inside the
process serving another's. The service asks it, on a socket of its own under
the host's sockets that no room mounts, what its modules serve, then passes it
each hook the judge reads, each call to one of their tools or to one of the
judge's own that asks the engine, each room's request of a kind they answer,
each view the operator or a room asks of them, and each event their hooks run
at, one typed request per connection, one reply,
each answered at once whatever the others wait on. The launch travels with each
request (`Calling`, `JudgeCalling`, `Relaying`, `Viewing`, `Happening`), never with the
process, which serves each launch of its repository alike.

The process stays running, so a hook costs the judgement alone, not a start of
Python and an import of `lup-dev`. It runs while something holds it (`Holder`):
each of the repository's launches does while it's open. The first request after
one holds it starts it; once nothing has held it for `Workers.idle`, it ends.
One that died is started again at the next request, and what it was answering
is answered as a request it couldn't: one crash interrupts everything in flight
for the repository. Each request finds the copy the repository's approved
command names, and what the operator approved, as it's asked (`docs/trust.md`):
where either is another than the process runs, a process of the approval starts
and answers from then on, and the one before ends once it has answered what it
was asked, a hold waiting for the operator among it.
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

from lup.blocks import Blocks
from lup.events import EventName, Publishing, Told
from lup.programs import ProgramError, Running, started
from lup.publishing import Published, Refusal
from lup.tools.serving import Answer
from lup.tools.tool import ToolSpec
from lup.types import JsonObject, Model, MutableModel
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import HostError, Refused, Register, Reply, Request
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
    """Ask what the repository's modules serve."""

    kind: Literal["module-listing"] = "module-listing"


class Offered(Reply):
    """What the repository's modules serve: each tool, each kind of the room's requests they answer, and each event their hooks run at."""

    kind: Literal["module-offered"] = "module-offered"
    tools: list[ToolSpec] = []
    kinds: list[str] = []
    events: list[EventName] = []
    """Each event their hooks run at, by its name (`lup.events`): the service
    tells them those alone."""


class Happening(Request, reads=False):
    """Tell the repository's modules an event of one of its launches, which their hooks run at."""

    kind: Literal["module-happening"] = "module-happening"
    launch: Register
    """The launch it's of."""
    event: Told
    conversation: Conversation | None = None
    """The conversation it's of: for a session's events, and something a
    conversation would publish."""


class Happened(Reply):
    """The hooks ran: what failed among them, each said whole, and at `Publishing` what they refused."""

    kind: Literal["module-happened"] = "module-happened"
    failures: list[str] = []
    refusals: list[Refusal] = []
    """Each hook's refusal at `Publishing`, a hook that failed there among them."""


class Calling(Request, reads=False):
    """Call one of the repository's modules' tools, for a conversation of one of its launches."""

    kind: Literal["module-call"] = "module-call"
    launch: Register
    """The launch whose session calls."""
    name: str
    arguments: JsonValue
    """The model's arguments, as it sent them: the tool validates them."""
    caller: Conversation


class JudgeCalling(Request, reads=False):
    """Call one of the judge's own tools that asks the engine, for a conversation of one of the repository's launches: the host service serves it, and the repository's process, whose engine is warm, runs it (`policy/tools.py`)."""

    kind: Literal["judge-call"] = "judge-call"
    launch: Register
    """The launch whose session calls."""
    name: str
    arguments: JsonValue
    """The model's arguments, as it sent them: the tool validates them."""
    caller: Conversation


class Called(Reply):
    """What a module's tool, or one of the judge's own, answered."""

    kind: Literal["module-called"] = "module-called"
    answer: Answer


class Relaying(Request, reads=False):
    """Pass a room's request to the module answering its kind."""

    kind: Literal["module-request"] = "module-request"
    launch: Register
    """The launch whose room sent it, as the host service recorded it, never as
    the room says: the room is known by the socket it's heard on."""
    request: JsonObject
    """The room's request, as it sent it."""


class Relayed(Reply):
    """A module's reply to a room's request, as the room reads it."""

    kind: Literal["module-relayed"] = "module-relayed"
    reply: JsonObject


class Viewing(Request, reads=True):
    """Answer one of the repository's modules' views, for the operator, or for a room of one of its launches."""

    kind: Literal["module-view"] = "module-view"
    module: str
    """The module's name."""
    view: str
    """The view's name: its method's."""
    argument: JsonValue
    """What it's given, as the asker sent it: the view's model validates it."""
    launch: Register | None = None
    """The launch whose room asks; none where the operator does."""


class Viewed(Reply):
    """A view's answer: its blocks."""

    kind: Literal["module-viewed"] = "module-viewed"
    blocks: Blocks


class JudgeHook(Request, reads=False):
    """Put one of a launch's hooks the judge reads to its judge."""

    kind: Literal["judge-hook"] = "judge-hook"
    runtime: str
    """The runtime whose hook it is, by its name: the payload says the rest,
    the worktree the judge reads among it."""
    payload: str
    """The hook's payload, as the room's hook sent it."""


class HookJudged(Reply):
    """The judge's answer to a hook: what the room's hook prints."""

    kind: Literal["hook-judged"] = "hook-judged"
    printed: str


type Answered = Annotated[
    Offered | Called | Relayed | Happened | HookJudged | Viewed,
    Field(discriminator="kind"),
]
"""Whatever a repository's process replies, told apart by its `kind`."""

type Replied = Annotated[
    Refused | Offered | Called | Relayed | Happened | HookJudged | Viewed,
    Field(discriminator="kind"),
]
"""A repository's process's reply, or its refusal, told apart by its `kind`."""


class Sent(Request, reads=False, extra="allow"):
    """A room's request as it sent it: its kind, and the fields of its own model; said to write whatever its kind, since its own model isn't known here."""


class Passed(Reply, extra="allow"):
    """A module's reply, passed to the room whole: its kind, and the fields of its own model."""


# lup: ignore("interface-shape", why="the four moments the service drives: a launch opening, its requests, its end, and the service's own stop, which ends what no launch's end does")
class LaunchModules(ABC):
    """Serves each launch's modules and judge from its repository's process: what they offer, each request, the launch's end, and the service's."""

    @abstractmethod
    async def open(self, launch: Register) -> Offered:
        """Hold `launch`'s repository's process while the launch is open, and return what its modules offer.

        The hold stays where they can't be served, so the launch's next request
        tries again. Raise `HostError` where they can't, saying why.
        """

    @abstractmethod
    async def ask(self, launch: Register, request: Request) -> Reply:
        """Put `request` of `launch`'s to its repository's process, starting it where it's gone, and return its reply.

        Raise `HostError` where it couldn't answer, or the launch isn't open,
        saying why.
        """

    @abstractmethod
    async def close(self, launch: Register) -> None:
        """Let go of `launch`'s hold on its repository's process: a request of its still on its way is refused."""

    @abstractmethod
    async def stop(self) -> None:
        """End every repository's process at once, whatever holds it, as the service stops: what each is answering is answered as what it couldn't."""


class LaunchJudge(ABC):
    """Judges each launch's hooks the judge reads, by its repository's approved copy."""

    @abstractmethod
    async def judged(self, launch: Register, payload: str) -> str:
        """Return what one of `launch`'s hooks prints, as its judge answers `payload`.

        It waits for as long as judging does, a hold's wait for the operator
        included. Raise `HostError` where the judge couldn't answer, saying why.
        """


class WorkerJudge(Model, LaunchJudge, arbitrary_types_allowed=True):
    """Each launch's judge, in its repository's process, which serves its modules too (`Workers`)."""

    modules: LaunchModules

    @override
    async def judged(self, launch: Register, payload: str) -> str:
        hook = JudgeHook(runtime=launch.runtime, payload=payload)
        reply = await self.modules.ask(launch, hook)
        match reply:
            case HookJudged(printed=printed):
                return printed
            case _:
                message = f"the repository's process answered a hook with {reply.kind}"
                raise HostError(message)


async def refusals(
    modules: LaunchModules, launch: Register, published: Published
) -> list[Refusal]:
    """Run `launch`'s modules' hooks at `Publishing` on `published`, and return their refusals: none lets it leave.

    Raise `HostError` where they can't be asked, so what can't be checked
    doesn't leave.
    """
    reply = await modules.ask(
        launch, Happening(launch=launch, event=Publishing(published=published))
    )
    match reply:
        case Happened(refusals=refused):
            return refused
        case _:
            message = f"the launch's modules replied {reply.kind} at `Publishing`"
            raise HostError(message)


class Holder(Model):
    """Something that needs a repository's process running, by what it is and which: while any holds it, it runs, or starts at the next request.

    One of the repository's launches holds it while it's open (`launched`);
    whatever else needs the process with no launch open holds it the same way,
    under a kind of its own (#113).
    """

    what: Literal["launch"]
    which: str
    """Which one of its kind: a launch's id."""

    @classmethod
    def launched(cls, launch: Register) -> Holder:
        """Return the hold `launch` has on its repository's process while it's open."""
        return cls(what="launch", which=launch.launch)


class Worker(MutableModel, arbitrary_types_allowed=True):
    """One of a repository's processes: the copy and the approval it runs, where it answers, and what it's answering."""

    process: Running
    command: Path
    """The copy's command it was started from, its links followed: which copy
    it runs, whichever the repository's approved command names since."""
    approval: str | None
    """What the operator had approved for the repository as it started, by its
    fingerprint: the declaration and the person's layer its modules were made
    from. None before any approval."""
    socket: Path
    """Where it answers: its own, so a process ending removes no other's."""
    offered: Offered
    output: asyncio.Task[None]
    """Says what it prints once it's ready, so its pipe never fills."""
    answering: int = 0
    """The requests it's answering, which a process replaced finishes first."""
    idle: asyncio.Event = Field(default_factory=asyncio.Event)
    """Set while it answers nothing."""


class Processes(MutableModel, arbitrary_types_allowed=True):
    """One repository's processes: the one answering, those an approval replaced finishing what they were asked, and what holds them running."""

    running: Worker | None = None
    replaced: list[Worker] = []
    """Its processes of an approval since replaced, finishing what they were
    asked."""
    starting: Path | None = None
    """The command of its process being started."""
    turn: asyncio.Lock = Field(default_factory=asyncio.Lock)
    """Held while its process is found, started or stopped, or a hold on it
    taken or let go, so one starts at a time and none ends under a new hold."""
    holders: list[Holder] = []
    stopping: asyncio.Task[None] | None = None
    """Ends its processes once nothing has held them for a while
    (`Workers.idle`); none while something holds them."""

    def taken(self) -> list[Worker]:
        """Take every one of its processes off it, to end them: none answers its requests from now on."""
        ended = [*([] if self.running is None else [self.running]), *self.replaced]
        self.running = None
        self.replaced = []
        return ended


class Workers(MutableModel, LaunchModules, arbitrary_types_allowed=True):
    """Each repository's process, of its approved copy: `<copy> worker <socket> <repository>`.

    The process says it's ready on its output's first line, and ends when its
    input closes, so a service that dies takes every repository's process with
    it.
    """

    layout: HostLayout
    say: Callable[[str], None]
    approval: Callable[[Path], str | None]
    """What the operator approved last for a repository, by its git directory:
    the approval's fingerprint, which a person's layer approved alone changes
    without installing a copy; none before any approval."""
    ending: timedelta = timedelta(seconds=5)
    """How long a process told to end has before it's killed."""
    idle: timedelta = timedelta(minutes=5)
    """How long a repository's process runs on once nothing holds it, so a launch
    opening soon after the last one ended finds it running, its declaration
    loaded."""
    repositories: dict[Path, Processes] = {}
    """Each repository's processes, by its git directory, kept once made: one
    whose processes ended holds nothing but its lock."""
    retiring: list[asyncio.Task[None]] = []

    @override
    async def open(self, launch: Register) -> Offered:
        await self.hold(launch.repository, Holder.launched(launch))
        async with self.answering(launch) as worker:
            return worker.offered

    @override
    async def ask(self, launch: Register, request: Request) -> Reply:
        async with self.answering(launch) as worker:
            return await self.exchange(worker, request)

    @override
    async def close(self, launch: Register) -> None:
        await self.release(launch.repository, Holder.launched(launch))

    @override
    async def stop(self) -> None:
        for processes in list(self.repositories.values()):
            async with processes.turn:
                processes.holders = []
                if processes.stopping is not None:
                    processes.stopping.cancel()
                    processes.stopping = None
                ended = processes.taken()
            for worker in ended:
                await self.ended(worker)

    def processes(self, repository: Path) -> Processes:
        """Return the processes of the repository whose git directory is `repository`."""
        return self.repositories.setdefault(repository, Processes())

    async def hold(self, repository: Path, holder: Holder) -> None:
        """Count `holder` among what holds `repository`'s process: it runs, or starts at the next request, until nothing has held it for `idle`."""
        processes = self.processes(repository)
        async with processes.turn:
            if holder not in processes.holders:
                processes.holders = [*processes.holders, holder]
            if processes.stopping is not None:
                processes.stopping.cancel()
                processes.stopping = None

    async def release(self, repository: Path, holder: Holder) -> None:
        """Let go of `holder`'s hold on `repository`'s process: where it held it last, the process ends once nothing has held it again for `idle` (`idled`)."""
        processes = self.processes(repository)
        async with processes.turn:
            processes.holders = [each for each in processes.holders if each != holder]
            if processes.holders or processes.stopping is not None:
                return
            processes.stopping = asyncio.create_task(self.idled(repository))

    async def idled(self, repository: Path) -> None:
        """End `repository`'s processes once nothing has held them for `idle`, what they're answering then answered as what they couldn't; a hold taken meanwhile cancels it."""
        processes = self.processes(repository)
        await asyncio.sleep(self.idle.total_seconds())
        async with processes.turn:
            processes.stopping = None
            ended = processes.taken()
        for worker in ended:
            await self.ended(worker)
        if ended:
            self.say(
                f"{repository}: nothing has held its process for {self.idle}, so it "
                "ended"
            )

    def commands(self) -> list[Path]:
        """List the command of each process it runs or is starting, its links followed: the copies in use."""
        return [
            command
            for processes in self.repositories.values()
            for command in [
                *([] if processes.running is None else [processes.running.command]),
                *(worker.command for worker in processes.replaced),
                *([] if processes.starting is None else [processes.starting]),
            ]
        ]

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
        """Return the process answering `launch`'s repository's requests, counted as answering one more.

        It's the one running the copy the launch's approved command names as
        it's asked, its links followed, of what the operator approved last for
        the repository. Where none runs it, because none was started, the one
        started died, or the repository's approved copy or approval changed, one
        is started; a process of the approval replaced goes on answering what it
        was asked, then ends (`retired`). Raise `HostError` where none can
        start, or the launch doesn't hold it: it has ended.
        """
        repository = launch.repository
        processes = self.processes(repository)
        async with processes.turn:
            if Holder.launched(launch) not in processes.holders:
                message = f"launch {launch.launch} has ended"
                raise HostError(message)
            command = launch.judge.resolve()
            approval = self.approval(repository)
            found = processes.running
            if found is not None and found.process.status is not None:
                self.say(f"{repository}: its process is gone; starting it again")
                processes.running = None
                await self.ended(found)
                found = None
            if found is None or (found.command, found.approval) != (command, approval):
                if found is not None:
                    self.say(
                        f"{repository}: approved anew, its copy {command}: a "
                        "process of the approval answers its requests, and the one "
                        f"before, from {found.command}, ends once it has answered "
                        "what it was asked"
                    )
                started = await self.started(repository, command, approval)
                processes.running = started
                if found is not None:
                    self.replace(processes, repository, found)
                found = started
            found.answering += 1
            found.idle.clear()
            return found

    async def started(
        self, repository: Path, command: Path, approval: str | None
    ) -> Worker:
        """Start a process of `repository`'s from `command`, and return it once it has said what its modules serve.

        Raise `HostError` where it doesn't start, or ends before it's ready.
        """
        processes = self.processes(repository)
        socket = self.layout.process(secrets.token_hex(8))
        socket.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        argv = [str(command), "worker", str(socket), str(repository)]
        processes.starting = command
        try:
            try:
                process = await started(*argv)
            except ProgramError as unstarted:
                raise HostError(str(unstarted)) from unstarted
            worker = await self.readied(repository, argv, process, socket, approval)
        finally:
            processes.starting = None
        self.say(
            f"{repository}: its modules serve {len(worker.offered.tools)} tools "
            f"and {len(worker.offered.kinds)} kinds of the room's requests, and its "
            f"judge answers its launches' hooks, from {command}"
        )
        return worker

    async def readied(
        self,
        repository: Path,
        argv: list[str],
        process: Running,
        socket: Path,
        approval: str | None,
    ) -> Worker:
        """Wait until the process is ready, and ask what its modules serve.

        Where it ends first, or doesn't list them, it's ended and `HostError`
        raised.
        """
        ready = await process.output.readline()
        if not ready:
            status = await process.ended()
            message = (
                f"`{shlex.join(argv)}` ended with status {status} before it was "
                "ready; what it said is in the host service's output"
            )
            raise HostError(message)
        output = asyncio.create_task(self.printed(repository, process.output))
        worker = Worker(
            process=process,
            command=Path(argv[0]),
            approval=approval,
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

    async def printed(self, repository: Path, output: asyncio.StreamReader) -> None:
        """Say what a repository's process prints once it's ready, as it comes, until it ends: a module's or a declaration's `print` reaches the service's output rather than filling a pipe nobody reads."""
        while chunk := await output.read(64 * 1024):
            said = chunk.decode(errors="replace").rstrip()
            self.say(f"{repository}: its process printed: {said}")

    def replace(self, processes: Processes, repository: Path, worker: Worker) -> None:
        """Keep `worker`, a process of an approval since replaced, until it has answered what it was asked, then end it."""
        processes.replaced = [*processes.replaced, worker]
        task = asyncio.create_task(self.retired(processes, repository, worker))
        self.retiring = [*(each for each in self.retiring if not each.done()), task]

    async def retired(
        self, processes: Processes, repository: Path, worker: Worker
    ) -> None:
        """End `worker` once it answers nothing: what it was asked, a hold among it, is answered by the copy it started from."""
        await worker.idle.wait()
        await self.ended(worker)
        processes.replaced = [each for each in processes.replaced if each is not worker]
        self.say(
            f"{repository}: its process from {worker.command} has answered what it "
            "was asked, and ended"
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
                f"the repository's process from {worker.command} couldn't be "
                f"reached: {unreached}"
            )
            raise HostError(message) from unreached
        if not raw:
            message = (
                f"the repository's process from {worker.command} ended before it "
                "answered; what it said is in the host service's output"
            )
            raise HostError(message)
        try:
            reply = TypeAdapter[Replied](Replied).validate_json(raw)
        except ValidationError as unread:
            message = (
                f"the repository's process from {worker.command} replied what "
                f"isn't a reply: {unread}"
            )
            raise HostError(message) from unread
        match reply:
            case Refused(error=error):
                raise HostError(error)
            case _:
                return reply
