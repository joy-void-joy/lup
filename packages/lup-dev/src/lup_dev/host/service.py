"""The host service: one per user, on the host, which rooms call for what only it can do.

`docs/launch.md`, *On the host: the service*. It listens on a control socket on the
host only, taking typed requests (`host/protocol.py`), each answered by the handler
routed its kind: the service's own register a launch, end one, list those served,
and stop the service; a module registers its own handlers with the service it
builds (`Route.to`).

Each launch it serves gets a directory of its own holding `hook.sock`, which the
launch's room mounts at `/run/lup`, so the service knows which launch speaks by the
socket it hears it on. The hook socket takes a runtime's raw payload, read to the
end, and answers it by running the launch's judge, its repository's approved copy
of `lup-dev`, as a process of its own (`<judge> hook <runtime>`, the payload on its
input, its answer what it prints), so each session is judged by the code approved
for its repository. Hooks for parallel calls arrive at once and a hold waits for
hours, so each answer waits on its judge in a thread of the service's pool, off
the event loop. Where the judge can't answer (its command missing, or ending with
a failure, a payload it can't read among them), the service answers in the
runtime's own terms through the `Answerer`, rather than closing empty, which the
runtime would take as no decision.

Each launch is recorded beside its directory, so a service started after one
stopped serves the same launches, in the directories their rooms mounted. The
service stops without waiting for the answers in flight: their threads finish
before its process exits, but their hooks hear nothing.
"""

import asyncio
import shlex
import shutil
import traceback
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, override

import sh
from filelock import FileLock, Timeout
from pydantic import ValidationError, field_validator

from lup.types import Model, MutableModel
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


