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
import logging
import shutil
import signal
import sys
from pathlib import Path
from typing import override

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from lup.declaration.errors import ProjectError
from lup.declaration.layout import MachineLayout
from lup.doors.door import Accepted, Answer, Method, RefusedError
from lup.doors.events import Event, Heeded
from lup.doors.parties import Machine
from lup.doors.service import Carrier
from lup.environment.declaration import load, resolve
from lup.environment.running.container import (
    REPLIES,
    answered,
    asked,
    declined,
    listening,
)
from lup.environment.running.planning import plan_of
from lup.environment.settings import LupSettings
from lup.environment.shell.hosted import Served, started
from lup.errors import LupError
from lup.hosting.carrying import (
    Arrival,
    Carrying,
    Forwards,
    Listens,
    Route,
    Visiting,
)
from lup.hosting.containers import Clearing, ContainerError
from lup.hosting.projects import Resumed, Resuming, Sharing
from lup.running.plan import Plan
from lup.running.wire import (
    Answered,
    Asking,
    Declined,
    FormatError,
    Host,
    Offer,
    Offering,
    ServiceCalled,
    read,
)
from lup.types import Model, MutableModel
lazy from lup.doors.parts import Runs
lazy from lup.environment.doors import Running
lazy from lup.shell.looks import Looks

ASKED = TypeAdapter[Asking](Asking)

log = logging.getLogger(__name__)
"""What the machine says of what it couldn't do, in its log."""


async def carried(
    running: Running, directory: Path, text: bytes, looks: Looks
) -> bytes:
    """Answer one message come in on a socket in `directory`: a call, routed and answered here or forwarded to the container whose part answers it, or a question of what the caller may call; nothing sent makes this raise.

    A view the machine's own parts answer is drawn with `looks`, the kinds the
    home repository's modules declare, as a container draws its project's.
    """
    try:
        message = read(text, ASKED)
    except (FormatError, ValidationError) as wrong:
        return declined(str(wrong))
    if isinstance(message, Offering):
        visiting = Visiting(directory=directory, repository=message.repository)
        offering = await running.serve(
            "offered", visiting.model_dump(mode="json"), Machine()
        )
        if not isinstance(offering, Accepted):
            return declined(offering.rejection.reason)
        return Offer.model_validate(offering.output).model_dump_json().encode()
    arrival = Arrival(directory=directory, call=message)
    routing = await running.serve("routed", arrival.model_dump(mode="json"), Machine())
    if not isinstance(routing, Accepted):
        return declined(routing.rejection.reason)
    route = Route.model_validate(routing.output)
    vouched = route.call.model_dump_json().encode()
    if route.to is None:
        return await answered(running, vouched, looks=looks)
    try:
        return await asked(route.to, vouched)
    except (OSError, ValueError) as lost:
        return declined(f"the container answering it can't be reached: {lost}")


class Forwarder(Model, Forwards):
    """What carries a message from the machine to a container's socket, a message past `limit` bytes refused."""

    limit: int

    @override
    async def forwarded(self, socket: Path, text: bytes) -> bytes:
        """Send `text` on `socket`, a container's, and return its answer."""
        return await asked(socket, text, limit=self.limit)


class Binder(MutableModel, Listens, arbitrary_types_allowed=True):
    """What listens on each directory's calling socket on the operator's machine, carrying what comes in as `Carrying` routes it."""

    running: Running
    looks: Looks
    """The kinds the home repository's modules declare, which the views of
    the machine's own parts are drawn with."""
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
            return await carried(self.running, directory, text, self.looks)

        server = await listening(directory / "calling.sock", answer, limit=self.limit)
        self.servers = {**self.servers, directory: server}

    def closed(self) -> None:
        """Stop listening on every socket."""
        for each in self.servers.values():
            each.close()


class Inward(MutableModel, Carrier, arbitrary_types_allowed=True):
    """What carries a service's call the machine's own parts make to a part one for the whole machine that runs in a container of its own: as the machine's, the one call that crosses saying so."""

    running: Running | None = None
    """The machine's parts, whose doors say which part serves a method: set
    once they've started."""
    carrying: Carrying | None = None
    """What knows where each part one for the whole machine runs: set once
    the machine's parts have started."""
    limit: int = 16 * 2**20
    """The longest answer read, in bytes."""

    @override
    async def heeded(self, event: Event) -> Heeded:
        """Tell nobody beyond the machine: an event the machine's own parts fire is heard by its own parts alone, which `Running` told already."""
        del event
        return Heeded()

    @override
    async def carried(self, method: Method, value: BaseModel) -> Answer | JsonValue:
        """Send the call to the container of the part serving it, as the machine's, and return what it answered as JSON.

        Raise `RefusedError` where that part isn't running in a container, or
        its container refuses or can't be reached.
        """
        name = method.taken.qualified
        entry = (
            None
            if self.running is None
            else next(
                (
                    each
                    for each in self.running.doors.entries()
                    if each.method is method
                ),
                None,
            )
        )
        placement = (
            None
            if entry is None or self.carrying is None
            else self.carrying.holding(entry.serves.named())
        )
        if placement is None:
            message = (
                f"`{name}` runs neither on the machine nor in a container of its own"
            )
            raise RefusedError(message, about=[name])
        call = ServiceCalled(
            service=method.taken.name,
            given=value.model_dump(mode="json"),
            by=Machine(),
        )
        try:
            text = await asked(
                placement.listening(), call.model_dump_json().encode(), limit=self.limit
            )
            reply = read(text, REPLIES)
        except (OSError, ValueError, LupError, ValidationError) as lost:
            message = f"`{name}` couldn't be carried to its container: {lost}"
            raise RefusedError(message, about=[name]) from lost
        match reply:
            case Answered(output=output):
                return output
            case Declined(rejection=rejection):
                raise RefusedError(rejection.reason, about=[name])


