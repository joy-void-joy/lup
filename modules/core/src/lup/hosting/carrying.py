"""`Carrying`: the machine's part deciding where each call goes, and who it's by, from the socket it came in on.

Each container lup starts gets a directory of sockets of its own, mounted at
`/run/lup` in it: `calling.sock`, which it calls out through, and
`listening.sock`, which it answers calls on. Who a call is by is this part's
word, from the directory it came in on, never what the call says: a project's
container is its project's `Codebase`, a session's room is that session's
`Agent`, the operator's directory is the `Operator`. A room may say which of
its session's conversations calls, a subagent's, and nothing else of who it
is. Every socket is a file in a directory no other container mounts,
never an abstract socket, which rooms, sharing the machine's network, could
reach (`README.md` here, *Carrying*).

The sockets themselves, binding and forwarding, are the environment's
(`lup.environment.running.machine`), told of each directory as it's made
(`Listens`); this part keeps where each part runs and decides each route.
"""

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

import lup
from lup.doors.door import RefusedError
from lup.doors.events import Heeded
from lup.doors.parties import Agent, Codebase, Machine, Operator
from lup.doors.parts import Part, Runtime
from lup.errors import LupError
from lup.running.plan import Name, Plan
from lup.running.wire import (
    Answered,
    Call,
    Caller,
    CommandCalled,
    EventCalled,
    Offer,
    Reply,
    ServiceCalled,
    ToolCalled,
    ViewCalled,
    read,
)
from lup.types import Model

REPLIED = TypeAdapter[Reply](Reply)


class Placement(Model):
    """A container lup started for a project's parts: their names, and its directory of sockets."""

    repository: Name
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


class SessionRoom(Model):
    """A session's room, as `Carrying` vouches for what calls from it: the project it works on, the session it's for, and its directory of sockets."""

    repository: Name
    """The project the session works on, as lup names it."""
    session: str
    """lup's id for the session, whose agent every call from it is by."""
    container: str
    directory: Path
    """Its sockets' directory on the machine, mounted at `/run/lup` in it."""


class Leaving(Model):
    """A session's room that stopped, by its session."""

    session: str


class Vouched(Model):
    """Who a call is by, as the socket it came in on says, and the project it's of: theirs, where the operator names one."""

    by: Caller
    repository: str | None


class Placing(Model):
    """Where a project's parts run, as they're started: its plan, and each container."""

    repository: Name
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


class Visiting(Model):
    """A question of what the caller may call, come in on a socket: the directory it came in on, and the project the operator asks about, where it's theirs."""

    directory: Path
    repository: str | None = None


class Route(Model):
    """Where a call goes, and the call as it's carried, its `by` this part's word."""

    to: Path | None
    """The socket of the container whose part answers it; none where the
    machine's own parts do."""
    call: Call


class Naming(Model):
    """A container to give a directory of sockets, by its name."""

    container: Name


class Directory(Model):
    """A container's directory of sockets on the machine."""

    path: Path


class Listens(ABC):
    """What listens on each directory's calling socket where the machine's parts run: the environment's, binding a socket file there and answering what comes in as `Carrying` routes it."""

    @abstractmethod
    async def listened(self, directory: Path) -> None:
        """Listen on `directory`'s calling socket from now on."""


class Forwards(ABC):
    """What carries a message from the machine to the socket a container answers on: the environment's, set where the machine's parts run."""

    @abstractmethod
    async def forwarded(self, socket: Path, text: bytes) -> bytes:
        """Send `text` on `socket` and return the answer.

        Raise `OSError` where nothing answers there.
        """


class Hearing(Model):
    """A session's event, for every part of its project hearing it: the project, the session, and the event, by its class's name, with its facts."""

    repository: str
    session: str
    event: str
    given: JsonValue


class Telling(Model):
    """A part's own event come in on a container's socket: the directory it came in on, and the event's class, by its name, with its facts."""

    directory: Path
    event: str
    given: JsonValue


