"""`@lup.action(verb=…, says=…)`: the operator's key runs the method, on what a view offers it.

What a key means is said once, on the action: the verb whose key reaches it,
and what it does, as the line of keys says it. The method takes the model what
it's run on gives it, or a list of that model, every mark of one send at once,
so two boxes ticked are one change rather than two. It answers words, a model,
or nothing where what it changed shows in the views it touches, and refuses by
raising `RefusedError`, saying why.
"""

from typing import TYPE_CHECKING, ClassVar, Concatenate, overload

from pydantic import BaseModel

from lup.doors.door import Answer, Door, DoorError, Served, Taken, is_model, spelled
from lup.doors.parties import Operator, Party

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class ActionDoor(Door):
    """An action's door: the operator's key runs the method on what a view offers it, and says what it does.

    `@lup.action(verb="done", says="merge it")` is this door, put on the method
    it decorates.
    """

    called: ClassVar[str] = "an action"
    default: ClassVar[list[type[Party]]] = [Operator]

    verb: str
    """The verb whose key reaches it, by its name."""
    says: str
    """What it does, as the line of keys says it after its key: `merge it onto
    dev`."""

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't an action's: one model or a list of it in, a model, `str` or nothing out."""
        if not is_model(taken.one()):
            message = (
                f"the action `{taken.qualified}` takes {taken.spelled_model()}: an "
                "action takes one pydantic model, what it's run on, or a list of "
                "it, every mark of a send"
            )
            raise DoorError(message)
        if not (
            taken.returned is None or taken.returned is str or taken.answers_model()
        ):
            message = (
                f"the action `{taken.qualified}` returns {spelled(taken.returned)}: "
                "an action returns a pydantic model, `str` for an answer in words, "
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


def action(*, verb: str, says: str) -> ActionDoor:
    """Return the door of an action, to put on a method: `verb`'s key runs it on what a view offers it, and `says` is what the line of keys says it does.

    It takes the model what it's run on gives it, or, as `list[Model]`, every
    mark of one send at once; its docstring is its command's help. It answers
    words, a model, or nothing where what it changed shows in the views it
    touches, and raises `RefusedError` to refuse, saying why.
    """
    return ActionDoor(verb=verb, says=says)
