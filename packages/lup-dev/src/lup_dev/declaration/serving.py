"""What a module serves: its methods, each reached through one of the library's doors, grouped in `ModuleServing` classes, and who may ask each.

A module's methods are those of its `ModuleServing` classes, each behind one of
the library's doors (`lup.doors`): `@lup.tool`, an agent's call through MCP;
`@lup.request`, a room's request, routed by the `kind` of the model it takes;
`@lup.on(Event)`, run at one of lup's events; `@lup.view`, what the dashboard
shows and its command prints, laid out from lup's blocks (`lup.blocks`);
`@lup.command`, a command under the module's on the command line. A
module lists its classes in its
`serving`, `Serving.of(GitHubServing)`. A class only groups methods: it narrows
`module` to its own module's class (`module: GitHub`), so they read its settings
with their types, and gives them the module's own context through `self`: its
data directory for the repository (`data`), the other repositories the
declaration names (`related`), where each runtime keeps its records and how
they're read (`recorded`), the items of lup's inbox a conversation exchanged, which the core
keeps (`exchanges`), and the publishing door (`publish`).

**Who asks is the method's** (`Asker`), by its `by` parameter, which hands it its
caller: `Agent`, a conversation of a launch's session calling a tool; `Room`,
code in one of the repository's rooms, untrusted, its launch with it; `Lup`,
lup itself running a hook at an event of a launch, its conversation with it for
a session's events; `Operator`, the operator, from the dashboard or a terminal
on the host. Each door has those who come through it (`askers`), and those a
method leaving `by` out is for: a tool's are `Agent`, a hook's `Lup`, a view's
`Operator | Room`; a request and a command have none, so each says (`by: Room`,
`by: Operator | Room`). Defining a class checks each of its
methods: a `by` naming someone its door never brings, or a request without one,
fails the class's definition, naming the method (`checked`). Who actually asked
is checked again before each call (`ask`), so a room never reaches a method
meant for someone else.

**What leaves under the operator's name** goes through the publishing door first
(`ModuleServing.publish`): every module's hooks at `Publishing`, any refusal
keeping it from leaving.

Each method runs on the host, in the repository's process of its approved copy
(`lup_dev.worker`), which makes its class afresh for each call; never in the
host service that serves every repository. The launch it's for travels with who
asks, as each request carries it.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from types import UnionType
from typing import TYPE_CHECKING, get_args

from pydantic import BaseModel, PydanticUndefinedAnnotation

from lup.doors import (
    CommandDoor,
    Door,
    Method,
    OnDoor,
    RequestDoor,
    ToolDoor,
    ViewDoor,
    served,
)
from lup.events import Event, events
from lup.publishing import Published, Refusal, told
from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.module import Module
from lup_dev.errors import LupDevError
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import Register, Reply, Request
from lup_dev.host.records import Recorded
from lup_dev.inbox.exchanges import Exchanges

if TYPE_CHECKING:
    from lup.tools.tool import ToolSpec


class Asker(Model):
    """Who asks a module's method: each a class of its own, which a method's `by` is typed as."""


class Agent(Asker):
    """A conversation of a launch's session, calling one of its tools: the session's own, or one of its subagents'."""

    launch: Register
    """The launch whose session calls, as the host service recorded it."""
    conversation: Conversation
    """The conversation calling."""


class Room(Asker):
    """Code in one of the repository's rooms, untrusted: whatever the room runs can send its requests, so a method answers it within its launch's limits."""

    launch: Register
    """The launch whose room asks, as the host service recorded it, never as the
    room says."""


class Lup(Asker):
    """lup itself, running a hook at one of its events of a launch."""

    launch: Register
    """The launch the event is of."""
    conversation: Conversation | None = None
    """The conversation it's of: for a session's events, and something a
    conversation would publish; none for a launch's own, and for a push."""


class Operator(Asker):
    """The operator: from the dashboard, or from a terminal on the host, where a command carries their authority."""


class Askers(Model):
    """Who comes through a door, and those a method that leaves out `by` is for."""

    through: list[type[Asker]]
    default: list[type[Asker]]
    """None where a method says who may ask it, as a request does."""


