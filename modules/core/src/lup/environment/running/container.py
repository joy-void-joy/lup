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

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from lup.declaration.errors import ProjectError
from lup.doors.door import Answer, Method, Refused, RefusedError, Rejection
from lup.doors.parties import Codebase
from lup.doors.service import Carrier
from lup.environment.declaration import load, resolve
from lup.environment.shell import viewed
from lup.errors import LupError
from lup.running.wire import (
    Answered,
    Call,
    CommandCalled,
    Declined,
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
    from lup.environment.declaration import Resolved
    from lup.environment.doors import Running
    from lup.environment.shell import Looks

CALLS = TypeAdapter[Call](Call)
REPLIES = TypeAdapter[Reply](Reply)


async def answered(running: Running, looks: Looks, text: bytes) -> bytes:
    """Answer one message that crossed to a container running `running`, whose views may name what `looks` holds: the call it carries, through its door, or why it's refused.

    A message of another version of its shape, or none, is refused in words, as
    is a view whose blocks name a kind nobody declares, the view's fault said
    to whoever read it: nothing sent makes this raise.
    """
    try:
        call = read(text, CALLS)
    except FormatError as other:
        reply: Reply = Declined(rejection=Rejection(submitted=None, reason=str(other)))
        return REPLIES.dump_json(reply)
    except ValidationError as wrong:
        reason = f"a message that crossed isn't a call through a door: {wrong}"
        reply = Declined(rejection=Rejection(submitted=None, reason=reason))
        return REPLIES.dump_json(reply)
    match call:
        case ToolCalled(tool=tool, given=given, by=by):
            outcome = await running.call(tool, given, by)
        case ServiceCalled(service=service, given=given, by=by):
            outcome = await running.serve(service, given, by)
        case CommandCalled(module=module, command=command, given=given, by=by):
            outcome = await running.run(module, command, given, by)
        case ViewCalled(module=module, view=view, given=given, by=by):
            try:
                outcome = await viewed(running, looks, module, view, given, by)
            except BlockError as drawn:
                reason = f"the view `{view}` of `{module}` can't be drawn: {drawn}"
                outcome = Refused(rejection=Rejection(submitted=given, reason=reason))
    return REPLIES.dump_json(replied(outcome))


async def asked(socket: Path, text: bytes) -> bytes:
    """Send one message on `socket` and return the answer it gets: one connection, one message each way."""
    reader, writer = await asyncio.open_unix_connection(socket)
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
    """The program's socket, which this container calls out through."""
    repository: str
    """The repository whose code this container runs: who the program will
    vouch the call is by, whatever it's sent."""

    @override
    async def carried(self, method: Method, value: BaseModel) -> Answer | JsonValue:
        """Send the call to the program, which carries it to the part serving it, and return what it answered as JSON.

        Raise `RefusedError` where it's refused there, or can't be sent.
        """
        call = ServiceCalled(
            service=method.taken.name,
            given=value.model_dump(mode="json"),
            by=Codebase(repository=self.repository),
        )
        name = method.taken.qualified
        try:
            text = await asked(self.calling, call.model_dump_json().encode())
            reply = read(text, REPLIES)
        except (OSError, LupError, ValidationError) as lost:
            message = f"`{name}` couldn't be carried to where its part runs: {lost}"
            raise RefusedError(message, about=[name]) from lost
        match reply:
            case Answered(output=output):
                return output
            case Declined(rejection=rejection):
                raise RefusedError(rejection.reason, about=[name])


def secrets_in(directory: Path | None) -> dict[str, str]:
    """Return each secret a file in `directory` holds, by the file's name; none where there's no directory."""
    if directory is None:
        return {}
    return {
        each.name: each.read_text() for each in directory.iterdir() if each.is_file()
    }


async def started(start: Start, resolved: Resolved) -> Running:
    """Start the parts `start` names of the project's declaration, `resolved`, a call to a service of another part carried out through the program.

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
        beyond=Outward(calling=start.calling, repository=start.repository),
        data=start.data,
    )


async def served(start: Start) -> None:
    """Load the project's declaration from its tree, start the parts `start` names, and answer each call that comes in on its socket until the container is stopped, the parts' `Stopping` run before it ends.

    Raise `ProjectError` where the declaration doesn't load or resolve, or a
    part named isn't the project's, or holds a secret not given.
    """
    resolved = resolve(load(start.root / start.declaration))
    running = await started(start, resolved)

    async def connected(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            text = await reader.readline()
            writer.write(await answered(running, resolved.looks, text) + b"\n")
            await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_unix_server(connected, path=start.listening)
    try:
        async with server:
            await server.serve_forever()
    finally:
        await running.stopped()
