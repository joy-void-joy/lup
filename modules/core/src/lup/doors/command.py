"""`@lup.command`: whoever runs the command line calls the method, under its module's command.

The fields of the model it takes are its arguments and options, and it returns
the text it prints. A command takes everything it needs as arguments: called
without one it needs, it's refused at once, naming it, rather than waiting on
input that may never come, so an agent or a test running it fails rather than
hangs.
"""

from typing import TYPE_CHECKING, ClassVar, Concatenate

from pydantic import BaseModel

from lup.doors.door import Door, DoorError, Served, Taken, is_model, spelled

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class CommandDoor(Door):
    """A command's door: whoever runs the command line calls the method, the fields of the model it takes its arguments and options, and prints the text it returns.

    `@lup.command` is this door, put on the method it decorates. It has no
    default callers, so each command says who may run it: `by: Operator`, on
    their machine with their authority, `by: Agent`, from an agent's room, or
    both.
    """

    called: ClassVar[str] = "a command"

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a command's: one model in, `str` out."""
        if not is_model(taken.given().annotation):
            message = (
                f"the command `{taken.qualified}` takes {taken.spelled_model()}: a "
                "command takes one pydantic model, whose fields are its arguments "
                "and options"
            )
            raise DoorError(message)
        if taken.returned is not str:
            message = (
                f"the command `{taken.qualified}` returns {spelled(taken.returned)}: "
                "a command returns the text it prints, `str`"
            )
            raise DoorError(message)

    def __call__[S, I: BaseModel, **P](
        self, method: Callable[Concatenate[S, I, P], Awaitable[str]], /
    ) -> Served[S, Concatenate[I, P], Awaitable[str]]:
        """Return `method` behind this door."""
        return Served(method, self)


def command[S, I: BaseModel, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[str]], /
) -> Served[S, Concatenate[I, P], Awaitable[str]]:
    """Make a method a command, under its module's on the command line: the fields of the model it takes are its arguments and options, its docstring its help, and the text it returns what it prints.

    It says who may run it, `by: Operator`, `by: Agent` or `by: Agent |
    Operator`: on the operator's machine a command carries their authority, in
    an agent's room the agent's.
    """
    return CommandDoor()(method)
