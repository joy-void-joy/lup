"""A typed Python function, given to an agent as a tool.

`@lup_tool` turns an async function taking one pydantic model and returning
another into a tool: its name is the function's, its description the docstring,
its input the parameter's model. Its `before` hooks run on the validated input,
in order, before the function does. A validation error, or a hook's `Deny`,
answers the call instead, so the agent reads why and calls again within its turn.

A tool runs in the caller's process; each adapter delivers it its runtime's way,
through what `AgentTool` says about it: its description and its call.
"""

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, JsonValue, ValidationError

from lup.errors import LupError
from lup.sessions.results import Rejection
from lup.types import JsonObject, Model


class ToolError(LupError):
    """A function can't be a tool: it takes other than one model, or has no docstring."""


class Allow(Model):
    """Let the call through to the tool's function."""


class Deny(Model):
    """Refuse the call; `reason` reaches the agent as the tool's answer."""

    reason: str


type Hook[I] = Callable[[I], Awaitable[Allow | Deny]]
"""A check on a call's validated input, run before the tool's function."""


class ToolSpec(Model):
    """What a session tells the model about a tool."""

    name: str
    description: str
    input_schema: JsonObject
    """The input model's JSON Schema."""


class Accepted(Model, arbitrary_types_allowed=True):
    """A call the tool ran: its validated input, and the answer the agent reads."""

    value: BaseModel
    answer: str
    """The function's output, as JSON."""


class Refused(Model):
    """A call the tool refused, and why: what the agent reads instead of an answer."""

    rejection: Rejection


class AgentTool(ABC):
    """What a session serves to the model, and calls when the model asks."""

    @abstractmethod
    def spec(self) -> ToolSpec:
        """Return the tool's name, description and input schema."""

    @abstractmethod
    async def call(self, arguments: JsonValue) -> Accepted | Refused:
        """Validate the model's arguments, review them, and run the tool on them."""


def is_model(annotation: type | None) -> bool:
    """Say whether an annotation is a pydantic model class.

    >>> is_model(Allow), is_model(int)
    (True, False)
    """
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


class Tool[I: BaseModel, O: BaseModel](Model, AgentTool, arbitrary_types_allowed=True):
    """A typed async function the agent may call, with the hooks that review each call."""

    name: str
    description: str
    input: type[I]
    function: Callable[[I], Awaitable[O]]
    before: list[Hook[I]] = []

    def spec(self) -> ToolSpec:
        """Return the tool's name, description and input model's schema."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input.model_json_schema(),
        )

    async def call(self, arguments: JsonValue) -> Accepted | Refused:
        """Validate `arguments`, run each hook in turn, then the function.

        Every validation error is in the refusal's reason, so one answer tells the
        agent everything to fix.
        """
        try:
            value = self.input.model_validate(arguments)
        except ValidationError as invalid:
            return Refused(
                rejection=Rejection(submitted=arguments, reason=str(invalid))
            )
        for hook in self.before:
            match await hook(value):
                case Deny(reason=reason):
                    return Refused(
                        rejection=Rejection(submitted=arguments, reason=reason)
                    )
                case Allow():
                    pass
        output = await self.function(value)
        return Accepted(value=value, answer=output.model_dump_json())


def lup_tool[I: BaseModel, O: BaseModel](
    function: Callable[[I], Awaitable[O]],
) -> Tool[I, O]:
    """Return `function` as a tool, named for it and described by its docstring.

    The function is async, takes one pydantic model and returns another.
    """
    description = inspect.getdoc(function)
    if description is None:
        message = f"the tool `{function.__name__}` needs a docstring: it's what the model reads"
        raise ToolError(message)
    signature = inspect.signature(function)
    match list(signature.parameters.values()):
        case [parameter]:
            annotation = parameter.annotation
        case parameters:
            message = (
                f"the tool `{function.__name__}` takes {len(parameters)} parameters; "
                "a tool takes one pydantic model"
            )
            raise ToolError(message)
    if not (is_model(annotation) and is_model(signature.return_annotation)):
        message = f"the tool `{function.__name__}` must take one pydantic model and return another"
        raise ToolError(message)
    return Tool[I, O](
        name=function.__name__,
        description=description,
        input=annotation,
        function=function,
    )