def askers(door: Door) -> Askers:
    """Return who comes through `door`: an agent through a tool's, a room through a request's, lup through a hook's, the operator or a room through a view's."""
    match door:
        case ToolDoor():
            return Askers(through=[Agent], default=[Agent])
        case RequestDoor():
            return Askers(through=[Room], default=[])
        case OnDoor():
            return Askers(through=[Lup], default=[Lup])
        case ViewDoor():
            return Askers(through=[Operator, Room], default=[Operator, Room])
        case CommandDoor():
            return Askers(through=[Operator, Room], default=[])


def said(askers: list[type[Asker]]) -> str:
    """Name a list of askers as a type does, a union for several.

    >>> said([Agent, Room])
    '`Agent | Room`'
    """
    return f"`{' | '.join(each.__name__ for each in askers)}`"


def named(owner: type, name: str, method: Method) -> list[type[Asker]]:
    """Return who `method`, `owner`'s `name`, may be asked by: its `by`'s type, one asker or a union of them; its doors' default askers where it leaves `by` out.

    Raise `ProjectError` naming it where `by` is typed as other than askers'
    own classes, names one its doors never bring, or is left out where a door
    has no default.
    """
    who = f"`{owner.__name__}.{name}`"
    doors = [askers(door) for door in method.doors]
    if method.taken.by is None:
        default = [each for door in doors for each in door.default]
        if not default:
            through = [each for door in doors for each in door.through]
            message = (
                f"{who} is {method.doors[0].says()}, which says who may ask it: "
                f"`by` typed as one of {said(through)}, or a union of them"
            )
            raise ProjectError(message)
        return list(dict.fromkeys(default))
    annotation = method.taken.by.annotation
    typed = get_args(annotation) if isinstance(annotation, UnionType) else [annotation]
    found = [
        each
        for each in typed
        if isinstance(each, type) and issubclass(each, Asker) and each is not Asker
    ]
    if len(found) != len(typed):
        message = (
            f"{who} takes `by` typed {annotation!r}: who asks is one of lup's "
            f"askers, {said([Agent, Room, Lup, Operator])}, or a union of them"
        )
        raise ProjectError(message)
    through = [each for door in doors for each in door.through]
    never = [each for each in found if each not in through]
    if never:
        message = (
            f"{who} takes `by: {' | '.join(each.__name__ for each in found)}`, but "
            f"{method.doors[0].says()} is asked by {said(through)} alone, never by "
            f"{said(never)}"
        )
        raise ProjectError(message)
    return found


def checked(owner: type, name: str, method: Method) -> None:
    """Raise `ProjectError` naming `owner`'s method `name` where it can't be served: who may ask it isn't among who its doors bring (`named`), or, a request, its model isn't a request's with a kind of its own, or what it returns isn't a reply."""
    named(owner, name, method)
    if not method.requested():
        return
    model = method.taken.model.annotation
    if not (issubclass(model, Request) and model is not Request):
        message = (
            f"`{owner.__name__}.{name}` is a request, so it takes the model of the "
            "requests it answers, a `Request` whose `kind` routes them"
        )
        raise ProjectError(message)
    returned = method.taken.returned
    if not (isinstance(returned, type) and issubclass(returned, Reply)):
        message = f"`{owner.__name__}.{name}` is a request, so it returns a `Reply`"
        raise ProjectError(message)


def narrowed(owner: type[BaseModel], field: str) -> type:
    """Return the type `owner` gives `field`, as its class narrows its base's.

    A class naming its module before the module is defined, in the same file, is
    completed here, once it is. Raise `ProjectError` where it can't be, or where
    the type isn't a class.
    """
    try:
        owner.model_rebuild()
    except PydanticUndefinedAnnotation as undefined:
        message = (
            f"`{owner.__name__}` names `{undefined.name}`, which its file doesn't "
            "define: where the module it's made with is in another file, that file "
            f"completes it with `{owner.__name__}.model_rebuild(_types_namespace=…)`"
        )
        raise ProjectError(message) from undefined
    annotation = owner.model_fields[field].annotation
    if not isinstance(annotation, type):
        message = (
            f"`{owner.__name__}` gives `{field}` the type {annotation!r}: narrow it "
            "to one class"
        )
        raise ProjectError(message)
    return annotation


def made_with(owner: type[BaseModel], module: Module) -> bool:
    """Say whether `owner`, a class of a module's methods, is made with `module`, its own module's class."""
    return isinstance(module, narrowed(owner, "module"))