async def hosted_parts(
    host: Host, runs: Runs | None, inward: Inward, *, contained: bool
) -> Running:
    """Start the home repository's parts holding the machine, as the machine's own, their data under `host.state`, their programs run by `runs`, a service of a part one for the whole machine in a container of its own carried by `inward`.

    Where nothing runs in a container (`contained` false: podman isn't
    there), the parts one for the whole machine run here too: no project's
    code runs anywhere, and the inbox still answers.
    """
    resolved = resolve(load(host.root / host.declaration))
    machine = [
        each.named()
        for each in resolved.doors.served
        if each.part.holds().machine or (each.part.holds().shared and not contained)
    ]
    return await resolved.doors.started(
        host.repository,
        {},
        only=machine,
        beyond=inward,
        data=host.state / "data",
        runtime=host.runtime,
        runs=runs,
        machine=True,
    )


async def hosted(host: Host, runs: Runs | None, *, limit: int = 16 * 2**20) -> None:
    """Host the machine's own parts, and carry every call coming in on a socket of theirs until stopped: the operator's, and each container's as `Carrying` makes its directory, a message past `limit` bytes refused.

    The dashboard is served beside the operator's socket, before it listens
    (`lup.environment.shell.hosted`). Each project the machine's parts ran
    before they last stopped is opened again, every container they left stopped first, since nothing routes
    calls to it any more. Stopped (`SIGTERM`, as `lup stop` sends it), it
    stops listening and runs its parts' `Stopping`, which stop the projects'
    containers. Raise `ProjectError` where the home repository's
    declaration doesn't select `Hosting`, which carries calls, and
    `ContainerError` where podman can't stop those left.
    """
    inward = Inward(limit=limit)
    contained = shutil.which("podman") is not None
    running = await hosted_parts(host, runs, inward, contained=contained)
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
    inward.running = running
    inward.carrying = carrying
    resolved = resolve(load(host.root / host.declaration))
    binder = Binder(running=running, looks=resolved.looks, limit=limit)
    carrying.listens = binder
    carrying.forwards = Forwarder(limit=limit)
    hosting = plan_of(resolved, [], host.root)
    unrun = [each.part for each in running.unrun]
    machine = [
        each
        for each in hosting.parts
        if (each.holds.machine or each.holds.shared) and each.named() not in unrun
    ]
    carrying.hosted = Plan(parts=machine, tools=hosting.tools)
    dashboard: Served | None = None
    try:
        dashboard = await started(
            host,
            running,
            carrying.operator() / "calling.sock",
            MachineLayout(configuration=LupSettings().xdg_config_home),
        )
        await binder.listened(carrying.operator())
        cleared = (
            await running.serve(
                "cleared", Clearing().model_dump(mode="json"), Machine()
            )
            if contained
            else None
        )
        if cleared is not None and not isinstance(cleared, Accepted):
            raise ContainerError(cleared.rejection.reason)
        sharing = Sharing(
            repository=host.repository,
            root=host.root,
            declaration=host.declaration,
            environment=Path(sys.prefix),
            data=host.state / "data",
            plan=hosting,
        )
        shared = (
            await running.serve(
                "machinewide", sharing.model_dump(mode="json"), Machine()
            )
            if contained
            else None
        )
        if shared is not None and not isinstance(shared, Accepted):
            log.warning(
                "lup couldn't start the parts one for the whole machine: %s",
                shared.rejection.reason,
            )
        resumed = await running.serve(
            "resumed", Resuming().model_dump(mode="json"), Machine()
        )
        if not isinstance(resumed, Accepted):
            raise ContainerError(resumed.rejection.reason)
        for repository, why in Resumed.model_validate(resumed.output).refused.items():
            log.warning("lup couldn't open %s again: %s", repository, why)
        stopping = asyncio.Event()
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopping.set)
        await stopping.wait()
    finally:
        if dashboard is not None:
            await dashboard.stopped()
        binder.closed()
        await running.stopped()
