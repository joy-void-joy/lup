"""`@lup.service`: code calls the method as a plain call, wherever its class runs.

A service takes one model and returns another, words, or nothing, as a tool
does; what differs is who calls it. An agent calls a tool through MCP; code calls
a service, read through its class, as it would any async function:

    pushed = await GitAccess.push(Pushing(branch="dev"))

The call is carried to wherever the class runs, its own container where it
holds something, or the project's, and answered there; a call it refuses raises
`RefusedError` at the caller, as a plain call's failure would. Read through an
instance, the method is that instance's, called as any, as the class's own code
calls it. Carrying is the environment's: lup sets what carries a call
(`CARRYING`) wherever it runs a module's code, and outside lup a service can't be
called (`UncarriedError`).

Who calls is, by default, a project's own code (`Codebase`), which whoever carries
the call vouches for from where it came; a room's program calls for its agent,
so a service it may call says `by: Agent | Codebase`.

The machine's own parts serve every project, so a call of theirs to a part that
runs one per project names which project's (`within`):

    with lup.within("harmon"):
        await Remotes.pushed(updates)

Named anywhere but where the machine's parts run, the call is refused: a
project's code calls its own project's parts alone.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Concatenate, overload

from pydantic import BaseModel, JsonValue, TypeAdapter

from lup.doors.door import Answer, Door, DoorError, Method, Taken, is_model, spelled
from lup.doors.parties import Codebase, Party
from lup.errors import LupError
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator


class UncarriedError(LupError):
    """A service was called where nothing carries its call: outside lup, where no class of it runs."""


class Carrier(ABC):
    """What carries a service's call to where its class runs, and brings back its answer: the environment's, wherever lup runs a module's code."""

    @abstractmethod
    async def carried(self, method: Method, value: BaseModel) -> Answer | JsonValue:
        """Carry a call of `method` on `value` to where its class runs, and return what it answered, as its method returned it or as its JSON.

        Raise `RefusedError` where it's refused there: a caller it isn't for,
        or the method refusing.
        """


CARRYING = ContextVar[Carrier | None]("carrying", default=None)
"""What carries a service's call from here: set by lup wherever it runs a
module's code, none outside lup."""

WITHIN = ContextVar[str | None]("within", default=None)
"""The project whose part a service call made here goes to, as `within`
names it; none where the call names none."""


@contextmanager
def within(project: str) -> Generator[None]:
    """Send each service call made inside to the part of the project named `project` (its repository, as lup names it), where the part runs one per project: how the machine's own parts, which serve every project, call one project's part.

    Honoured only where the machine's parts run: a call made inside it
    anywhere else is refused.
    """
    named = WITHIN.set(project)
    try:
        yield
    finally:
        WITHIN.reset(named)


class ServiceDoor(Door):
    """A service's door: code calls the method as a plain call, wherever its class runs.

    `@lup.service` is this door, put on the method it decorates.
    """

    called: ClassVar[str] = "a service"
    default: ClassVar[list[type[Party]]] = [Codebase]
    named_across: ClassVar[bool] = True

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a service's: one model in, a model, `str` or nothing out."""
        if not is_model(taken.given().annotation):
            message = (
                f"the service `{taken.qualified}` takes {taken.spelled_model()}: a "
                "service takes one pydantic model"
            )
            raise DoorError(message)
        if not (
            taken.returned is None or taken.returned is str or taken.answers_model()
        ):
            message = (
                f"the service `{taken.qualified}` returns {spelled(taken.returned)}: "
                "a service returns a pydantic model, `str`, or nothing"
            )
            raise DoorError(message)

    def __call__[S, I: BaseModel, O: Answer, **P](
        self, method: Callable[Concatenate[S, I, P], Awaitable[O]], /
    ) -> Service[S, I, O, P]:
        """Return `method` behind this door."""
        return Service(method, self)


class Reach[I: BaseModel, O](Model, arbitrary_types_allowed=True):
    """A service read through its class: called as a plain async function, its call carried to where its class runs."""

    method: Method
    """The service, as its class declares it."""

    async def __call__(self, value: I) -> O:
        """Call the service on `value`, wherever its class runs, and return what it answered.

        Raise `UncarriedError` where nothing carries the call, and
        `RefusedError` where it's refused.
        """
        carrier = CARRYING.get()
        if carrier is None:
            name = self.method.taken.qualified
            message = (
                f"`{name}` is a service, called where lup runs a module's code, "
                "which carries the call to where its class runs; nothing here does"
            )
            raise UncarriedError(message, about=[name])
        answered = await carrier.carried(self.method, value)
        returned = self.method.taken.returned
        return TypeAdapter[O](returned).validate_python(answered)


class Service[S, I: BaseModel, O: Answer, **P](Method):
    """A service, typed as written: read through its class, a plain call carried to where the class runs (`Reach`); read through an instance, that instance's method."""

    def __init__(
        self, function: Callable[Concatenate[S, I, P], Awaitable[O]], door: ServiceDoor
    ) -> None:
        """Hold the function as written, behind `door`."""
        self.written = function
        super().__init__(function, door)

    @overload
    def __get__(self, instance: None, owner: type | None = None) -> Reach[I, O]: ...
    @overload
    def __get__(
        self, instance: S, owner: type | None = None
    ) -> Callable[Concatenate[I, P], Awaitable[O]]: ...
    def __get__(
        self, instance: S | None, owner: type | None = None
    ) -> Reach[I, O] | Callable[Concatenate[I, P], Awaitable[O]]:
        """Return the service read through its class, carried; or the method of `instance`."""
        if instance is None:
            return Reach[I, O](method=self)
        return partial(self.written, instance)


service = ServiceDoor()
"""The door of a service, to put on a method code calls as a plain call,
wherever its class runs. It takes one model, then `by` where it needs who
calls; by default a project's own code may."""
