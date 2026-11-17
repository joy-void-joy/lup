"""`@lup.command`, or `@lup.command(verb=…, says=…)`: what someone does, which the command line runs by name and, given a verb, the dashboard offers under its key.

One door for what's done, wherever it's offered: the command line runs every
command of a module by its name, the fields of the model it takes its arguments
and options, and a command given a `verb` is also what that key does on what a
view offers it, `says` being what the line of keys says it does. Who may run it
is its `by`, checked before every run, wherever it's run from: a command for the
operator alone refuses an agent running it from their room. A command takes
everything it needs as arguments: run without one it needs, it's refused at
once, naming it, rather than waiting on input that may never come, so an agent
or a test running it fails rather than hangs.

A command the dashboard offers may take a list of its model, every mark of one
send at once, so two boxes ticked are one change rather than two; run from the
command line, it's given one. It answers a model, words, or nothing where what
it changed shows in the views it touches, and refuses by raising
`RefusedError`, saying why.
"""

from typing import TYPE_CHECKING, ClassVar, Concatenate, Self, overload

from pydantic import BaseModel, model_validator

from lup.doors.door import Answer, Door, DoorError, Served, Taken, is_model, spelled

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class CommandDoor(Door):
    """A command's door: the command line runs the method by name, its model's fields its arguments and options; given a verb, the dashboard offers it under that key on what a view gives it.

    `@lup.command` and `@lup.command(verb="done", says="merge it")` are this
    door, put on the method they decorate. It has no default callers, so each
    command says who may run it: `by: Operator`, `by: Agent`, or both.
    """

    called: ClassVar[str] = "a command"
    verb: str | None = None
    """The verb whose key reaches it in the dashboard, by its name; none for a
    command the command line alone runs."""
    says: str | None = None
    """What it does, as the dashboard's line of keys says it after its key: `merge
    it onto dev`; given with `verb`, and only with it."""

    @model_validator(mode="after")
    def keyed(self) -> Self:
        """Refuse a verb without what it says, or what it says without a verb."""
        if (self.verb is None) != (self.says is None):
            message = (
                "a command the dashboard offers names its `verb` and what it "
                "`says`, both, and one the command line alone runs names neither"
            )
            raise DoorError(message)
        return self

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a command's: one model in, or a list of it where the dashboard offers it, and a model, `str` or nothing out."""
        if not is_model(taken.one()):
            message = (
                f"the command `{taken.qualified}` takes {taken.spelled_model()}: a "
                "command takes one pydantic model, whose fields are its arguments "
                "and options"
            )
            raise DoorError(message)
        if taken.gathers() and self.verb is None:
            message = (
                f"the command `{taken.qualified}` takes a list, every mark of one "
                "send, which only the dashboard gives: a command taking one names "
                "the `verb` whose key reaches it"
            )
            raise DoorError(message)
        if not (
            taken.returned is None or taken.returned is str or taken.answers_model()
        ):
            message = (
                f"the command `{taken.qualified}` returns {spelled(taken.returned)}: "
                "a command returns a pydantic model, `str` for an answer in words, "
                "or nothing"
            )
            raise DoorError(message)

    @overload
    def __call__[S, I: BaseModel, O: Answer, **P](
        self, method: Callable[Concatenate[S, I, P], Awaitable[O]], /
    ) -> Served[S, Concatenate[I, P], Awaitable[O]]: ...
    @overload
    def __call__[S, I: BaseModel, O: Answer, **P](
        self, method: Callable[Concatenate[S, list[I], P], Awaitable[O]], /
    ) -> Served[S, Concatenate[list[I], P], Awaitable[O]]: ...
    def __call__[S, O: Answer, **P](
        self, method: Callable[Concatenate[S, P], Awaitable[O]], /
    ) -> Served[S, P, Awaitable[O]]:
        """Return `method` behind this door."""
        return Served(method, self)


@overload
def command[S, I: BaseModel, O: Answer, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[O]], /
) -> Served[S, Concatenate[I, P], Awaitable[O]]: ...
@overload
def command(*, verb: str, says: str) -> CommandDoor: ...
def command[S, I: BaseModel, O: Answer, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[O]] | None = None,
    /,
    *,
    verb: str | None = None,
    says: str | None = None,
) -> Served[S, Concatenate[I, P], Awaitable[O]] | CommandDoor:
    """Make a method a command, run by its name under its module's on the command line; given a verb and what it says, the door that also puts it under that key in the dashboard.

    The fields of the model it takes are its arguments and options, its
    docstring its help. It says who may run it, `by: Operator`, `by: Agent` or
    both: on the operator's machine a command carries their authority, in an
    agent's room the agent's. It answers a model, words, or nothing, and raises
    `RefusedError` to refuse, saying why.
    """
    door = CommandDoor(verb=verb, says=says)
    return door if method is None else door(method)
