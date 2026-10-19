"""What a module serves a launched session: tools its agent calls, and answers to its room's requests.

A module's tools are methods of a `ModuleTools` class, each decorated with the
library's `@lup_tool`, as a tool for an ask from code is a function. lup makes an
instance for each call, so a tool reaches through `self` what the call is about:
its module's settings (`self.module`, which the class narrows to its own module,
`module: GitHub`), the launch (`self.launch`) and the conversation calling
(`self.caller`). A module lists its classes in its `tools`,
`Toolsets.of(GitHubTools)`.

A room's request is answered the same way: a `ModuleHandler` names the request
it answers by narrowing its `request` field to that request's model, and
`answer` replies, the module, the launch and the module's own data directory for
the repository through `self`.

What a module does at lup's moments is a `ModuleHooks` class, each method run at
a moment marked with the library's `@lup_hook`: at the one its name names, or
those its `on` names. lup's moments are its own three, a launch opening, a launch
ending once its session has fully stopped, and `publishing`, before anything
leaves under the operator's name; and the five each runtime's hooks are read as
(`lup.sessions.terminal.Event`). A hook observes, but at a moment that's
answered (`ANSWERED`: `publishing`) it may refuse, returning its refusals
(`lup_dev.host.publishing`), each naming what it found and where; one refusal
keeps what would leave from leaving. Through `self` it reaches its module, the
launch, where the launch's runtime keeps its sessions' records, and the module's
own data directory for the repository.

A module's tool that would publish something puts it through the door first
(`ModuleTools.publish`), which runs every module's hooks at `publishing`.

Each runs on the host, in the launch's own process of the repository's approved
copy (`lup_dev.worker`), never in the host service that serves every launch.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

from pydantic import BaseModel, PydanticUndefinedAnnotation

from lup.tools.hook import hooks
from lup.tools.tool import AgentTool, ToolSpec, bound, declared
from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.module import Module
from lup_dev.errors import LupDevError
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import Register, Reply, Request
from lup_dev.host.publishing import Published, Refusal, told
from lup_dev.host.records import Records

if TYPE_CHECKING:
    from lup.sessions.terminal import Event


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
    """Say whether `owner`, a class of tools or a handler, is made with `module`, its own module's class."""
    return isinstance(module, narrowed(owner, "module"))


class Door(ABC):
    """Where what a module's tool would publish under the operator's name is put to every module's hooks at `publishing` first."""

    @abstractmethod
    async def refusals(
        self, published: Published, conversation: Conversation | None
    ) -> list[Refusal]:
        """Run every module's hooks at `publishing` on `published`, for `conversation`, and return their refusals: none lets it leave."""


class UnpublishedError(LupDevError):
    """What a tool would publish was refused at the `publishing` moment; its message lists each refusal."""


class ModuleTools(Model, arbitrary_types_allowed=True):
    """A module's tools in a launched session: each a method decorated with `@lup_tool`.

    A subclass narrows `module` to its own module's class, so its tools read
    that module's settings with their types.
    """

    module: Module
    launch: Register
    """The launch whose session calls."""
    caller: Conversation
    """The conversation calling: the session's own, or one of its subagents'."""
    door: Door
    """Where what a tool would publish is checked first (`publish`)."""

    @classmethod
    def specs(cls) -> list[ToolSpec]:
        """Return what a session is told about each tool, with no instance."""
        return list(declared(cls).values())

    def tools(self) -> list[AgentTool]:
        """Return each tool, bound to this call."""
        return bound(self)

    async def publish(self, published: Published, naming: str) -> None:
        """Put what a tool would publish under the operator's name to every module's hooks at `publishing`, before it leaves.

        `naming` names it in a refusal (`this issue`). Raise `UnpublishedError`,
        listing each refusal, where any hook refuses; the tool then publishes
        nothing.
        """
        refused = await self.door.refusals(published, self.caller)
        if refused:
            raise UnpublishedError(told(refused, naming))


