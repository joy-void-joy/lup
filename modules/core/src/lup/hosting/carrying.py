"""`Carrying`: the machine's part deciding where each call goes, and who it's by, from the socket it came in on.

Each container lup starts gets a directory of sockets of its own, mounted at
`/run/lup` in it: `calling.sock`, which it calls out through, and
`listening.sock`, which it answers calls on. Who a call is by is this part's
word, from the directory it came in on, never what the call says: a project's
container is its project's `Codebase`, the operator's directory is the
`Operator`. Every socket is a file in a directory no other container mounts,
never an abstract socket, which rooms, sharing the machine's network, could
reach (`README.md` here, *Carrying*).

The sockets themselves, binding and forwarding, are the environment's
(`lup.environment.running.machine`); this part keeps where each part runs and
decides each route.
"""

from pathlib import Path

import lup
from lup.doors.door import RefusedError
from lup.doors.parties import Codebase, Machine, Operator
from lup.doors.parts import Data, Part
from lup.running.plan import PartPlan, Plan
from lup.running.wire import (
    ActionCalled,
    Call,
    Caller,
    CommandCalled,
    ServiceCalled,
    ToolCalled,
)
from lup.types import Model


class Placement(Model):
    """A container lup started for a project's parts: their names, and its directory of sockets."""

    repository: str
    """The project whose code it runs, as lup names it."""
    parts: list[str]
    """The parts it runs, each `module.Part`."""
    container: str
    directory: Path
    """Its sockets' directory on the machine, mounted at `/run/lup` in it."""

    def listening(self) -> Path:
        """Return the socket it answers calls on."""
        return self.directory / "listening.sock"

    def calling(self) -> Path:
        """Return the socket it calls out through."""
        return self.directory / "calling.sock"


class Placing(Model):
    """Where a project's parts run, as they're started: its plan, and each container."""

    repository: str
    plan: Plan
    placements: list[Placement]


class Arrival(Model):
    """A call come in on a socket: the directory it came in on, and the call as it was sent."""

    directory: Path
    call: Call
    repository: str | None = None
    """The project the operator's call is for, where it's theirs: the one
    whose repository their `lup` runs in. A container's own project is the
    container's, whatever this says."""


class Route(Model):
    """Where a call goes, and the call as it's carried, its `by` this part's word."""

    to: Path | None
    """The socket of the container whose part answers it; none where the
    machine's own parts do."""
    call: Call


class Naming(Model):
    """A container to give a directory of sockets, by its name."""

    container: str


class Directory(Model):
    """A container's directory of sockets on the machine."""

    path: Path


class Placed(Model):
    """Each container lup started that calls come in from, by its directory."""

    placements: list[Placement]


class Carrying(Part, machine=True, shared=True):
    """The machine's part deciding where each call goes, and who it's by, from the socket it came in on."""

    sockets: Data
    """Every directory of sockets: one per container, and the operator's."""
    plans: dict[str, Plan] = {}
    """Each project's plan, by its repository."""
    placements: list[Placement] = []

    def operator(self) -> Path:
        """Return the operator's directory of sockets, which no container mounts: a call coming in there is the operator's."""
        directory = self.sockets.path / "operator"
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    @lup.service
    async def directory(self, naming: Naming, by: Machine) -> Directory:
        """Make a container's directory of sockets, its own, and return it."""
        del by
        directory = self.sockets.path / "containers" / naming.container
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return Directory(path=directory)

    @lup.service
    async def placed(self, placing: Placing, by: Machine) -> None:
        """Keep where a project's parts run, in place of where they ran before."""
        del by
        self.plans = {**self.plans, placing.repository: placing.plan}
        self.placements = [
            *[
                each
                for each in self.placements
                if each.repository != placing.repository
            ],
            *placing.placements,
        ]

    @lup.service
    async def listened(self, asking: Placed, by: Machine) -> Placed:
        """Return each container calls come in from, for the machine to listen on its socket."""
        del asking, by
        return Placed(placements=self.placements)

    @lup.service
    async def routed(self, arrival: Arrival, by: Machine) -> Route:
        """Decide where a call come in on a socket goes, and who it's by: the operator on their own directory, a project's code on its container's.

        A call is answered by a part of the caller's project, the one the
        operator names for theirs, or else by a part one for the whole machine.
        Raise `RefusedError` where the directory is no container's nor the
        operator's, or no part answers the call.
        """
        del by
        caller = self.caller(arrival.directory)
        call = arrival.call.model_copy(update={"by": caller})
        repository = (
            caller.repository if isinstance(caller, Codebase) else arrival.repository
        )
        serving = self.serving(way_of(call), repository)
        if serving is None:
            message = f"no part lup runs answers {way_of(call).said()}"
            raise RefusedError(message)
        placement = next(
            (each for each in self.placements if serving.named() in each.parts),
            None,
        )
        return Route(to=None if placement is None else placement.listening(), call=call)

    def caller(self, directory: Path) -> Caller:
        """Return who a call coming in on `directory` is by.

        Raise `RefusedError` where it's no container's nor the operator's.
        """
        if directory == self.operator():
            return Operator()
        placement = next(
            (each for each in self.placements if each.directory == directory), None
        )
        if placement is None:
            message = f"{directory} is no container's lup started, nor the operator's"
            raise RefusedError(message)
        return Codebase(repository=placement.repository)

    def serving(self, way: Way, repository: str | None) -> PartPlan | None:
        """Return the part answering a call through `way`: of `repository`'s plan first, then any project's part one for the whole machine."""
        own = None if repository is None else self.plans.get(repository)
        found = None if own is None else own.serving(way.door, way.name, way.module)
        if found is not None:
            return found
        return next(
            (
                each
                for plan in self.plans.values()
                if (each := plan.serving(way.door, way.name, way.module)) is not None
                and each.holds.shared
            ),
            None,
        )


class Way(Model):
    """The door a call comes through, the name it's called by, and its module where the name is the module's alone."""

    door: str
    name: str
    module: str | None = None

    def said(self) -> str:
        """Name it as a refusal does: the command `keep` of `hosting`."""
        within = "" if self.module is None else f" of `{self.module}`"
        return f"the {self.door} `{self.name}`{within}"


def way_of(call: Call) -> Way:
    """Return the door `call` comes through, and the name it's called by."""
    match call:
        case ToolCalled(tool=tool):
            return Way(door="tool", name=tool)
        case ServiceCalled(service=service):
            return Way(door="service", name=service)
        case ActionCalled(module=module, action=action):
            return Way(door="action", name=action, module=module)
        case CommandCalled(module=module, command=command):
            return Way(door="command", name=command, module=module)
