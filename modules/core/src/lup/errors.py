"""The root of every error lup raises, so a caller can catch them all at once."""


class LupError(Exception):
    """Something lup couldn't do; each module's errors descend from it.

    What it's about, by name, rides beside its message (`about`), so a caller
    reads the method or the modules it names without parsing its words:

    >>> LupError("two modules share `shout`", about=["echo", "other"]).about
    ['echo', 'other']
    """

    def __init__(self, message: str, *, about: list[str] | None = None) -> None:
        """Say what went wrong, and name what it's about."""
        super().__init__(message)
        self.about: list[str] = [] if about is None else about
        """What it's about, by name: the method a door can't take, by its name
        in its class (`EchoServing.shout`), or the modules a declaration can't
        resolve with; none where it names nothing."""
