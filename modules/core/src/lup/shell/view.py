"""`@lup.view`: the dashboard shows the method's answer, kept live, and its command prints it as text.

A view takes what's viewed, a model, and answers `Blocks`, which the shell lays
out in the one document and which its command prints as text (`Blocks.text`),
so an agent reads what the operator saw. The operator and agents may both read
a view, unless its `by` says otherwise. A view of the worktree it's typed in,
as code rules' table of rules, says `here=True`: `lup` answers it in its own
process, over that worktree's declaration, as it answers a command marked so;
it's the command line's alone, since the dashboard is typed in no worktree.
"""

from typing import TYPE_CHECKING, ClassVar, Concatenate, overload

from pydantic import BaseModel

from lup.doors.door import Door, DoorError, Served, Taken, is_model, spelled
from lup.doors.parties import Agent, Operator, Party
from lup.doors.tool import summary_of
from lup.shell.blocks import Blocks

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class ViewDoor(Door):
    """A view's door: the dashboard shows what the method answers, and its command prints it as text.

    `@lup.view` is this door, put on the method it decorates.
    """

    called: ClassVar[str] = "a view"
    default: ClassVar[list[type[Party]]] = [Operator, Agent]
    here: bool = False
    """Whether it reads the worktree it's typed in: `lup` answers it in its own
    process, over that worktree's declaration, never carrying it to where the
    project runs."""
    longest: int = 60
    """The most characters its summary, its docstring's first line, may take:
    what the command line's help lists it by, beside its name, in 80 columns."""

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a view's: one model in, what's viewed, and `Blocks` out."""
        if not is_model(taken.given().annotation):
            message = (
                f"the view `{taken.qualified}` takes {taken.spelled_model()}: a view "
                "takes one pydantic model, what's viewed"
            )
            raise DoorError(message)
        if taken.returned is not Blocks:
            message = (
                f"the view `{taken.qualified}` returns {spelled(taken.returned)}: a "
                "view returns `Blocks`"
            )
            raise DoorError(message)
        summary_of(taken.qualified, taken.description, self.longest, "view")

    def __call__[S, I: BaseModel, **P](
        self, method: Callable[Concatenate[S, I, P], Awaitable[Blocks]], /
    ) -> Served[S, Concatenate[I, P], Awaitable[Blocks]]:
        """Return `method` behind this door."""
        return Served(method, self)


@overload
def view[S, I: BaseModel, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[Blocks]], /
) -> Served[S, Concatenate[I, P], Awaitable[Blocks]]: ...
@overload
def view(*, here: bool) -> ViewDoor: ...
def view[S, I: BaseModel, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[Blocks]] | None = None,
    /,
    *,
    here: bool = False,
) -> Served[S, Concatenate[I, P], Awaitable[Blocks]] | ViewDoor:
    """Make a method a view: it takes what's viewed, a model, and answers `Blocks`, which the dashboard shows, kept live, and its command prints as text; given `here`, one `lup` answers where it's typed, over that worktree's declaration.

    The operator and agents may both read it, unless its `by` names who may.
    """
    door = ViewDoor(here=here)
    return door if method is None else door(method)
