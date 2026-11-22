"""lup's events, which a method behind `@lup.on` runs at: each a class, carrying its own facts.

The core's are a class's own start and stop: `Starting`, as the class is made
where it runs, and `Stopping`, before it stops there. A session's events come
with the piece that starts sessions (#5).
"""

from typing import ClassVar

from lup.types import Model


class Event(Model):
    """Something lup runs a module's methods at: each event a class of its own, which a method behind `@lup.on` takes.

    Where the event says it's `answered`, a method run at it may answer words,
    told to whoever the event is about beside it, or refuse what it's about,
    raising `RefusedError` with the words they read instead.
    """

    answered: ClassVar[bool] = False
    """Whether a method run at it may answer words, or refuse it."""
    fired: ClassVar[bool] = False
    """Whether a part's own code may tell it to its project's parts
    (`lup.heeded`): a project's own event, never one only lup tells, as a
    session's is."""


class Heeded(Model):
    """What the methods run at an event answered: each one's words, in order, and the refusal, where one refused."""

    told: list[str] = []
    refused: str | None = None


class Starting(Event):
    """A part made where it runs, as its container starts: what it keeps running, a bot's connection say, it starts here.

    A method run at it may go on as long as the class runs: lup stops it,
    cancelling it, once every method run at `Stopping` has ended.
    """


class Stopping(Event):
    """A part about to stop where it runs, as its container stops or its code is replaced: what it started, it ends here.

    Each method run at it ends before lup cancels what the class started at
    `Starting`.
    """