class Carrying(Part, machine=True, shared=True):
    """The machine's part deciding where each call goes, and who it's by, from the socket it came in on."""

    sockets: Runtime
    """Every directory of sockets, in memory: one per container, and the
    operator's."""
    listens: Listens | None = Field(default=None, exclude=True, repr=False)
    """What listens on each directory's socket as it's made: the
    environment's, set where the machine's parts run; none where calls are
    routed without sockets, as in a promise."""
    forwards: Forwards | None = Field(default=None, exclude=True, repr=False)
    """What carries an event to a container's socket: the environment's, set
    where the machine's parts run; none where nothing is carried, as in a
    promise."""
    plans: dict[str, Plan] = {}
    """Each project's plan, by its repository."""
    hosted: Plan = Field(default_factory=Plan)
    """The machine's own parts' plan, which every caller is offered beside
    its project's: set where the machine's parts run."""
    placements: list[Placement] = []
    machinewide: list[Placement] = []
    """Each container running a part one for the whole machine that doesn't
    hold the machine, from the home repository's approved commit."""
    rooms: list[SessionRoom] = []
    """Each session's room that's running."""

    def operator(self) -> Path:
        """Return the operator's directory of sockets, which no container mounts: a call coming in there is the operator's."""
        directory = self.sockets.path / "operator"
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    @lup.service
    async def directory(self, naming: Naming, by: Machine) -> Directory:
        """Make a container's directory of sockets, its own, listened on from now on, and return it.

        It's named by a digest of the container's name, short, since a
        socket's path is limited to 108 bytes.
        """
        del by
        digest = hashlib.blake2b(naming.container.encode(), digest_size=8)
        directory = self.sockets.path / "containers" / digest.hexdigest()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.listens is not None:
            await self.listens.listened(directory)
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
    async def sharing(self, placing: Placing, by: Machine) -> None:
        """Keep where the parts one for the whole machine that don't hold the machine run, each in a container of its own, in place of where they ran before."""
        del by
        self.machinewide = list(placing.placements)

    def machines(self, way: Way, call: Call) -> Route:
        """Route a call the machine answers: to the container of a part one for the whole machine that doesn't hold it, where the home repository's plan says one serves it, else to the machine's own parts, which refuse what none of them serves.

        Only the home repository's plan says which part is one for the whole
        machine: a project's plan claiming one is never followed. Where its
        container isn't running, as where podman isn't there and it runs in
        the machine's process, the machine answers, or refuses saying it isn't
        running.
        """
        serving = self.hosted.serving(way.door, way.name, way.module)
        if serving is None or serving.holds.machine or not serving.holds.shared:
            return Route(to=None, call=call)
        sharing = self.holding(serving.named())
        if sharing is None:
            return Route(to=None, call=call)
        return Route(to=sharing.listening(), call=call)

    def holding(self, part: str) -> Placement | None:
        """Return the container running the part named `part` (`module.Part`) one for the whole machine; none where none does."""
        return next((each for each in self.machinewide if part in each.parts), None)

    @lup.service
    async def seated(self, room: SessionRoom, by: Machine) -> None:
        """Keep where a session's room is, in place of where it was before: every call from it is by that session's agent from now on."""
        del by
        self.rooms = [
            *[each for each in self.rooms if each.session != room.session],
            room,
        ]

    @lup.service
    async def left(self, leaving: Leaving, by: Machine) -> None:
        """Forget a session's room that stopped: a call coming in on its directory is refused from now on."""
        del by
        self.rooms = [each for each in self.rooms if each.session != leaving.session]

    @lup.service
    async def heard(self, hearing: Hearing, by: Machine) -> Heeded:
        """Carry a session's event to every part of its project hearing it, in its project's containers and in the session's own room, and return what they answered: their words in that order, and the first refusal.

        A container that doesn't answer, as a room whose parts haven't
        started yet, is passed over.
        """
        del by
        plan = self.plans.get(hearing.repository)
        if plan is None or self.forwards is None:
            return Heeded()
        hearers = [each for each in plan.parts if hearing.event in each.hears]
        sockets = [
            each.listening()
            for each in self.placements
            if each.repository == hearing.repository
            and any(part.named() in each.parts for part in hearers)
        ]
        room = next(
            (each for each in self.rooms if each.session == hearing.session), None
        )
        if room is not None and any(part.holds.room for part in hearers):
            sockets = [*sockets, room.directory / "listening.sock"]
        call = EventCalled(
            event=hearing.event,
            given=hearing.given,
            by=Agent.of(hearing.session),
        )
        told: list[str] = []
        for socket in sockets:
            try:
                answer = await self.forwards.forwarded(
                    socket, call.model_dump_json().encode()
                )
                reply = read(answer, REPLIED)
            except OSError, LupError, ValidationError:
                continue
            if not isinstance(reply, Answered):
                continue
            heeded = Heeded.model_validate(reply.output)
            told = [*told, *heeded.told]
            if heeded.refused is not None:
                return Heeded(told=told, refused=heeded.refused)
        return Heeded(told=told)

    @lup.service
    async def fired(self, telling: Telling, by: Machine) -> Heeded:
        """Carry a part's own event to every part of its project hearing it in the project's other containers, and return what they answered: their words in that order, and the first refusal, after which none is told.

        Only a project's own code fires one, from its container, to its own
        project's parts alone; the container it came from told its own parts
        already. A container hearing it that doesn't answer, or refuses to read
        it, refuses it, since a check that didn't run let nothing through.
        Raise `RefusedError` where the directory is no project's container.
        """
        del by
        vouched = self.vouched(telling.directory, None)
        repository = vouched.repository
        if not isinstance(vouched.by, Codebase) or repository is None:
            message = (
                f"`{telling.event}` is fired by a project's own code, from one of "
                "its containers, which this socket isn't"
            )
            raise RefusedError(message)
        plan = self.plans.get(repository)
        hearers = (
            []
            if plan is None
            else [each for each in plan.parts if telling.event in each.hears]
        )
        placements = [
            each
            for each in self.placements
            if each.repository == repository
            and each.directory != telling.directory
            and any(part.named() in each.parts for part in hearers)
        ]
        call = EventCalled(event=telling.event, given=telling.given, by=vouched.by)
        told: list[str] = []
        for placement in placements:
            try:
                if self.forwards is None:
                    message = "the machine forwards nothing yet"
                    raise RefusedError(message)
                answer = await self.forwards.forwarded(
                    placement.listening(), call.model_dump_json().encode()
                )
                reply = read(answer, REPLIED)
            except (OSError, LupError, ValidationError) as lost:
                refused = f"`{placement.container}`, hearing `{telling.event}`, didn't answer: {lost}"
                return Heeded(told=told, refused=refused)
            if not isinstance(reply, Answered):
                refused = f"`{placement.container}`, hearing `{telling.event}`, refused to read it: {reply.rejection.reason}"
                return Heeded(told=told, refused=refused)
            heeded = Heeded.model_validate(reply.output)
            told = [*told, *heeded.told]
            if heeded.refused is not None:
                return Heeded(told=told, refused=heeded.refused)
        return Heeded(told=told)

    @lup.service
    async def routed(self, arrival: Arrival, by: Machine) -> Route:
        """Decide where a call come in on a socket goes, and who it's by: the operator on their own directory, a project's code on its container's.

        A call is answered by a part of the caller's project running in one
        of its containers, the project the operator names for theirs; by a
        part one for the whole machine that doesn't hold it, in its own
        container; or else by the machine's own parts, which refuse what none
        of them serves: never by another project's part, and a part a plan
        says is the machine's is only ever the machine's own. Raise
        `RefusedError` where the directory is no container's, no session's
        room nor the operator's, where a conversation is named from anywhere
        but a room, where the call is to a command answered where `lup` is
        typed (`here`), or where the project's part answering the call isn't
        running.
        """
        del by
        vouched = self.vouched(
            arrival.directory, arrival.repository, arrival.call.conversation
        )
        call = arrival.call.model_copy(update={"by": vouched.by, "conversation": None})
        repository = vouched.repository
        plan = None if repository is None else self.plans.get(repository)
        way = way_of(call)
        serving = None if plan is None else plan.serving(way.door, way.name, way.module)
        here = serving is not None and any(
            each.here
            for each in serving.doorways
            if each.door == way.door and each.name == way.name
        )
        if here:
            message = (
                f"{way.said()} is answered where `lup` is typed, over that "
                "worktree's declaration, never carried to where the project runs"
            )
            raise RefusedError(message)
        if serving is None or serving.holds.machine or serving.holds.shared:
            return self.machines(way, call)
        placement = next(
            (
                each
                for each in self.placements
                if each.repository == repository and serving.named() in each.parts
            ),
            None,
        )
        if placement is None:
            message = (
                f"{way.said()} is `{serving.named()}`'s, which isn't running: "
                "a part holding something waits for the operator"
            )
            raise RefusedError(message)
        return Route(to=placement.listening(), call=call)

    @lup.service
    async def offered(self, visiting: Visiting, by: Machine) -> Offer:
        """Say what a caller asking on a socket may call: who they are, from the directory it came in on, and their project's plan, the machine's own parts' beside it.

        A project's parts that the machine runs are the machine's, offered
        once, as the machine's. Raise `RefusedError` where the directory is no
        container's, no session's room nor the operator's.
        """
        del by
        vouched = self.vouched(visiting.directory, visiting.repository)
        repository = vouched.repository
        own = None if repository is None else self.plans.get(repository)
        parts = [
            each
            for each in ([] if own is None else own.parts)
            if not (each.holds.machine or each.holds.shared)
        ]
        tools = [] if own is None else own.tools
        return Offer(
            by=vouched.by,
            plan=Plan(
                parts=[*parts, *self.hosted.parts],
                tools=[*tools, *self.hosted.tools],
            ),
        )

    def vouched(
        self, directory: Path, named: str | None, conversation: str | None = None
    ) -> Vouched:
        """Return who a call coming in on `directory` is by, and the project it's of: the one the operator names (`named`), else the caller's own.

        A session's room vouches for its session's agent, the conversation it
        names within that session where it names one. Raise `RefusedError`
        where the directory is no container's, no session's room nor the
        operator's, or where a caller that isn't a room names a conversation.
        """
        room = next((each for each in self.rooms if each.directory == directory), None)
        if room is not None:
            return Vouched(
                by=Agent.of(room.session, conversation), repository=room.repository
            )
        if conversation is not None:
            message = (
                "only a session's room names the conversation a call is from: "
                f"{directory} is no session's room"
            )
            raise RefusedError(message)
        if directory == self.operator():
            return Vouched(by=Operator(), repository=named)
        placement = next(
            (
                each
                for each in [*self.placements, *self.machinewide]
                if each.directory == directory
            ),
            None,
        )
        if placement is None:
            message = (
                f"{directory} is no container's lup started, no session's room, "
                "nor the operator's"
            )
            raise RefusedError(message)
        return Vouched(
            by=Codebase(repository=placement.repository),
            repository=placement.repository,
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
        case CommandCalled(module=module, command=command):
            return Way(door="command", name=command, module=module)
        case ViewCalled(module=module, view=view):
            return Way(door="view", name=view, module=module)
