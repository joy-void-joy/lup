"""`@lup.on(Event)`: lup runs the method at an event, handing it the event.

The method takes the event, whose class says which (`lup.doors.events`), and
returns nothing; no party calls it, so it takes no `by`. A class's own start and
stop are the core's events (`Starting`, `Stopping`): what a class keeps running
as long as it runs, it starts at the one and ends at the other.
"""

from typing import TYPE_CHECKING, ClassVar

from lup.doors.door import Door, DoorError, Served, Taken, spelled
from lup.doors.events import Event

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from lup.doors.parties import Party


class OnDoor(Door):
    """A hook's door: lup runs the method at its event, handing it the event.

    `@lup.on(Starting)` is this door, put on the method it decorates.
    """

    called: ClassVar[str] = "run at an event"

    event: type[Event]
    """The event it runs at, by its class."""

    def contract(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a hook's: its event's class in, nothing out."""
        annotation = taken.given().annotation
        if annotation is not self.event:
            message = (
                f"`{taken.qualified}` runs at `{self.event.__name__}`, and takes "
                f"{taken.spelled_model()}: a method run at an event takes that "
                "event's class"
            )
            raise DoorError(message)
        if taken.returned is not None:
            message = (
                f"`{taken.qualified}` returns {spelled(taken.returned)}: a method "
                "run at an event returns nothing"
            )
            raise DoorError(message)

    def checked(self, taken: Taken) -> None:
        """Raise `DoorError` where `taken` isn't a hook's, or takes `by`: nobody calls a hook, lup runs it."""
        self.contract(taken)
        if taken.by is not None:
            message = (
                f"`{taken.qualified}` takes `by`, but nobody calls a method run at "
                "an event: lup runs it, and the event carries its own facts"
            )
            raise DoorError(message)

    def parties(self, taken: Taken) -> list[type[Party]]:
        """Return no party: lup runs a hook, nobody calls it."""
        del taken
        return []

    def __call__[S, E: Event](
        self, method: Callable[[S, E], Awaitable[None]], /
    ) -> Served[S, [E], Awaitable[None]]:
        """Return `method` run at this door's event."""
        return Served(method, self)


def on(event: type[Event]) -> OnDoor:
    """Return the door of a hook, to put on a method lup runs at `event`, handing it the event.

    The method takes the event's class and returns nothing. At `Starting` it
    may go on as long as its class runs, ending once lup cancels it at the
    class's stop.
    """
    return OnDoor(event=event)
