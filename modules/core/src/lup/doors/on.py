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
        answers = self.event.answered and taken.returned in [str, str | None]
        if annotation is not self.event:
            message = (
                f"`{taken.qualified}` runs at `{self.event.__name__}`, and takes "
                f"{taken.spelled_model()}: a method run at an event takes that "
                "event's class"
            )
            raise DoorError(message)
        if taken.returned is not None and not answers:
            message = (
                f"`{taken.qualified}` returns {spelled(taken.returned)}: a method "
                "run at an event returns nothing, or, at one that's answered, words "
                "(`str | None`)"
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

    def __call__[S, E: Event, R: str | None](
        self, method: Callable[[S, E], Awaitable[R]], /
    ) -> Served[S, [E], Awaitable[R]]:
        """Return `method` run at this door's event."""
        return Served(method, self)


def on(event: type[Event]) -> OnDoor:
    """Return the door of a hook, to put on a method lup runs at `event`, handing it the event.

    The method takes the event's class and returns nothing, or, at an event
    that's `answered`, words told beside what it's about; there it may refuse
    it too, raising `RefusedError`. At `Starting` it may go on as long as its
    class runs, ending once lup cancels it at the class's stop.
    """
    return OnDoor(event=event)
