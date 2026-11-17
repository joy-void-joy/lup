"""The machine's own parts, hosted: started on the operator's machine from the home repository's approved commit, with the sockets every call comes in on.

The parts decide (`lup.hosting`): `Carrying` where each call goes and who it's
by, from the directory it came in on. This is the glue they can't be, since it
binds sockets: one in the operator's directory, which no container mounts, and
one in each container's directory as `Carrying` makes it, each a file, never an
abstract socket. A call is read, routed, and answered by the machine's own
parts or forwarded to the container whose part answers it, its `by` the one
`Carrying` vouched for (`lup/hosting/README.md`, *Carrying*).
"""

import asyncio
from pathlib import Path
from typing import override

from pydantic import TypeAdapter, ValidationError

from lup.declaration.errors import ProjectError
from lup.doors.door import Accepted
from lup.doors.parties import Machine
from lup.environment.declaration import load, resolve
from lup.environment.running.container import answered, asked, declined, listening
from lup.hosting.carrying import Arrival, Carrying, Listens, Route
from lup.running.wire import Call, FormatError, Host, read
from lup.types import MutableModel
lazy from lup.doors.parts import Runs
lazy from lup.environment.doors import Running

CALLS = TypeAdapter[Call](Call)


async def carried(running: Running, directory: Path, text: bytes) -> bytes:
    """Answer one message come in on a socket in `directory`: route it, and answer it here or forward it to the container whose part answers it; nothing sent makes this raise."""
    try:
        call = read(text, CALLS)
    except (FormatError, ValidationError) as wrong:
        return declined(str(wrong))
    arrival = Arrival(directory=directory, call=call)
    routing = await running.serve("routed", arrival.model_dump(mode="json"), Machine())
    if not isinstance(routing, Accepted):
        return declined(routing.rejection.reason)
    route = Route.model_validate(routing.output)
    vouched = route.call.model_dump_json().encode()
    if route.to is None:
        return await answered(running, vouched)
    try:
        return await asked(route.to, vouched)
    except (OSError, ValueError) as lost:
        return declined(f"the container answering it can't be reached: {lost}")


class Binder(MutableModel, Listens, arbitrary_types_allowed=True):
    """What listens on each directory's calling socket on the operator's machine, carrying what comes in as `Carrying` routes it."""

    running: Running
    limit: int
    """The longest message read, in bytes."""
    servers: dict[Path, asyncio.Server] = {}
    """Each socket listened on, by its directory."""

    @override
    async def listened(self, directory: Path) -> None:
        """Listen on `directory`'s calling socket from now on, where nothing does yet."""
        if directory in self.servers:
            return

        async def answer(text: bytes) -> bytes:
            return await carried(self.running, directory, text)

        server = await listening(directory / "calling.sock", answer, limit=self.limit)
        self.servers = {**self.servers, directory: server}

    def closed(self) -> None:
        """Stop listening on every socket."""
        for each in self.servers.values():
            each.close()


async def hosted_parts(host: Host, runs: Runs | None) -> Running:
    """Start the home repository's machine parts, those holding the machine or one for the whole machine, as the machine's own, their data under `host.state`, their programs run by `runs`."""
    resolved = resolve(load(host.root / host.declaration))
    machine = [
        each.named()
        for each in resolved.doors.served
        if each.part.holds().machine or each.part.holds().shared
    ]
    return await resolved.doors.started(
        host.repository,
        {},
        only=machine,
        data=host.state / "data",
        runs=runs,
        machine=True,
    )


async def hosted(host: Host, runs: Runs | None, *, limit: int = 16 * 2**20) -> None:
    """Host the machine's own parts, and carry every call coming in on a socket of theirs until stopped: the operator's, and each container's as `Carrying` makes its directory, a message past `limit` bytes refused.

    Raise `ProjectError` where the home repository's declaration doesn't
    select `Hosting`, which carries calls.
    """
    running = await hosted_parts(host, runs)
    carrying = next(
        (each.made for each in running.made if isinstance(each.made, Carrying)), None
    )
    if carrying is None:
        await running.stopped()
        message = (
            f"{host.repository}'s declaration doesn't select `Hosting`, whose "
            "`Carrying` carries every call: the home repository's must"
        )
        raise ProjectError(message)
    binder = Binder(running=running, limit=limit)
    carrying.listens = binder
    try:
        await binder.listened(carrying.operator())
        await asyncio.Event().wait()
    finally:
        binder.closed()
        await running.stopped()
