"""A session held with no terminal: a runtime a launcher talks to over its room's input and output, the same shape for each runtime.

    piped = await room.hold(arguments, settings)
    session = adapter_held(piped, said=log)
    reading = asyncio.create_task(session.served())
    await session.send("<the operator's words>")
    await session.interrupt()
    status = await ended(piped, timedelta(minutes=2))

`Declaration.held(settings)` compiles a declaration for it as `terminal`
compiles one for a person at a terminal: the same settings, files and mounts,
with a command whose input and output are the launcher's. A held session takes
nothing a tool server pushes and has no messaging socket: whatever starts a turn
of it comes on its input (`send`).

Each runtime's adapter implements it over its own wire, and says where its
runtime differs: whether its process outlives its controller, so that only
stopping its container ends it; whether a terminal attaches to it live, or takes
it over by ending it and resuming; whether an interrupt stops a running command.
A runtime with no held session yet says so where it compiles one.
"""

from abc import ABC, abstractmethod


class HeldSession(ABC):
    """A runtime's session held over its room's input and output."""

    @abstractmethod
    async def send(self, text: str) -> None:
        """Give the session `text` as a user turn: an idle session starts a turn on it, and a busy one reads it in the turn under way, once its running call ends."""

    @abstractmethod
    async def interrupt(self) -> None:
        """End the turn under way at once, a foreground command with it; nothing where none is."""

    @abstractmethod
    async def served(self) -> None:
        """Read what the runtime says until its output ends, as it does when the runtime exits."""
