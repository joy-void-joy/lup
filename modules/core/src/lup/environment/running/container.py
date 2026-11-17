"""The program a container runs: a project's parts started, calls through their doors answered on a socket, and a call to a part running elsewhere carried out through the program on the operator's machine.

Each connection is one call: a JSON message, answered with one, every message
carrying the version of its shape, read first (`lup.running.wire`). Who calls is
the program's word, from the socket the call came in on, never the caller's.
A service the parts' code calls is answered here where its part runs here, and
otherwise sent to the program, which carries it to the part's container
(`lup/running/README.md`, *A container*).
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, override
lazy from collections.abc import Awaitable, Callable

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from lup.declaration.errors import ProjectError
from lup.doors.door import Accepted, Answer, Method, Refused, RefusedError, Rejection
from lup.doors.service import Carrier
from lup.environment.declaration import load, resolve
from lup.errors import LupError
from lup.running.wire import (
    ActionCalled,
    Answered,
    Call,
    CommandCalled,
    Declined,
    FormatError,
    Reply,
    ServiceCalled,
    Start,
    ToolCalled,
    read,
)
from lup.types import Model

if TYPE_CHECKING:
    from lup.environment.doors import Running

CALLS = TypeAdapter[Call](Call)
REPLIES = TypeAdapter[Reply](Reply)


def replied(answered: Accepted | Refused) -> Reply:
    """Return a call's answer as it crosses: what the method answered, as JSON, or the refusal."""
    match answered:
        case Accepted(output=BaseModel() as model):
            return Answered(output=model.model_dump(mode="json"))
        case Accepted(output=str() as words):
            return Answered(output=words)
        case Accepted():
            return Answered()
        case Refused(rejection=rejection):
            return Declined(rejection=rejection)


async def answered(running: Running, text: bytes) -> bytes:
    """Answer one message that crossed to a container running `running`: the call it carries, through its door, or why it's refused.

    A message of another version of its shape, or none, is refused in words,
    as is a call no one vouched for, which carries no `by`: only the program on
    the operator's machine sends one here. Nothing sent makes this raise.
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
        case ToolCalled(tool=tool, given=given):
            outcome = await running.call(tool, given, call.by)
        case ServiceCalled(service=service, given=given):
            outcome = await running.serve(service, given, call.by)
        case ActionCalled(module=module, action=action, given=given):
            outcome = await running.act(module, action, given, call.by)
        case CommandCalled(module=module, command=command, given=given):
            outcome = await running.run(module, command, given, call.by)
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


async def started(start: Start) -> Running:
    """Load the project's declaration from its tree, and start the parts `start` names, a call to a service of another part carried out through the program.

    Raise `ProjectError` where the declaration doesn't load or resolve, or a
    part named isn't the project's, or holds a secret not given.
    """
    resolved = resolve(load(start.root / start.declaration))
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
    )


async def served(start: Start, *, limit: int = 16 * 2**20) -> None:
    """Start the parts `start` names, and answer each call that comes in on its socket until the container is stopped, a message past `limit` bytes refused, the parts' `Stopping` run before it ends."""
    running = await started(start)

    async def answer(text: bytes) -> bytes:
        return await answered(running, text)

    server = await listening(start.listening, answer, limit=limit)
    try:
        async with server:
            await server.serve_forever()
    finally:
        await running.stopped()