def judged(asked: Asked) -> Judged:
    """Run the judge's process to its end, the payload on its input."""
    program, *arguments = asked.command
    try:
        ran = sh.Command(program)(
            *arguments,
            _in=asked.payload,
            _ok_code=list(range(256)),
            _tty_out=False,
            _return_cmd=True,
        )
    except sh.CommandNotFound as missing:
        return Judged(
            status=127, output="", error=f"`{program}` isn't there: {missing}"
        )
    except sh.ErrorReturnCode as ended:
        # Only a signal ends it outside the statuses taken.
        return Judged(
            status=ended.exit_code,
            output=ended.stdout.decode(errors="replace"),
            error=ended.stderr.decode(errors="replace"),
        )
    return Judged(
        status=ran.exit_code,
        output=ran.stdout.decode(errors="replace"),
        error=ran.stderr.decode(errors="replace"),
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


class Served(Model, arbitrary_types_allowed=True):
    """A launch the service serves, and the server on its hook socket."""

    launch: Register
    server: asyncio.Server


async def closed(server: asyncio.Server) -> None:
    """Close `server` and the connections it holds, its socket file removed."""
    server.close()
    server.close_clients()
    await server.wait_closed()


class Launches(MutableModel, arbitrary_types_allowed=True):
    """The launches the service serves, each on its own hook socket."""

    layout: HostLayout
    answerer: Answerer
    judge: Callable[[Asked], Judged]
    """Runs a launch's judge for one hook; a test gives a stub."""
    say: Callable[[str], None]
    threads: ThreadPoolExecutor
    """The pool each hook is answered in, off the event loop."""
    served: dict[str, Served] = {}

    async def open(self, request: Register) -> Path:
        """Serve a launch: its directory, its hook socket inside, its record.

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

        async def hook(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.hook(request, reader, writer)

        server = await asyncio.start_unix_server(hook, path=sockets.hook)
        self.served[request.launch] = Served(launch=request, server=server)
        self.layout.record(request.launch).write_text(request.model_dump_json(indent=2))
        self.say(
            f"{request.launch}: served, {request.runtime} in {request.worktree}, "
            f"judged by {request.judge}, its sockets in {sockets.directory}"
        )
        return sockets.directory

    async def hook(
        self,
        request: Register,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Answer one hook heard on a launch's socket, and close the connection.

        The payload is read to the end and answered in the pool. Where answering
        fails even so, the failure is said, with its traceback, and the
        connection closes unanswered: the room's hook prints nothing and ends with
        status 0, which the runtime takes as no decision.
        """
        payload = (await reader.read()).decode()
        loop = asyncio.get_running_loop()
        try:
            answer = await loop.run_in_executor(
                self.threads, self.answered, request, payload
            )
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

    def answered(self, request: Register, payload: str) -> str:
        """Return the judge's answer to one hook, or where it can't answer, the runtime's word that it couldn't.

        What the judge said is the service's to tell, in full; the hook's answer
        points there. It blocks for as long as judging does, a hold's wait for
        the operator included.
        """
        asked = Asked(
            command=[str(request.judge), "hook", request.runtime], payload=payload
        )
        ran = self.judge(asked)
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

    async def close(self, launch: str) -> None:
        """End a launch: its hook socket closed, its record and directory removed.

        The directory goes with whatever the room left in it.
        """
        served = self.served.pop(launch, None)
        if served is None:
            message = f"no launch named `{launch}` is served"
            raise HostError(message)
        await closed(served.server)
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
        """Close every launch's hook socket, keeping its record and its directory."""
        for served in self.served.values():
            await closed(served.server)
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
    """The host service: the control socket, a hook socket per launch, the handlers."""

    layout: HostLayout
    answerer: Answerer
    say: Callable[[str], None]
    """Where the service tells what it does: the terminal, or its log."""
    judge: Callable[[Asked], Judged] = judged
    """Runs a launch's judge for one hook, as a process of its own; a test gives a stub."""
    routes: list[Route] = []
    """The handlers modules register, beside the service's own."""
    threads: int = 256
    """How many hooks are answered at once. A hold holds a thread while it waits;
    past this many, a hook waits for a thread."""

    @field_validator("routes")
    @classmethod
    def distinct(cls, routes: list[Route]) -> list[Route]:
        """Refuse two handlers for one kind, the service's own kinds included."""
        kinds = Counter(
            [
                Register.named(),
                Unregister.named(),
                ListLaunches.named(),
                Stop.named(),
                *(route.kind for route in routes),
            ]
        )
        repeated = [kind for kind, count in kinds.items() if count > 1]
        if repeated:
            message = f"more than one handler for {', '.join(sorted(repeated))}"
            raise ValueError(message)
        return routes

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
        and answers in flight are left to finish unheard.
        """
        self.layout.sockets.mkdir(mode=0o700, parents=True, exist_ok=True)
        life = FileLock(self.layout.lock, timeout=0)
        try:
            life.acquire()
        except Timeout as running:
            message = f"a host service runs already, on {self.layout.control}"
            raise HostError(message) from running
        threads = ThreadPoolExecutor(
            max_workers=self.threads, thread_name_prefix="hook"
        )
        launches = Launches(
            layout=self.layout,
            answerer=self.answerer,
            judge=self.judge,
            say=self.say,
            threads=threads,
        )
        stopped = asyncio.Event()
        own = [
            Route.to(Registering(launches=launches)),
            Route.to(Ending(launches=launches)),
            Route.to(Listing(launches=launches)),
            Route.to(Stopping(stopped=stopped)),
        ]
        routes = {route.kind: route for route in [*own, *self.routes]}

        async def control(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            await self.control(routes, reader, writer)

        try:
            await launches.reopen()
            server = await asyncio.start_unix_server(control, path=self.layout.control)
            self.say(f"The host service listens on {self.layout.control}.")
            try:
                yield Serving(stopped=stopped)
            finally:
                await closed(server)
        finally:
            await launches.shut()
            threads.shutdown(wait=False, cancel_futures=True)
            life.release()
            self.say("The host service stopped.")

    async def control(
        self,
        routes: dict[str, Route],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Answer one control request, and close the connection.

        A connection that sends nothing only asks whether the service answers.
        """
        raw = (await reader.read()).decode()
        if raw:
            reply = await self.answered(routes, raw)
            writer.write(reply.model_dump_json().encode())
            await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def answered(self, routes: dict[str, Route], raw: str) -> Reply:
        """Answer one control request with the handler routed its kind.

        A request that doesn't parse, or of no kind routed, is refused, as is one
        its handler refuses or fails on; a failure is said with its traceback.
        """
        try:
            kind = Request.model_validate_json(raw).kind
        except ValidationError as failure:
            return self.refused(f"a request is a JSON object with its kind: {failure}")
        route = routes.get(kind)
        if route is None:
            known = ", ".join(sorted(routes))
            return self.refused(f"no handler for `{kind}`; the service answers {known}")
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
