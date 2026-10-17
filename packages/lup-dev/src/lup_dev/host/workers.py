"""A launch's modules, served from a process of its own, of the repository's approved copy.

The host service serves every launch with the `lup-dev` installed for the
operator. A module's code, lup's or a project's, runs in each launch's own
process instead (`lup_dev.worker`), started from the repository's approved copy
(`Register.judge`) when the launch opens: so it's the code the operator approved
for that repository, and one project's module never runs inside the process
serving the others' launches. The service asks it, on a socket beside the
launch's record that the room doesn't mount, what its modules serve, then
passes it each call to one of their tools, each room's request of a kind
they answer, and each moment their hooks run at, one typed request per
connection, one reply. It's stopped when
the launch ends, and started again where it died.
"""

import asyncio
import shlex
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from lup.sessions.terminal import Event
from lup.tools.serving import Answer
from lup.tools.tool import ToolSpec
from lup.types import JsonObject, MutableModel
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import HostError, Refused, Register, Reply, Request
from lup_dev.layout import HostLayout

if TYPE_CHECKING:
    from pathlib import Path


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


class Listing(Request):
    """Ask what a launch's modules serve."""

    kind: Literal["module-listing"] = "module-listing"


type Occasion = Event | Literal["launched", "stopped"]
"""When a module's hooks may run, as the service tells it: the launch opening, the
launch ending once its session has fully stopped, and each event a runtime's
hooks are read as."""


class Offered(Reply):
    """What a launch's modules serve: each tool, each kind of the room's requests they answer, and each occasion their hooks run at."""

    kind: Literal["module-offered"] = "module-offered"
    tools: list[ToolSpec] = []
    kinds: list[str] = []
    occasions: list[Occasion] = []


class Happening(Request):
    """Tell a launch's modules an occasion their hooks run at."""

    kind: Literal["module-happening"] = "module-happening"
    occasion: Occasion
    conversation: Conversation | None = None
    """The conversation it's of, for a session's events."""
    call: str | None = None
    tool: str | None = None


class Happened(Reply):
    """The hooks ran: what failed among them, each said whole."""

    kind: Literal["module-happened"] = "module-happened"
    failures: list[str] = []


class Calling(Request):
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


class Relaying(Request):
    """Pass a room's request to the module answering its kind."""

    kind: Literal["module-request"] = "module-request"
    request: JsonObject
    """The room's request, as it sent it."""


class Relayed(Reply):
    """A module's reply to a room's request, as the room reads it."""

    kind: Literal["module-relayed"] = "module-relayed"
    reply: JsonObject


type Answered = Annotated[
    Offered | Called | Relayed | Happened, Field(discriminator="kind")
]
"""Whatever a launch's modules reply, told apart by its `kind`."""


class Sent(Request, extra="allow"):
    """A room's request as it sent it: its kind, and the fields of its own model."""


class Passed(Reply, extra="allow"):
    """A module's reply, passed to the room whole: its kind, and the fields of its own model."""


class LaunchModules(ABC):
    """Serves each launch's modules: what they offer, each call to them, and their end."""

    @abstractmethod
    async def open(self, launch: Register) -> Offered:
        """Start serving `launch`'s modules, and return what they offer.

        Raise `HostError` where they can't be served.
        """

    @abstractmethod
    async def ask(self, launch: Register, request: Request) -> Reply:
        """Put `request` to `launch`'s modules, starting them again where they're gone, and return their reply."""

    @abstractmethod
    async def close(self, launch: Register) -> None:
        """Stop serving `launch`'s modules."""


class Worker(MutableModel, arbitrary_types_allowed=True):
    """One launch's own process, serving its modules."""

    process: asyncio.subprocess.Process
    offered: Offered


class Workers(MutableModel, LaunchModules, arbitrary_types_allowed=True):
    """Each launch's modules, in a process of its repository's approved copy: `<judge> worker <socket>`.

    The process reads the launch's registration as its input's first line, says
    it's ready on its output's first line, and ends when its input closes, so a
    service that dies takes its launches' processes with it.
    """

    layout: HostLayout
    say: Callable[[str], None]
    running: dict[str, Worker] = {}

    @override
    async def open(self, launch: Register) -> Offered:
        socket = self.layout.modules(launch.launch)
        socket.unlink(missing_ok=True)
        command = [str(launch.judge), "worker", str(socket)]
        try:
            # lup: ignore("subprocess", why="the host service keeps each launch's process running beside its event loop, which sh can't: it forks, and holds a thread per program")
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )
        except OSError as missing:
            message = f"`{shlex.join(command)}` doesn't run: {missing}"
            raise HostError(message) from missing
        if process.stdin is None or process.stdout is None:
            message = f"`{shlex.join(command)}` started without its pipes"
            raise HostError(message)
        process.stdin.write(f"{launch.model_dump_json()}\n".encode())
        await process.stdin.drain()
        ready = await process.stdout.readline()
        if not ready:
            status = await process.wait()
            message = (
                f"`{shlex.join(command)}` ended with status {status} before serving "
                "the launch's modules; what it said is in the host service's output"
            )
            raise HostError(message)
        offered = await self.exchange(launch, Listing())
        if not isinstance(offered, Offered):
            message = f"`{shlex.join(command)}` listed its modules as {offered.kind}"
            raise HostError(message)
        self.running[launch.launch] = Worker(process=process, offered=offered)
        self.say(
            f"{launch.launch}: its modules serve {len(offered.tools)} tools and "
            f"{len(offered.kinds)} kinds of the room's requests, from {launch.judge}"
        )
        return offered

    @override
    async def ask(self, launch: Register, request: Request) -> Reply:
        worker = self.running.get(launch.launch)
        if worker is None or worker.process.returncode is not None:
            self.say(
                f"{launch.launch}: its modules' process is gone; starting it again"
            )
            await self.open(launch)
        return await self.exchange(launch, request)

    async def exchange(self, launch: Register, request: Request) -> Answered:
        """Send one request on `launch`'s modules' socket, and read its reply by its kind.

        A refusal is raised as the `HostError` it says.
        """
        raw = await exchanged(self.layout.modules(launch.launch), request)
        try:
            refused = Refused.model_validate_json(raw)
        except ValidationError:
            return TypeAdapter[Answered](Answered).validate_json(raw)
        raise HostError(refused.error)

    @override
    async def close(self, launch: Register) -> None:
        worker = self.running.pop(launch.launch, None)
        self.layout.modules(launch.launch).unlink(missing_ok=True)
        if worker is None or worker.process.returncode is not None:
            return
        if worker.process.stdin is not None:
            worker.process.stdin.close()
        try:
            await asyncio.wait_for(worker.process.wait(), timeout=5)
        except TimeoutError:
            worker.process.kill()
            await worker.process.wait()
