"""The host service: one per user, on the host, which rooms call for what only it can do.

`docs/launch.md`, *On the host: the service*. It listens on a control socket on the
host only, taking typed requests (`host/protocol.py`), each answered by the handler
routed its kind: the service's own register a launch, end one, list those served,
and stop the service; a module registers its own handlers with the service it
builds (`Route.to`).

Each launch it serves gets a directory of its own, which the launch's room mounts
at `/run/lup`, so the service knows which launch speaks by the socket it hears it
on. It holds three sockets:
- `hook.sock` takes a runtime's raw payload, read to the end. The service reads
  it through the `Courier` (`host/courier.py`), which says whether the launch's
  judge reads it. One it reads is answered by running the judge, its
  repository's approved copy of `lup-dev`, as a process of its own (`<judge>
  hook <runtime>`, the payload on its input, its answer what it prints), so each
  session is judged by the code approved for its repository; one it doesn't is
  answered by the service itself, without starting the judge, as no decision.
  Every answer goes out through the `Courier` again, a call to lup's tools
  rewritten to carry lup's id for the conversation calling. Hooks for parallel
  calls arrive at once and a hold waits for hours, so each judge is spawned
  through asyncio and awaited on the event loop, which goes on serving meanwhile.
  Where the judge can't answer (its command missing, or ending with a failure, a
  payload it can't read among them), the service answers in the runtime's own
  terms through the `Answerer`, rather than closing empty, which the runtime
  would take as no decision.
- `mcp.sock` serves lup's tools, and `request.sock` the room's requests, each
  routed to the modules that registered them (`host/rooms.py`).

Each launch is recorded beside its directory, so a service started after one
stopped serves the same launches, in the directories their rooms mounted. The
service stops without waiting for the answers in flight: their judges are
killed, and their hooks hear nothing.
"""

import asyncio
import shlex
import shutil
import traceback
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Self, override

from filelock import FileLock, Timeout
from pydantic import ValidationError, model_validator

from lup.tools.serving import serve
from lup.types import Model, MutableModel
from lup_dev.host.courier import Conversations, Courier, Telling
from lup_dev.host.protocol import (
    Done,
    HostError,
    Listed,
    ListLaunches,
    Refused,
    Register,
    Registered,
    Reply,
    Request,
    Stop,
    Unregister,
)
from lup_dev.host.rooms import SERVER, LaunchTools, RoomRoute, RoomTools
from lup_dev.layout import HostLayout

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


class Answerer(ABC):
    """What the service knows of each runtime lup knows: its name, and how it hears a hook its judge couldn't answer."""

    @abstractmethod
    def runtimes(self) -> list[str]:
        """Name the runtimes whose hooks the service answers."""

    @abstractmethod
    def unanswered(self, runtime: str, payload: str, failure: str) -> str:
        """Answer one of `runtime`'s hooks its launch's judge couldn't, saying `failure` in the runtime's own terms.

        What the hook prints: a payload in, whether or not it reads as one of the
        runtime's hooks.
        """


class Asked(Model):
    """One hook put to a launch's judge: the command running it, and the payload on its input."""

    command: list[str]
    payload: str


class Judged(Model):
    """How a judge's process ended: its status, what it printed, and what it said beside."""

    status: int
    output: str
    """What it printed: the hook's answer, where `status` is 0."""
    error: str
    """What it wrote to its standard error, or why it couldn't run."""


