"""`@lup.tool`: an agent calls the method, through MCP, its arguments the model it takes.

A tool takes one model and returns another, or `str` for an answer meant to be
read rather than parsed. Its name is its method's, and its description its
docstring, which opens with its summary (`summary_of`). Its marks say whether a
call to it may be sent again: `reads` where it only reads, changing nothing,
and `idempotent` where a call sent again with the same arguments adds nothing
to what the first did. They're MCP's `readOnlyHint` and `idempotentHint`.
"""

import pydoc
from typing import TYPE_CHECKING, ClassVar, Concatenate, Self, overload

from pydantic import BaseModel, model_validator

from lup.doors.door import Door, DoorError, Served, Taken, is_model, spelled
from lup.doors.parties import Agent, Party
from lup.types import JsonObject, Model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def summary_of(name: str, description: str, longest: int = 50) -> str:
    """Return the summary of the tool `name`: its description's first line, standing alone, `longest` characters at most.

    A session that finds tools by searching for them lists each by its name and
    summary, as a git log lists commits by their subject line. Raise `DoorError`
    naming the tool where the description opens with no line standing alone
    (one running onto the next without a blank line between), or where that line
    is longer.

    >>> summary_of("weather", "Look up today's weather.")
    "Look up today's weather."
    """
    line, _ = pydoc.splitdoc(description)
    if not line:
        message = (
            f"the tool `{name}` has no summary: its docstring opens with one line "
            f"saying what it does, {longest} characters at most, then a blank line "
            "before the rest"
        )
        raise DoorError(message)
    if len(line) > longest:
        message = (
            f"the tool `{name}`'s summary, its docstring's first line, is "
            f"{len(line)} characters, past {longest}: {line}"
        )
        raise DoorError(message)
    return line


class ToolSpec(Model):
    """What a session tells the model about a tool: its name, its description, the schema of its arguments, and its marks."""

    name: str
    description: str
    """What the model reads about the tool, its summary line first."""
    input_schema: JsonObject
    """The JSON Schema of the model it takes."""
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


class ToolDoor(Door):
    """A tool's door: an agent calls the method, its arguments the model it takes; its marks say whether a call may be sent again.

    `@lup.tool(reads=True)` is this door, put on the method it decorates.
    """

    called: ClassVar[str] = "a tool"
    default: ClassVar[list[type[Party]]] = [Agent]

    reads: bool = False
    """Whether the tool only reads, changing nothing: MCP's `readOnlyHint`."""
    idempotent: bool = False
    """Whether a call sent again with the same arguments adds nothing to what
    the first did: MCP's `idempotentHint`."""

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a tool's: one model in, a model or `str` out, and a docstring opening with its summary."""
        if not is_model(taken.model.annotation):
            message = (
                f"the tool `{taken.qualified}` takes {taken.spelled_model()}: a tool "
                "takes one pydantic model, its arguments"
            )
            raise DoorError(message)
        if not (taken.answers_model() or taken.returned is str):
            message = (
                f"the tool `{taken.qualified}` returns {spelled(taken.returned)}: a "
                "tool returns a pydantic model, or `str` for an answer in words"
            )
            raise DoorError(message)
        summary_of(taken.qualified, taken.description)

    def spec(self, taken: Taken) -> ToolSpec:
        """Return what a session tells the model about the tool taking what `taken` says."""
        model = taken.model.annotation
        return ToolSpec(
            name=taken.name,
            description=taken.description,
            input_schema=model.model_json_schema(),
            reads=self.reads,
            idempotent=self.idempotent,
        )

    def __call__[S, I: BaseModel, O: BaseModel | str, **P](
        self, method: Callable[Concatenate[S, I, P], Awaitable[O]], /
    ) -> Served[S, Concatenate[I, P], Awaitable[O]]:
        """Return `method` behind this door."""
        return Served(method, self)


@overload
def tool[S, I: BaseModel, O: BaseModel | str, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[O]], /
) -> Served[S, Concatenate[I, P], Awaitable[O]]: ...
@overload
def tool(*, reads: bool = False, idempotent: bool = False) -> ToolDoor: ...
def tool[S, I: BaseModel, O: BaseModel | str, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[O]] | None = None,
    /,
    *,
    reads: bool = False,
    idempotent: bool = False,
) -> Served[S, Concatenate[I, P], Awaitable[O]] | ToolDoor:
    """Make a method a tool, named for it and described by its docstring; given no method, the door, marked, to put on one.

    The method is async, takes one pydantic model and returns another, or `str`
    for an answer in words; it takes `by: Agent` after its model where it needs
    the agent calling. Its docstring's first line, standing alone, is the
    tool's summary, 50 characters at most (`summary_of`). `reads` marks a tool
    that only reads, `idempotent` one a call sent again adds nothing to
    (`ToolDoor`).
    """
    door = ToolDoor(reads=reads, idempotent=idempotent)
    return door if method is None else door(method)
