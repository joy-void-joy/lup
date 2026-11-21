"""The program a container runs: a project's parts started, calls through their doors answered on a socket, and a call to a part running elsewhere carried out through the program on the operator's machine.

Each connection is one call: a JSON message, answered with one, every message
carrying the version of its shape, read first (`lup.running.wire`). Who calls is
the program's word, from the socket the call came in on, never the caller's.
A service the parts' code calls is answered here where its part runs here, and
otherwise sent to the program, which carries it to the part's container
(`lup/running/README.md`, *A container*).
"""

import asyncio
import signal
from pathlib import Path
from typing import TYPE_CHECKING, override
lazy from collections.abc import Awaitable, Callable

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from lup.declaration.errors import ProjectError
from lup.doors.door import Answer, Method, Refused, RefusedError, Rejection
from lup.doors.on import OnDoor
from lup.doors.service import Carrier
from lup.environment.declaration import Resolved, load, resolve
from lup.environment.running.programs import Local
from lup.environment.shell.viewing import viewed
from lup.errors import LupError
from lup.running.wire import (
    Answered,
    CommandCalled,
    Crossed,
    Declined,
    EventCalled,
    FormatError,
    Reply,
    ServiceCalled,
    Start,
    ToolCalled,
    ViewCalled,
    read,
    replied,
)
from lup.shell.blocks import BlockError
from lup.types import Model

if TYPE_CHECKING:
    from lup.environment.doors import Running
    from lup.shell.looks import Looks

CALLS = TypeAdapter[Crossed](Crossed)
REPLIES = TypeAdapter[Reply](Reply)


async def heeded(running: Running, named: str, given: JsonValue) -> bytes:
    """Run the methods made here run at the event of the class named `named`, `given` as its facts, and answer what they answered (`Heeded`); refused where no method here hears an event of that name, or `given` isn't one."""
    kinds = [
        entry.method.door.event
        for entry in running.here()
        if isinstance(entry.method.door, OnDoor)
        and entry.method.door.event.__name__ == named
    ]
    if not kinds:
        return declined(f"no part here hears an event named `{named}`")
    try:
        event = kinds[0].model_validate(given)
    except ValidationError as wrong:
        return declined(f"what crossed isn't a `{named}`: {wrong}")
    heard = await running.heard(event)
    return REPLIES.dump_json(Answered(output=heard.model_dump(mode="json")))


async def answered(
    running: Running, text: bytes, *, looks: Looks | None = None
) -> bytes:
    """Answer one message that crossed to a container running `running`: the call it carries, through its door, or why it's refused.

    A message of another version of its shape, or none, is refused in words,
    as is a call no one vouched for, which carries no `by`: only the program on
    the operator's machine sends one here. A view is answered where `looks`,
    the kinds its project declares, is given, and refused where what it
    answers names a kind nobody declares, the view's fault said to whoever read
    it. Nothing sent makes this raise.
    """
    try:
        call = read(text, CALLS)
    except FormatError as other:
        return declined(str(other))
    except ValidationError as wrong:
        return declined(f"a message that crossed isn't a call through a door: {wrong}")
    if call.by is None:
        return declined(
            "a call reaches a part only as the program on the operator's machine "
            "vouched for it, saying who it's by: this one says no one"
        )
    match call:
        case EventCalled(event=named, given=given):
            return await heeded(running, named, given)
        case ToolCalled(tool=tool, given=given):
            outcome = await running.call(tool, given, call.by)
        case ServiceCalled(service=service, given=given):
            outcome = await running.serve(service, given, call.by)
        case CommandCalled(module=module, command=command, given=given):
            outcome = await running.run(module, command, given, call.by)
        case ViewCalled(module=module, view=view, given=given) if looks is not None:
            try:
                outcome = await viewed(running, looks, module, view, given, call.by)
            except BlockError as drawn:
                reason = f"the view `{view}` of `{module}` can't be drawn: {drawn}"
                outcome = Refused(rejection=Rejection(submitted=given, reason=reason))
        case ViewCalled():
            return declined("a view isn't answered where nothing declares its kinds")
    return REPLIES.dump_json(replied(outcome))


def declined(reason: str) -> bytes:
    """Return a refusal of a message as it crosses, saying why."""
    reply: Reply = Declined(rejection=Rejection(submitted=None, reason=reason))
    return REPLIES.dump_json(reply)