class Publisher(ABC):
    """Where what a module would publish under the operator's name is put to every module's hooks at `Publishing` first."""

    @abstractmethod
    async def refusals(
        self,
        published: Published,
        launch: Register,
        conversation: Conversation | None,
    ) -> list[Refusal]:
        """Run every module's hooks at `Publishing` on `published`, for `launch` and `conversation`, and return their refusals: none lets it leave."""


class UnpublishedError(LupDevError):
    """What a method would publish was refused at `Publishing`; its message lists each refusal."""


class Related(Model):
    """Another repository the declaration names for the project's sessions to read, as the host finds it."""

    name: str
    path: Path
    """Where it is on the host, absolute and resolved."""
    github: str | None
    """Its `owner/name` on GitHub, where its entry gives one."""


class ModuleServing(Model, arbitrary_types_allowed=True):
    """A class of a module's methods, each behind one of the library's doors: `@lup.tool`, `@lup.request`, `@lup.on(Event)`.

    A subclass narrows `module` to its own module's class, so its methods read
    that module's settings with their types. Defining one checks each of its
    methods (`checked`), refusing one whose `by` names someone its door never
    brings, or a request that doesn't say who may ask it.
    """

    module: Module
    data: Path
    """The module's own directory for the repository, under lup's data."""
    related: list[Related]
    """The other repositories the declaration names, as the host finds them."""
    recorded: dict[str, Recorded]
    """Where each runtime keeps its sessions' records on this machine, and how
    they're read, by the runtime's name: a launch's are its runtime's."""
    publisher: Publisher
    """Where what a method would publish is checked first (`publish`)."""
    exchanges: Exchanges
    """Where a view reads the items of lup's inbox a conversation of the
    repository exchanged, which the core keeps."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a method that can't be served: who may ask it isn't among who its doors bring, or it's a request that doesn't take a request and return a reply."""
        super().__pydantic_init_subclass__(**kwargs)
        for name, method in served(cls).items():
            checked(cls, name, method)

    async def publish(
        self, published: Published, naming: str, by: Agent | Room
    ) -> None:
        """Put what `by` would publish under the operator's name to every module's hooks at `Publishing`, before it leaves.

        `naming` names it in a refusal (`this issue`). Raise `UnpublishedError`,
        listing each refusal, where any hook refuses; the method then publishes
        nothing.
        """
        conversation = by.conversation if isinstance(by, Agent) else None
        refused = await self.publisher.refusals(published, by.launch, conversation)
        if refused:
            raise UnpublishedError(told(refused, naming))


def ask(owner: type[ModuleServing], name: str, asker: Asker) -> None:
    """Raise `LupDevError` where `asker` isn't one `owner`'s method `name` may be asked by: its `by`'s type, or its doors' default askers where it leaves `by` out."""
    method = served(owner)[name]
    allowed = named(owner, name, method)
    if not isinstance(asker, tuple(allowed)):
        message = (
            f"`{owner.__name__}.{name}` of `{narrowed(owner, 'module').__name__}` "
            f"is asked by {said(allowed)}, never by `{type(asker).__name__}`"
        )
        raise LupDevError(message)


def tools(owner: type[ModuleServing]) -> list[ToolSpec]:
    """Return what a session is told about each tool `owner` serves, with no instance."""
    return [
        spec for method in served(owner).values() if (spec := method.spec()) is not None
    ]


def requests(owner: type[ModuleServing]) -> dict[str, str]:
    """Return each kind of request `owner` answers, with the name of the method answering it."""
    return {
        method.taken.model.annotation.named(): name
        for name, method in served(owner).items()
        if method.requested()
    }


def asked_by_room(owner: type[ModuleServing], name: str) -> bool:
    """Say whether a room may ask `owner`'s method `name`."""
    return Room in named(owner, name, served(owner)[name])


def listening(owner: type[ModuleServing]) -> list[type[Event]]:
    """Return the events `owner`'s hooks run at, in lup's order."""
    hooked = [event for method in served(owner).values() for event in method.events()]
    return [event for event in events() if event in hooked]


def at(owner: type[ModuleServing], event: type[Event]) -> list[str]:
    """Return the names of `owner`'s hooks that run at `event`, in the order declared."""
    return [name for name, method in served(owner).items() if event in method.events()]