class ModuleHandler(Model, ABC):
    """A module's answer to one kind of request from a launch's room.

    A subclass narrows `request` to the model of the requests it answers, whose
    `kind` routes them here (`answering`), and `module` to its own module's class.
    """

    module: Module
    launch: Register
    """The launch whose room asks."""
    request: Request
    data: Path
    """The module's own directory for the repository, under lup's data."""

    @abstractmethod
    async def answer(self) -> Reply:
        """Answer the request, on the launch's process's event loop, off it where it blocks.

        A `HostError` refuses the request with its message.
        """


def answering(handler: type[ModuleHandler]) -> type[Request]:
    """Return the model of the requests `handler` answers, read off its narrowed `request`.

    Raise `ProjectError` where `request` isn't narrowed to a request's model.
    """
    model = narrowed(handler, "request")
    if not issubclass(model, Request) or model is Request:
        message = (
            f"`{handler.__name__}` answers no request: narrow its `request` to the "
            "model of the requests it answers"
        )
        raise ProjectError(message)
    return model


type MomentName = Literal[
    "launched",
    "stopped",
    "publishing",
    "session_started",
    "call_started",
    "call_finished",
    "turn_ended",
    "conversation_ended",
]
"""lup's moments, which a module's hooks run at: a launch opening; a launch ending,
its session fully stopped; something about to leave under the operator's name;
and the five each runtime's hooks are read as."""

ANSWERED: list[MomentName] = ["publishing"]
"""The moments a hook may answer: at `publishing` it returns its refusals. At
every other one it observes, returning nothing."""

HEARD: dict[Event, MomentName] = {
    "session-started": "session_started",
    "call-started": "call_started",
    "call-finished": "call_finished",
    "turn-ended": "turn_ended",
    "conversation-ended": "conversation_ended",
}
"""The moment each of the events a runtime's hooks are read as is."""


class Moment(Model):
    """What's known of a moment a module's hook runs at."""

    name: MomentName
    conversation: Conversation | None = None
    """The conversation it's of, for a session's moments and a post; none for a
    launch's and a push."""
    call: str | None = None
    """The call's id, at a call's start or finish."""
    tool: str | None = None
    """The tool called, by the runtime's name for it."""
    published: Published | None = None
    """What would leave, at `publishing`: a push, or a post."""


class ModuleHooks(Model, arbitrary_types_allowed=True):
    """What a module does at lup's moments: each method marked with `@lup_hook`.

    A subclass narrows `module` to its own module's class, as a class of tools
    does. A hook naming no moment of lup's fails the class's definition. A hook
    at `publishing` returns its refusals, `list[Refusal]`, an empty list letting
    what would leave go; at every other moment it returns nothing.
    """

    module: Module
    launch: Register
    records: Records
    """Where the launch's runtime keeps its sessions' records on this machine."""
    data: Path
    """The module's own directory for the repository, under lup's data."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a hook naming a moment that isn't lup's."""
        super().__pydantic_init_subclass__(**kwargs)
        known = get_args(MomentName.__value__)
        unknown = [
            f"`{name}` at `{moment}`"
            for name, moments in hooks(cls).items()
            for moment in moments
            if moment not in known
        ]
        if unknown:
            message = (
                f"`{cls.__name__}` runs {', '.join(unknown)}, which isn't one of "
                f"lup's moments: {', '.join(known)}"
            )
            raise ProjectError(message)


def listening(hooked: type[ModuleHooks]) -> list[MomentName]:
    """Return the moments a class of hooks runs at, in lup's order."""
    marked = [moment for moments in hooks(hooked).values() for moment in moments]
    return [moment for moment in get_args(MomentName.__value__) if moment in marked]


def at(instance: ModuleHooks, moment: MomentName) -> list[str]:
    """Return the names of `instance`'s hooks that run at `moment`, in the order declared."""
    return [
        name for name, moments in hooks(type(instance)).items() if moment in moments
    ]