async def judged(asked: Asked) -> Judged:
    """Run the judge's process to its end, the payload on its input; kill it where the wait is cancelled.

    Spawned rather than forked: `sh` forks from the service's process and runs
    Python in the child before the judge starts, which can deadlock in a process
    with threads, and it would hold a thread per hook for a hold's hours.
    """
    program, *arguments = asked.command
    try:
        # lup: ignore("subprocess", why="the host service awaits each judge on its event loop, which sh can't: it forks, and holds a thread per hook")
        process = await asyncio.create_subprocess_exec(
            program,
            *arguments,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as missing:
        return Judged(
            status=127, output="", error=f"`{program}` doesn't run: {missing}"
        )
    try:
        output, error = await process.communicate(asked.payload.encode())
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return Judged(
        status=await process.wait(),
        output=output.decode(errors="replace"),
        error=error.decode(errors="replace"),
    )


class Handler[R: Request](ABC):
    """Answers one kind of control request; a module registers its own with the service."""

    @abstractmethod
    def request(self) -> type[R]:
        """Return the model of the requests this answers: its `kind` routes them here."""

    @abstractmethod
    async def answer(self, request: R) -> Reply:
        """Answer one request on the service's event loop, off it where it blocks.

        A `HostError` refuses the request with its message.
        """


class Route(Model, arbitrary_types_allowed=True):
    """A handler as the service dispatches to it: its kind, and its answer to the JSON."""

    kind: str
    answer: Callable[[str], Awaitable[Reply]]

    @classmethod
    def to[R: Request](cls, handler: Handler[R]) -> Route:
        """Route the requests of `handler`'s kind to it, each read as its model."""
        model = handler.request()

        async def answered(raw: str) -> Reply:
            return await handler.answer(model.model_validate_json(raw))

        return cls(kind=model.named(), answer=answered)


def bound(room: RoomRoute, launch: Register) -> Route:
    """Route a room's requests of `room`'s kind to its handler, as they come from `launch`'s room."""

    async def answered(raw: str) -> Reply:
        return await room.answer(raw, launch)

    return Route(kind=room.kind, answer=answered)


class Dispatcher(Model, arbitrary_types_allowed=True):
    """One typed request per connection, answered by the route its kind names, and one reply."""

    routes: dict[str, Route]
    answering: str
    """Who answers on the socket, as a refusal names it."""
    say: Callable[[str], None]

    async def connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Answer one request, and close the connection.

        A connection that sends nothing only asks whether the socket answers.
        """
        raw = (await reader.read()).decode()
        if raw:
            reply = await self.answered(raw)
            writer.write(reply.model_dump_json().encode())
            await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def answered(self, raw: str) -> Reply:
        """Answer one request with the route its kind names.

        A request that doesn't parse, or of no kind routed, is refused, as is one
        its handler refuses or fails on; a failure is said with its traceback.
        """
        try:
            kind = Request.model_validate_json(raw).kind
        except ValidationError as failure:
            return self.refused(f"a request is a JSON object with its kind: {failure}")
        route = self.routes.get(kind)
        if route is None:
            known = ", ".join(sorted(self.routes)) or "no kind"
            return self.refused(
                f"no handler for `{kind}`; {self.answering} answers {known}"
            )
        try:
            return await route.answer(raw)
        except (HostError, ValidationError) as failure:
            return self.refused(str(failure))
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"the `{kind}` handler failed:\n{told}")
            return self.refused(f"the `{kind}` handler failed: {failure!r}")

    def refused(self, error: str) -> Refused:
        """Refuse a request, saying why."""
        self.say(f"refused a request: {error}")
        return Refused(error=error)


class Served(Model, arbitrary_types_allowed=True):
    """A launch the service serves: its conversations, and the servers on its sockets."""

    launch: Register
    conversations: Conversations
    servers: list[asyncio.Server]
    """Its hook socket's, its tool server's and its requests' socket's."""


async def closed(server: asyncio.Server) -> None:
    """Close `server` and the connections it holds, its socket file removed."""
    server.close()
    server.close_clients()
    await server.wait_closed()


class Launches(MutableModel, arbitrary_types_allowed=True):
    """The launches the service serves, each on its own sockets."""

    layout: HostLayout
    answerer: Answerer
    courier: Courier
    judge: Callable[[Asked], Awaitable[Judged]]
    """Runs a launch's judge for one hook; a test gives a stub."""
    tools: list[RoomTools]
    room_routes: list[RoomRoute]
    line_limit: int
    """The longest line lup's tool server reads: one MCP message."""
    say: Callable[[str], None]
    served: dict[str, Served] = {}

    async def open(self, request: Register) -> Path:
        """Serve a launch: its directory, its sockets inside, its record.

        A launch served already, running a runtime the answerer doesn't know, or
        whose judge isn't there, is refused. A directory left by a service before
        is used as it is, since the launch's room mounted it.
        """
        if request.launch in self.served:
            message = f"a launch named `{request.launch}` is served already"
            raise HostError(message)
        known = self.answerer.runtimes()
        if request.runtime not in known:
            message = (
                f"no runtime named `{request.runtime}`; "
                f"the service answers {', '.join(known)}"
            )
            raise HostError(message)
        if not request.judge.is_file():
            message = (
                f"the launch's judge, {request.judge}, isn't there: approving the "
                "repository's host zone (`lup-dev trust`) installs it"
            )
            raise HostError(message)
        sockets = self.layout.launch(request.launch)
        sockets.directory.mkdir(parents=True, exist_ok=True)
        conversations = Conversations()

        def said(line: str) -> None:
            self.say(f"{request.launch}: {line}")

        requests = Dispatcher(
            routes={room.kind: bound(room, request) for room in self.room_routes},
            answering="a room's request socket",
            say=said,
        )

        async def hook(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.hook(request, conversations, reader, writer)

        async def tools(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.tools_served(request, conversations, reader, writer)

        async with AsyncExitStack() as opening:
            hooks = await asyncio.start_unix_server(hook, path=sockets.hook)
            opening.push_async_callback(closed, hooks)
            served = await asyncio.start_unix_server(
                tools, path=sockets.mcp, limit=self.line_limit
            )
            opening.push_async_callback(closed, served)
            asked = await asyncio.start_unix_server(
                requests.connection, path=sockets.request
            )
            opening.pop_all()
        self.served[request.launch] = Served(
            launch=request, conversations=conversations, servers=[hooks, served, asked]
        )
        self.layout.record(request.launch).write_text(request.model_dump_json(indent=2))
        self.say(
            f"{request.launch}: served, {request.runtime} in {request.worktree}, "
            f"judged by {request.judge}, its sockets in {sockets.directory}"
        )
        return sockets.directory

    async def hook(
        self,
        request: Register,
        conversations: Conversations,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Answer one hook heard on a launch's socket, and close the connection.

        The payload is read to the end and answered. Where answering fails even
        so, the failure is said, with its traceback, and the connection closes
        unanswered: the room's hook prints nothing and ends with status 0, which
        the runtime takes as no decision.
        """
        payload = (await reader.read()).decode()
        try:
            answer = await self.answered(request, conversations, payload)
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"{request.launch}: answering a hook failed:\n{told}")
            answer = ""
        try:
            writer.write(answer.encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except ConnectionError as gone:
            self.say(f"{request.launch}: the hook was gone before its answer: {gone}")
            return
        self.say(f"{request.launch}: answered a hook")

    async def answered(
        self, request: Register, conversations: Conversations, payload: str
    ) -> str:
        """Return what one hook prints: the judge's answer where it reads the hook, none where it doesn't, with what the courier adds.

        The conversation the hook names gets lup's id here the first time. A
        payload the courier can't read goes to the judge as it is, which answers
        it or says it couldn't; where the courier can't add to the judge's answer,
        the answer goes out as the judge gave it. Either is said.
        """
        try:
            heard = self.courier.heard(request.runtime, payload)
        except ValueError as unread:
            self.say(
                f"{request.launch}: a hook lup couldn't read goes to its judge as it "
                f"is: {unread}"
            )
            return await self.judgement(request, payload)
        conversation = conversations.named(heard.session, heard.agent)
        answer = await self.judgement(request, payload) if heard.judged else ""
        try:
            return self.courier.told(
                request.runtime, payload, answer, Telling(caller=conversation.id)
            )
        except ValueError as unread:
            self.say(
                f"{request.launch}: the judge's answer goes out as it gave it, since "
                f"lup couldn't add to it: {unread}"
            )
            return answer

    async def judgement(self, request: Register, payload: str) -> str:
        """Return the judge's answer to one hook, or where it can't answer, the runtime's word that it couldn't.

        What the judge said is the service's to tell, in full; the hook's answer
        points there. It waits for as long as judging does, a hold's wait for the
        operator included.
        """
        asked = Asked(
            command=[str(request.judge), "hook", request.runtime], payload=payload
        )
        ran = await self.judge(asked)
        if ran.status == 0:
            return ran.output
        command = shlex.join(asked.command)
        self.say(
            f"{request.launch}: `{command}` couldn't answer a hook (status "
            f"{ran.status}). What it said:\n{ran.error}"
        )
        failure = (
            f"`{command}` ended with status {ran.status}; what it said is in the "
            f"host service's output, {self.layout.log} when it runs in the "
            "background"
        )
        return self.answerer.unanswered(request.runtime, payload, failure)

    async def tools_served(
        self,
        request: Register,
        conversations: Conversations,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Serve lup's tools over one connection on a launch's `mcp.sock`, until it closes.

        Where serving breaks (a line past the limit, a connection reset), it's
        said with its traceback, and the connection closes.
        """
        toolset = LaunchTools(
            launch=request, tools=self.tools, conversations=conversations, say=self.say
        )
        try:
            await serve(toolset, reader, writer, name=SERVER)
        except Exception as failure:
            told = "".join(traceback.format_exception(failure))
            self.say(f"{request.launch}: serving lup's tools failed:\n{told}")
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError as gone:
            self.say(
                f"{request.launch}: lup's tool server was gone before it closed: {gone}"
            )

    async def close(self, launch: str) -> None:
        """End a launch: its sockets closed, its record and directory removed.

        The directory goes with whatever the room left in it.
        """
        served = self.served.pop(launch, None)
        if served is None:
            message = f"no launch named `{launch}` is served"
            raise HostError(message)
        for server in served.servers:
            await closed(server)
        self.layout.record(launch).unlink(missing_ok=True)
        shutil.rmtree(self.layout.launch(launch).directory)
        self.say(f"{launch}: ended")

    async def reopen(self) -> None:
        """Serve each launch recorded by a service before, where its room mounted it.

        A record that doesn't read as a launch's, or that this service can't serve,
        is said and left in place.
        """
        for record in sorted(self.layout.launches.glob("*.json")):
            try:
                request = Register.model_validate_json(record.read_text())
                await self.open(request)
            except (ValidationError, HostError) as failure:
                self.say(f"{record} isn't served again: {failure}")

    async def shut(self) -> None:
        """Close every launch's sockets, keeping its record and its directory."""
        for served in self.served.values():
            for server in served.servers:
                await closed(server)
        self.served = {}


class Registering(Model, Handler[Register]):
    """Answers `Register`: the launch served, its socket directory replied."""

    launches: Launches

    @override
    def request(self) -> type[Register]:
        return Register

    @override
    async def answer(self, request: Register) -> Reply:
        return Registered(directory=await self.launches.open(request))


class Ending(Model, Handler[Unregister]):
    """Answers `Unregister`: the launch ended."""

    launches: Launches

    @override
    def request(self) -> type[Unregister]:
        return Unregister

    @override
    async def answer(self, request: Unregister) -> Reply:
        await self.launches.close(request.launch)
        return Done()


class Listing(Model, Handler[ListLaunches]):
    """Answers `ListLaunches`: each launch served, as it was registered."""

    launches: Launches

    @override
    def request(self) -> type[ListLaunches]:
        return ListLaunches

    @override
    async def answer(self, request: ListLaunches) -> Reply:
        return Listed(
            launches=[served.launch for served in self.launches.served.values()]
        )


class Stopping(Model, Handler[Stop], arbitrary_types_allowed=True):
    """Answers `Stop`: the service stops once the reply is written."""

    stopped: asyncio.Event

    @override
    def request(self) -> type[Stop]:
        return Stop

    @override
    async def answer(self, request: Stop) -> Reply:
        self.stopped.set()
        return Done()


class Serving(Model, arbitrary_types_allowed=True):
    """A service while it serves: it stops once `stopped` is set."""

    stopped: asyncio.Event


class HostService(Model, arbitrary_types_allowed=True):
    """The host service: the control socket, each launch's sockets, the handlers and tools modules register."""

    layout: HostLayout
    answerer: Answerer
    courier: Courier
    """Reads each runtime's hooks, and adds to their answers."""
    say: Callable[[str], None]
    """Where the service tells what it does: the terminal, or its log."""
    judge: Callable[[Asked], Awaitable[Judged]] = judged
    """Runs a launch's judge for one hook, as a process of its own; a test gives a stub."""
    routes: list[Route] = []
    """The handlers modules register on the control socket, beside the service's own."""
    room_routes: list[RoomRoute] = []
    """The handlers modules register for the room's requests, on each launch's
    `request.sock`."""
    tools: list[RoomTools] = []
    """The tools modules serve each launched session, on its `mcp.sock`."""
    line_limit: int = 16 * 1024 * 1024
    """The longest line lup's tool server reads, one MCP message: well above
    asyncio's 64 KiB, which a long message to the operator could pass."""

    @model_validator(mode="after")
    def distinct(self) -> Self:
        """Refuse two handlers for one kind, on the control socket and the room's alike, and two modules serving one tool."""
        kinds = Counter(
            [
                Register.named(),
                Unregister.named(),
                ListLaunches.named(),
                Stop.named(),
                *(route.kind for route in self.routes),
                *(route.kind for route in self.room_routes),
            ]
        )
        repeated = [kind for kind, count in kinds.items() if count > 1]
        if repeated:
            message = f"more than one handler for {', '.join(sorted(repeated))}"
            raise ValueError(message)
        names = Counter(spec.name for tools in self.tools for spec in tools.specs())
        twice = [name for name, count in names.items() if count > 1]
        if twice:
            message = f"more than one module serves {', '.join(sorted(twice))}"
            raise ValueError(message)
        return self

    async def serve(self) -> None:
        """Serve until a `Stop` request, or until cancelled."""
        async with self.serving() as serving:
            await serving.stopped.wait()

    @asynccontextmanager
    async def serving(self) -> AsyncGenerator[Serving]:
        """Serve while the context is open: the control socket, and each launch recorded.

        The service holds a lock for its whole life, which the OS frees, so a second
        refuses to start while one runs; a control socket left by a service that
        died is replaced. On leaving, the sockets close, the launches stay recorded,
        and the judges of answers in flight are killed, unheard.
        """
        self.layout.sockets.mkdir(mode=0o700, parents=True, exist_ok=True)
        life = FileLock(self.layout.lock, timeout=0)
        try:
            life.acquire()
        except Timeout as running:
            message = f"a host service runs already, on {self.layout.control}"
            raise HostError(message) from running
        launches = Launches(
            layout=self.layout,
            answerer=self.answerer,
            courier=self.courier,
            judge=self.judge,
            tools=self.tools,
            room_routes=self.room_routes,
            line_limit=self.line_limit,
            say=self.say,
        )
        stopped = asyncio.Event()
        own = [
            Route.to(Registering(launches=launches)),
            Route.to(Ending(launches=launches)),
            Route.to(Listing(launches=launches)),
            Route.to(Stopping(stopped=stopped)),
        ]
        control = Dispatcher(
            routes={route.kind: route for route in [*own, *self.routes]},
            answering="the service",
            say=self.say,
        )
        try:
            await launches.reopen()
            server = await asyncio.start_unix_server(
                control.connection, path=self.layout.control
            )
            self.say(f"The host service listens on {self.layout.control}.")
            try:
                yield Serving(stopped=stopped)
            finally:
                await closed(server)
        finally:
            await launches.shut()
            life.release()
            self.say("The host service stopped.")