async def listening(
    socket: Path, answer: Callable[[bytes], Awaitable[bytes]], *, limit: int
) -> asyncio.Server:
    """Answer each connection on `socket`, a file, a stale one replaced: one message each way, a message past `limit` bytes refused rather than read."""

    async def connected(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            try:
                text = await reader.readline()
            except ValueError:
                reply = declined(f"a message past {limit} bytes isn't read")
            else:
                reply = await answer(text)
            writer.write(reply + b"\n")
            await writer.drain()
        finally:
            writer.close()

    await asyncio.to_thread(socket.unlink, missing_ok=True)
    return await asyncio.start_unix_server(connected, path=socket, limit=limit)


async def asked(socket: Path, text: bytes, *, limit: int = 16 * 2**20) -> bytes:
    """Send one message on `socket` and return the answer it gets: one connection, one message each way, an answer past `limit` bytes raising `ValueError`."""
    reader, writer = await asyncio.open_unix_connection(socket, limit=limit)
    try:
        writer.write(text + b"\n")
        await writer.drain()
        return await reader.readline()
    finally:
        writer.close()
        await writer.wait_closed()


class Outward(Model, Carrier):
    """What carries a service's call from a container to a part running elsewhere: the program on the operator's machine, through its socket."""

    calling: Path
    """The program's socket, which this container calls out through: the
    program says who the call is by, from the socket, so it's sent without."""

    @override
    async def carried(self, method: Method, value: BaseModel) -> Answer | JsonValue:
        """Send the call to the program, which carries it to the part serving it, and return what it answered as JSON.

        Raise `RefusedError` where it's refused there, or can't be sent.
        """
        call = ServiceCalled(
            service=method.taken.name, given=value.model_dump(mode="json")
        )
        name = method.taken.qualified
        try:
            text = await asked(self.calling, call.model_dump_json().encode())
            reply = read(text, REPLIES)
        except (OSError, ValueError, LupError, ValidationError) as lost:
            message = f"`{name}` couldn't be carried to where its part runs: {lost}"
            raise RefusedError(message, about=[name]) from lost
        match reply:
            case Answered(output=output):
                return output
            case Declined(rejection=rejection):
                raise RefusedError(rejection.reason, about=[name])


def secrets_in(directory: Path | None) -> dict[str, str]:
    """Return each secret a file in `directory` holds, by the file's name, each file removed once read, and the directory with them, so a secret is handed over once; none where there's no directory."""
    if directory is None:
        return {}
    files = [each for each in directory.iterdir() if each.is_file()]
    secrets = {each.name: each.read_text() for each in files}
    for each in files:
        each.unlink()
    directory.rmdir()
    return secrets


async def started(start: Start, resolved: Resolved) -> Running:
    """Start the parts `start` names of the project `resolved` from its declaration, a call to a service of another part carried out through the program.

    Raise `ProjectError` where a part named isn't the project's, or holds a
    secret not given.
    """
    named = [each.named() for each in resolved.doors.served]
    wanted = (
        start.parts
        if start.parts is not None
        else [
            each.named()
            for each in resolved.doors.served
            if not each.part.holds().anything()
        ]
    )
    missing = [each for each in wanted if each not in named]
    if missing:
        message = (
            f"the project has no part {', '.join(f'`{each}`' for each in missing)}"
        )
        raise ProjectError(message, about=missing)
    return await resolved.doors.started(
        start.repository,
        secrets_in(start.secrets),
        only=wanted,
        beyond=Outward(calling=start.calling),
        data=start.data,
        runtime=start.runtime,
        runs=Local(),
        git=start.git,
        ssh=start.ssh,
    )


async def served(start: Start, *, limit: int = 16 * 2**20) -> None:
    """Load the project's declaration from its tree, start the parts `start` names, and answer each call that comes in on its socket until the container is stopped, a message past `limit` bytes refused.

    Stopped (podman sends `SIGTERM`), it takes no new call, finishes each it's
    answering, then runs the parts' `Stopping` before it ends: the machine
    starts a project's next containers and routes calls to them before
    stopping these, so a restart cuts no call.
    """
    resolved = resolve(load(start.root / start.declaration))
    running = await started(start, resolved)

    async def answer(text: bytes) -> bytes:
        return await answered(running, text, looks=resolved.looks)

    server = await listening(start.listening, answer, limit=limit)
    stopping = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopping.set)
    try:
        await stopping.wait()
        server.close()
        await server.wait_closed()
    finally:
        await running.stopped()
