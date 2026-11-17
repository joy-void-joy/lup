"""lup's events, which a method behind `@lup.on` runs at: each a class, carrying its own facts.

The core's are a class's own start and stop: `Starting`, as the class is made
where it runs, and `Stopping`, before it stops there. A session's events come
with the piece that starts sessions (#5).
"""

from lup.types import Model


class Event(Model):
    """Something lup runs a module's methods at: each event a class of its own, which a method behind `@lup.on` takes."""


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
