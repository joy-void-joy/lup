"""A typed Python function, given to an agent as a tool.

`@lup_tool` turns an async function taking one pydantic model and returning
another into a tool: its name is the function's, its description the docstring,
its input the parameter's model. Its `before` hooks run on the validated input,
in order, before the function does. A validation error, or a hook's `Deny`,
answers the call instead, so the agent reads why and calls again within its turn.

**A tool's summary** is its description's first line, standing alone (a blank
line after it where more follows, as a docstring's summary line does), 50
characters at most, as a git commit's subject line is; the rest is its full
description, as long as it needs. A session that finds tools by searching for
them lists each by its name and summary, so the agent knows what's there. A tool
whose description has no such line is refused when it's made, naming it.

A tool runs in the caller's process; each adapter delivers it its runtime's way,
through what `AgentTool` says about it: its description and its call.
"""

import inspect
import pydoc
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Self

from pydantic import BaseModel, JsonValue, ValidationError, model_validator

from lup.errors import LupError
from lup.sessions.results import Rejection
from lup.types import JsonObject, Model


class ToolError(LupError):
    """A function can't be a tool: it takes other than one model, or its docstring has no summary line."""


class Allow(Model):
    """Let the call through to the tool's function."""


class Deny(Model):
    """Refuse the call; `reason` reaches the agent as the tool's answer."""

    reason: str


type Hook[I] = Callable[[I], Awaitable[Allow | Deny]]
"""A check on a call's validated input, run before the tool's function."""


def summary_of(name: str, description: str, longest: int = 50) -> str:
    """Return the summary of the tool `name`: its description's first line, standing alone, `longest` characters at most.

    Raise `ToolError` naming the tool where the description opens with no line
    standing alone (none at all, or one running onto the next without a blank
    line between), or where that line is longer.

    >>> summary_of("weather", "Look up today's weather.")
    "Look up today's weather."
    """
    line, _ = pydoc.splitdoc(description)
    if not line:
        message = (
            f"the tool `{name}` has no summary: its description opens with one line "
            f"saying what it does, {longest} characters at most, then a blank line "
            "before the rest"
        )
        raise ToolError(message)
    if len(line) > longest:
        message = (
            f"the tool `{name}`'s summary, its description's first line, is "
            f"{len(line)} characters, past {longest}: {line}"
        )
        raise ToolError(message)
    return line


class ToolSpec(Model):
    """What a session tells the model about a tool.

    A spec whose description has no summary line is refused (`summary_of`).
    """

    name: str
    description: str
    """What the model reads about the tool, its summary line first."""
    input_schema: JsonObject
    """The input model's JSON Schema."""

    @model_validator(mode="after")
    def summarized(self) -> Self:
        """Refuse a description without a summary line."""
        summary_of(self.name, self.description)
        return self

    @property
    def summary(self) -> str:
        """The description's first line: what the tool does, in 50 characters at most."""
        return summary_of(self.name, self.description)


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
    """What the model reads about the tool, its summary line first (`summary_of`)."""
    input: type[I]
    function: Callable[[I], Awaitable[O]]
    before: list[Hook[I]] = []

    @model_validator(mode="after")
    def summarized(self) -> Self:
        """Refuse a tool whose description has no summary line, naming it."""
        summary_of(self.name, self.description)
        return self

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

    The function is async, takes one pydantic model and returns another. Its
    docstring's first line, standing alone, is the tool's summary, 50 characters
    at most (`summary_of`).
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
