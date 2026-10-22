"""A typed Python function, given to an agent as a tool.

`@lup_tool` turns an async function taking one pydantic model and returning
another into a tool: its name is the function's, its description the docstring,
its input the parameter's model. Its `before` hooks run on the validated input,
in order, before the function does. A validation error, or a hook's `Deny`,
answers the call instead, so the agent reads why and calls again within its turn.
A tool returning a model answers with its JSON; one returning `str` answers in
those words, for a tool whose answer is meant to be read rather than parsed.

On a method (`self` and one model), `@lup_tool` makes a `Method`: read through an
instance, it's that instance's tool, so a class of tools reaches what they share
through `self`; read through the class, it says what the tool is without one.

**A tool's summary** is its description's first line, standing alone (a blank
line after it where more follows, as a docstring's summary line does), 50
characters at most, as a git commit's subject line is; the rest is its full
description, as long as it needs. A session that finds tools by searching for
them lists each by its name and summary, so the agent knows what's there. A tool
whose description has no such line is refused when it's made, naming it.

**A tool's marks** say whether a call to it may be sent again: `reads` where it
only reads, changing nothing, and `idempotent` where a call sent again with the
same arguments adds nothing to what the first did, as one that finds its wait
again. `@lup_tool(reads=True)` and `@lup_tool(idempotent=True)` set them;
unmarked, a tool acts. They're MCP's `readOnlyHint` and `idempotentHint`, which
the server publishes with each tool and lup's bridge reads, to send a call again
across a restart of the server (`lup.sessions.bridge`) only where it's safe.

A tool runs in the caller's process; each adapter delivers it its runtime's way,
through what `AgentTool` says about it: its description and its call.
"""

import inspect
import pydoc
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Self, overload

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
    reads: bool = False
    """Whether the tool only reads, changing nothing: MCP's `readOnlyHint`."""
    idempotent: bool = False
    """Whether a call sent again with the same arguments adds nothing to what
    the first did: MCP's `idempotentHint`."""

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


class Tool[I: BaseModel, O: BaseModel | str](
    Model, AgentTool, arbitrary_types_allowed=True
):
    """A typed async function the agent may call, with the hooks that review each call."""

    name: str
    description: str
    """What the model reads about the tool, its summary line first (`summary_of`)."""
    input: type[I]
    function: Callable[[I], Awaitable[O]]
    before: list[Hook[I]] = []
    reads: bool = False
    """Whether the tool only reads (`ToolSpec.reads`)."""
    idempotent: bool = False
    """Whether a call sent again adds nothing (`ToolSpec.idempotent`)."""

    @model_validator(mode="after")
    def summarized(self) -> Self:
        """Refuse a tool whose description has no summary line, naming it."""
        summary_of(self.name, self.description)
        return self

    def spec(self) -> ToolSpec:
        """Return the tool's name, description, input model's schema and marks."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input.model_json_schema(),
            reads=self.reads,
            idempotent=self.idempotent,
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
        return Accepted(value=value, answer=answered(output))


def answered(output: BaseModel | str) -> str:
    """Return what the agent reads of a tool's output: its words, or a model's JSON.

    >>> answered("Filed."), answered(Deny(reason="no"))
    ('Filed.', '{"reason":"no"}')
    """
    if isinstance(output, str):
        return output
    return output.model_dump_json()


class Shape(Model, arbitrary_types_allowed=True):
    """What a tool's function says of the tool, its name, its description and the parameter taking its model, with the marks its declaration gives it."""

    name: str
    description: str
    parameter: inspect.Parameter
    """The function's one parameter besides `self`, annotated with the model the
    tool takes."""
    reads: bool = False
    idempotent: bool = False

    @classmethod
    def of(
        cls,
        function: Callable[..., Awaitable[BaseModel | str]],
        *,
        reads: bool = False,
        idempotent: bool = False,
    ) -> Shape:
        """Read the tool's shape off its function, a method's `self` left out, marked as `reads` and `idempotent` say.

        Raise `ToolError` naming the function where it has no docstring, where it
        takes other than one pydantic model besides `self`, or where it returns
        other than a pydantic model or `str`.
        """
        name = function.__name__
        description = inspect.getdoc(function)
        if description is None:
            message = f"the tool `{name}` needs a docstring: it's what the model reads"
            raise ToolError(message)
        signature = inspect.signature(function)
        match list(signature.parameters.values()):
            case [parameter] | [inspect.Parameter(name="self"), parameter]:
                annotation = parameter.annotation
            case parameters:
                taken = [each for each in parameters if each.name != "self"]
                message = (
                    f"the tool `{name}` takes {len(taken)} parameters besides "
                    "`self`; a tool takes one pydantic model"
                )
                raise ToolError(message)
        returned = signature.return_annotation
        if not (is_model(annotation) and (is_model(returned) or returned is str)):
            message = (
                f"the tool `{name}` must take one pydantic model and return another, "
                "or `str` for an answer in words"
            )
            raise ToolError(message)
        summary_of(name, description)
        return cls(
            name=name,
            description=description,
            parameter=parameter,
            reads=reads,
            idempotent=idempotent,
        )


