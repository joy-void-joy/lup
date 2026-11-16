"""`@lup.request`: code in a room asks the method, sending the model it takes, whose `kind` routes it.

Code in a room sends a typed request whichever module answers it, so a request
is routed by its `kind` rather than by a module's name, and one kind is one
method's across the project's modules. The method returns the reply, a model.
"""

from typing import TYPE_CHECKING, ClassVar, Concatenate

from pydantic import BaseModel

from lup.doors.door import Door, DoorError, Served, Taken, is_model, spelled
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class Request(Model):
    """What code in a room sends a module's method: its `kind` names it, and routes it to the one method answering it.

    Each kind is a subclass giving `kind` a literal default of its own, so the
    request carries it wherever it's sent:

    >>> from typing import Literal
    >>> class Ping(Request):
    ...     '''Ask whether a module is there.'''
    ...
    ...     kind: Literal["ping"] = "ping"
    >>> Ping.named(), Ping().kind
    ('ping', 'ping')
    """

    kind: str

    @classmethod
    def named(cls) -> str | None:
        """Return the kind its requests carry, its `kind`'s default; none where it gives none."""
        # lup: ignore("dict-literal-key", why="pydantic lists a model's fields in a dict by name, and `kind` is one `Request` itself declares")
        default = cls.model_fields["kind"].default
        return default if isinstance(default, str) else None


class RequestDoor(Door):
    """A request's door: code in a room asks the method, sending the `Request` it takes; the method returns the reply.

    `@lup.request` is this door, put on the method it decorates. It has no
    default callers, so each request says who may send it, `by: Agent` for the
    agent whose room it comes from.
    """

    called: ClassVar[str] = "a request"

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a request's: a `Request` of a kind of its own in, a model out."""
        if not self.kind(taken):
            message = (
                f"the request `{taken.qualified}` takes {taken.spelled_model()}: a "
                "request takes a `Request` giving `kind` a default of its own, "
                "which routes it"
            )
            raise DoorError(message)
        if not taken.answers_model():
            message = (
                f"the request `{taken.qualified}` returns {spelled(taken.returned)}: "
                "a request returns its reply, a pydantic model"
            )
            raise DoorError(message)

    def kind(self, taken: Taken) -> str | None:
        """Return the kind of request a method taking what `taken` says answers: its `Request`'s own; none where it takes no `Request` of a kind of its own."""
        model = taken.given().annotation
        if is_model(model) and issubclass(model, Request):
            return model.named()
        return None

    def __call__[S, I: Request, O: BaseModel, **P](
        self, method: Callable[Concatenate[S, I, P], Awaitable[O]], /
    ) -> Served[S, Concatenate[I, P], Awaitable[O]]:
        """Return `method` behind this door."""
        return Served(method, self)


def request[S, I: Request, O: BaseModel, **P](
    method: Callable[Concatenate[S, I, P], Awaitable[O]], /
) -> Served[S, Concatenate[I, P], Awaitable[O]]:
    """Make a method a request: code in a room sends the `Request` it takes, routed by its `kind`, and it returns the reply.

    It says who may send it, `by: Agent` for the agent whose room it comes from:
    a request has no default callers, so each says whose untrusted code it
    answers.
    """
    return RequestDoor()(method)
