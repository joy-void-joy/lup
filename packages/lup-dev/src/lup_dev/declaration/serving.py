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
`answer` replies, the module and the launch through `self`.

Each runs on the host, in the launch's own process of the repository's approved
copy (`lup_dev.worker`), never in the host service that serves every launch.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, PydanticUndefinedAnnotation

from lup.tools.tool import AgentTool, ToolSpec, bound, declared
from lup.types import Model
from lup_dev.declaration.errors import ProjectError
from lup_dev.declaration.module import Module
from lup_dev.host.courier import Conversation
from lup_dev.host.protocol import Register, Reply, Request


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


class ModuleTools(Model):
    """A module's tools in a launched session: each a method decorated with `@lup_tool`.

    A subclass narrows `module` to its own module's class, so its tools read
    that module's settings with their types.
    """

    module: Module
    launch: Register
    """The launch whose session calls."""
    caller: Conversation
    """The conversation calling: the session's own, or one of its subagents'."""

    @classmethod
    def specs(cls) -> list[ToolSpec]:
        """Return what a session is told about each tool, with no instance."""
        return list(declared(cls).values())

    def tools(self) -> list[AgentTool]:
        """Return each tool, bound to this call."""
        return bound(self)


class ModuleHandler(Model, ABC):
    """A module's answer to one kind of request from a launch's room.

    A subclass narrows `request` to the model of the requests it answers, whose
    `kind` routes them here (`answering`), and `module` to its own module's class.
    """

    module: Module
    launch: Register
    """The launch whose room asks."""
    request: Request

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