class Method[S, I: BaseModel, O: BaseModel | str](property):
    """A tool written as a method: an instance's tool when read through it, itself when read through the class.

    A read-only property of its class, so a pydantic model holds it as it holds
    any property, not as a field; its class lists it among its attributes, so a
    class of tools finds its own (`declared`, `bound`).
    """

    def __init__(self, shape: Shape, function: Callable[[S, I], Awaitable[O]]) -> None:
        """Hold the tool's shape and its function, which takes the instance first."""
        self.shape = shape
        self.function = function
        super().__init__(self.bound)

    def __set_name__(self, owner: type, name: str) -> None:
        """Refuse a name its class gives a field: the field would hide the tool."""
        refuse_taken(owner, name, "tool")

    def bound(self, instance: S) -> Tool[I, O]:
        """Return the tool, its function called with `instance` first."""
        return Tool[I, O](
            name=self.shape.name,
            description=self.shape.description,
            input=self.shape.parameter.annotation,
            function=partial(self.function, instance),
            reads=self.shape.reads,
            idempotent=self.shape.idempotent,
        )

    @overload
    def __get__(self, instance: None, owner: type[S] | None = None) -> Self: ...
    @overload
    def __get__(self, instance: S, owner: type[S] | None = None) -> Tool[I, O]: ...
    def __get__(
        self, instance: S | None, owner: type[S] | None = None
    ) -> Self | Tool[I, O]:
        """Return the tool bound to `instance`, or this method where read through its class."""
        if instance is None:
            return self
        return self.bound(instance)

    def spec(self) -> ToolSpec:
        """Return the tool's name, description, input model's schema and marks, with no instance."""
        return ToolSpec(
            name=self.shape.name,
            description=self.shape.description,
            input_schema=self.shape.parameter.annotation.model_json_schema(),
            reads=self.shape.reads,
            idempotent=self.shape.idempotent,
        )


def refuse_taken(owner: type, name: str, what: str) -> None:
    """Raise `ToolError` where `owner`, or a class it derives from, gives `name` to a field of its model.

    pydantic drops a class's attribute named after a base's field, so a method
    named so would vanish without a word.
    """
    fields = [
        field
        for base in owner.__mro__[1:]
        if issubclass(base, BaseModel)
        for field in base.model_fields
    ]
    if name in fields:
        message = (
            f"`{owner.__name__}`'s {what} `{name}` takes the name of a field of its "
            "model, which would hide it: name it otherwise"
        )
        raise ToolError(message)


def declared(owner: type[BaseModel]) -> dict[str, ToolSpec]:
    """Return each tool written as a method of `owner`, or of a class it derives from, by its attribute's name, in the order declared.

    A method a subclass declares again stands in its base's place.
    """
    return {
        name: value.spec()
        for klass in reversed(owner.__mro__)
        for name, value in vars(klass).items()
        if isinstance(value, Method)
    }


def bound(instance: BaseModel) -> list[AgentTool]:
    """Return each tool written as a method of `instance`'s class, bound to it."""
    return [
        tool
        for name in declared(type(instance))
        if isinstance(tool := getattr(instance, name), AgentTool)
    ]


class Marks(Model):
    """What `@lup_tool(...)` was told of a tool before it's applied to the function: whether it only reads, and whether a call sent again adds nothing."""

    reads: bool = False
    idempotent: bool = False

    @overload
    def __call__[I: BaseModel, O: BaseModel | str](
        self, function: Callable[[I], Awaitable[O]], /
    ) -> Tool[I, O]: ...
    @overload
    def __call__[S, I: BaseModel, O: BaseModel | str](
        self, function: Callable[[S, I], Awaitable[O]], /
    ) -> Method[S, I, O]: ...
    def __call__[S, I: BaseModel, O: BaseModel | str](
        self,
        function: Callable[[I], Awaitable[O]] | Callable[[S, I], Awaitable[O]],
        /,
    ) -> Tool[I, O] | Method[S, I, O]:
        """Return `function` as a tool carrying these marks (`lup_tool`)."""
        return lup_tool(function, reads=self.reads, idempotent=self.idempotent)


@overload
def lup_tool[I: BaseModel, O: BaseModel | str](
    function: Callable[[I], Awaitable[O]],
    /,
    *,
    reads: bool = False,
    idempotent: bool = False,
) -> Tool[I, O]: ...
@overload
def lup_tool[S, I: BaseModel, O: BaseModel | str](
    function: Callable[[S, I], Awaitable[O]],
    /,
    *,
    reads: bool = False,
    idempotent: bool = False,
) -> Method[S, I, O]: ...
@overload
def lup_tool(*, reads: bool = False, idempotent: bool = False) -> Marks: ...
def lup_tool[S, I: BaseModel, O: BaseModel | str](
    function: Callable[..., Awaitable[O]] | None = None,
    /,
    *,
    reads: bool = False,
    idempotent: bool = False,
    # lup: ignore("reportInvalidTypeVarUse", why="the implementation of two overloads: `S` is what the second binds from a method's `self`, which the implementation takes as any callable")
) -> Tool[I, O] | Method[S, I, O] | Marks:
    """Return `function` as a tool, named for it and described by its docstring; given no function, the marks to apply to one.

    The function is async, takes one pydantic model and returns another, or `str`
    for an answer in words. Its docstring's first line, standing alone, is the
    tool's summary, 50 characters at most (`summary_of`). A method, taking `self`
    first, becomes a `Method`, each instance's own tool. `reads` marks a tool
    that only reads, `idempotent` one a call sent again adds nothing to
    (`ToolSpec`); `@lup_tool(reads=True)` marks as `@lup_tool` does.
    """
    if function is None:
        return Marks(reads=reads, idempotent=idempotent)
    shape = Shape.of(function, reads=reads, idempotent=idempotent)
    if "self" in inspect.signature(function).parameters:
        return Method[S, I, O](shape, function)
    return Tool[I, O](
        name=shape.name,
        description=shape.description,
        input=shape.parameter.annotation,
        function=function,
        reads=reads,
        idempotent=idempotent,
    )
