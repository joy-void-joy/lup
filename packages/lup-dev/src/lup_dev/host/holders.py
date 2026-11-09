"""The launches whose session a launcher holds with no terminal, and the requests the host service makes of each launcher, on the socket beside its lock (`lup_dev.host.held`)."""

from collections.abc import Awaitable, Callable
from typing import Literal

from lup.types import MutableModel
from lup_dev.host.client import requested
from lup_dev.host.protocol import Done, HostError, Register, Request
from lup_dev.layout import Layout


class HeldPrompt(Request, reads=False):
    """On a launcher's socket: give the held session these words as a user turn."""

    kind: Literal["held-prompt"] = "held-prompt"
    text: str


class HeldInterrupt(Request, reads=False):
    """On a launcher's socket: end the turn under way."""

    kind: Literal["held-interrupt"] = "held-interrupt"


class HeldEnd(Request, reads=False):
    """On a launcher's socket: end the session; answered once it has ended."""

    kind: Literal["held-end"] = "held-end"


class Holders(MutableModel, arbitrary_types_allowed=True):
    """The launches the service serves whose session a launcher holds, and how it reaches each: one request per connection on the socket beside its lock."""

    layout: Layout
    prompt: Callable[[str, str, str], str | None] = lambda _, __, ___: None
    """Spells the user turn that starts an idle held session of the runtime
    named on what waits for it: the runtime, the text and a token in, the
    turn's text out, carrying the token whole; none where the runtime has no
    held session (`cli.py`'s adapters)."""
    held: list[str] = []
    """By launch id, as each was served."""
    interrupted: Callable[[str], Awaitable[None]] | None = None
    """What follows an interrupt that went through, by launch id: its session
    taken for idle, since an interrupted turn runs no turn's end, and woken for
    what waits (`Delivery.interrupted`); none does nothing."""

    def opened(self, launch: Register) -> None:
        """Keep `launch` where it's held, once it's served."""
        if launch.held and launch.launch not in self.held:
            self.held = [*self.held, launch.launch]

    def closed(self, launch: str) -> None:
        """Forget `launch`, once the service stops serving it."""
        self.held = [each for each in self.held if each != launch]

    def holds(self, launch: str) -> bool:
        """Say whether `launch`'s session is held by its launcher."""
        return launch in self.held

    async def asked(self, launch: str, request: Request) -> Done:
        """Ask `launch`'s launcher `request`, and return its answer; raise `HostError` where the launch isn't held, its launcher can't be reached, or refuses, saying why."""
        if not self.holds(launch):
            message = f"launch `{launch}` isn't a held session: its terminal is its own"
            raise HostError(message)
        socket = self.layout.launch(launch).held
        try:
            return await requested(socket, request, Done)
        except HostError as failed:
            message = f"launch `{launch}`'s launcher, on {socket}: {failed}"
            raise HostError(message) from failed
        except OSError as unreached:
            message = f"launch `{launch}`'s launcher can't be reached on {socket}: {unreached}"
            raise HostError(message) from unreached
