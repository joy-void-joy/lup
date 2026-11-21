"""What a session's room sends the machine for its runtime: a hook, as its runtime ran it."""

from lup.types import Model


class Hooked(Model):
    """One of the runtime's hooks, as it ran in the room: its name and its payload, whole, which the machine reads with the session's runtime."""

    hook: str
    payload: str
