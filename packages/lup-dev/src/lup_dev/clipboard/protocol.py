"""The clipboard's requests from a room, and their handlers on the host.

`docs/launch.md`, *The clipboard*. A room has no display, so its programs
can't reach the operator's clipboard; the room's `wl-paste` and `wl-copy`
(`clipboard/shim.py`) send these on the launch's `request.sock` instead, and the
host answers them with the operator's own desktop (`clipboard/desktop.py`):
what types the clipboard offers, what it holds as one of them, and text to put
on it. Each is answered for any launch: lending a room the clipboard is the
operator's choice, made once for every room.
"""

import base64
from typing import Literal, override

from lup.types import Model
from lup_dev.clipboard.desktop import Clipboard
from lup_dev.host.protocol import Done, Register, Reply, Request
from lup_dev.host.rooms import RoomHandler, RoomRoute


class ListTypes(Request):
    """List the types the clipboard offers, as MIME types (`image/png`, `text/plain`)."""

    kind: Literal["clipboard-types"] = "clipboard-types"
    primary: bool = False
    """The primary selection, the text last selected, rather than the clipboard."""


class ReadClipboard(Request):
    """Read what the clipboard holds, as one of its types; as text where none is named."""

    kind: Literal["clipboard-read"] = "clipboard-read"
    type: str | None = None
    primary: bool = False


class WriteClipboard(Request):
    """Put text on the clipboard."""

    kind: Literal["clipboard-write"] = "clipboard-write"
    text: str
    primary: bool = False


class Types(Reply):
    """The types the clipboard offers."""

    kind: Literal["clipboard-types-listed"] = "clipboard-types-listed"
    types: list[str]


class Held(Reply):
    """What the clipboard holds, as the type asked: its bytes in base64, since JSON carries no bytes."""

    kind: Literal["clipboard-held"] = "clipboard-held"
    data: str

    @classmethod
    def of(cls, data: bytes) -> Held:
        """Carry `data`.

        >>> Held.of(b"hi").data
        'aGk='
        """
        return cls(data=base64.b64encode(data).decode())


class Listing(Model, RoomHandler[ListTypes], arbitrary_types_allowed=True):
    """Answers `ListTypes` with the operator's clipboard."""

    clipboard: Clipboard

    @override
    def request(self) -> type[ListTypes]:
        return ListTypes

    @override
    async def answer(self, request: ListTypes, launch: Register) -> Reply:
        return Types(types=await self.clipboard.types(primary=request.primary))


class Reading(Model, RoomHandler[ReadClipboard], arbitrary_types_allowed=True):
    """Answers `ReadClipboard` with the operator's clipboard."""

    clipboard: Clipboard

    @override
    def request(self) -> type[ReadClipboard]:
        return ReadClipboard

    @override
    async def answer(self, request: ReadClipboard, launch: Register) -> Reply:
        held = await self.clipboard.read(request.type, primary=request.primary)
        return Held.of(held)


class Writing(Model, RoomHandler[WriteClipboard], arbitrary_types_allowed=True):
    """Answers `WriteClipboard` with the operator's clipboard."""

    clipboard: Clipboard

    @override
    def request(self) -> type[WriteClipboard]:
        return WriteClipboard

    @override
    async def answer(self, request: WriteClipboard, launch: Register) -> Reply:
        await self.clipboard.write(request.text, primary=request.primary)
        return Done()


def routes(clipboard: Clipboard) -> list[RoomRoute]:
    """Return the clipboard's routes on each launch's `request.sock`: its types listed, read and written."""
    return [
        RoomRoute.to(Listing(clipboard=clipboard)),
        RoomRoute.to(Reading(clipboard=clipboard)),
        RoomRoute.to(Writing(clipboard=clipboard)),
    ]
