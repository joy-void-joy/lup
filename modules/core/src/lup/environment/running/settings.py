"""What the program a container runs reads from its environment."""

from lup.types import Settings


class Running(Settings):
    """The program's environment: what it's asked to do, where a detached container has no input to read it from."""

    lup_asked: str | None = None
    """What to do, as the JSON message its input would carry; none to read its
    input."""
