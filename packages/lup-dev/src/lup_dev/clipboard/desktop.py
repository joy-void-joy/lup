"""The operator's clipboard on the host, through their desktop's own programs.

`docs/host-tools.md`, *The clipboard*. The host service runs in the operator's
graphical session, the environment of the launch that started it, so it reaches
the clipboard as any of their programs does: `wl-paste` and `wl-copy` under
Wayland, `xclip` under X. A room reaches it only through the service, which
answers three requests and nothing else (`clipboard/protocol.py`), each bounded:
a clipboard holding more than `limit` bytes is refused rather than read whole,
and a program that doesn't answer within `timeout` is stopped.
"""

import asyncio
import shlex
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, override

from lup.types import Model
from lup_dev.host.protocol import HostError

if TYPE_CHECKING:
    from lup_dev.settings import LupDevSettings


class Clipboard(ABC):
    """The operator's clipboard, as the host reaches it."""

    @abstractmethod
    async def types(self, *, primary: bool) -> list[str]:
        """Return the types it offers; the primary selection's where `primary`.

        Raise `HostError` where it can't be read, saying why.
        """

    @abstractmethod
    async def read(self, type_: str | None, *, primary: bool) -> bytes:
        """Return what it holds as `type_`, as text where none is named.

        Raise `HostError` where it can't be read, saying why.
        """

    @abstractmethod
    async def write(self, text: str, *, primary: bool) -> None:
        """Put `text` on it.

        Raise `HostError` where it can't be written, saying why.
        """


type Session = Literal["wayland", "x11"]
"""The kind of graphical session the host service runs in."""


class Desktop(Model, Clipboard):
    """The clipboard of the graphical session the host service runs in, through its own programs; none where it runs outside one."""

    session: Session | None
    limit: int = 32 * 1024 * 1024
    """The most a read returns: a screenshot passes, a video doesn't."""
    timeout: timedelta = timedelta(seconds=5)

    @classmethod
    def of(cls, settings: LupDevSettings) -> Desktop:
        """Return the clipboard of the session `settings` name: Wayland's where `WAYLAND_DISPLAY` is set, X's where `DISPLAY` is, none otherwise."""
        if settings.wayland_display:
            return cls(session="wayland")
        if settings.display:
            return cls(session="x11")
        return cls(session=None)

    @override
    async def types(self, *, primary: bool) -> list[str]:
        match self.session:
            case "wayland":
                command = ["wl-paste", "--list-types", *self.wayland(primary=primary)]
            case "x11":
                command = ["xclip", *self.x11(primary=primary), "-t", "TARGETS", "-o"]
            case None:
                raise self.away()
        listed = (await self.ran(command)).decode(errors="replace")
        return [line for line in listed.splitlines() if line]

    @override
    async def read(self, type_: str | None, *, primary: bool) -> bytes:
        typed = [] if type_ is None else ["--type", type_]
        match self.session:
            case "wayland":
                command = [
                    "wl-paste",
                    "--no-newline",
                    *typed,
                    *self.wayland(primary=primary),
                ]
            case "x11":
                targeted = [] if type_ is None else ["-t", type_]
                command = ["xclip", *self.x11(primary=primary), *targeted, "-o"]
            case None:
                raise self.away()
        return await self.ran(command)

    @override
    async def write(self, text: str, *, primary: bool) -> None:
        match self.session:
            case "wayland":
                command = ["wl-copy", *self.wayland(primary=primary)]
            case "x11":
                command = ["xclip", *self.x11(primary=primary)]
            case None:
                raise self.away()
        await self.given(command, text.encode())

    def wayland(self, *, primary: bool) -> list[str]:
        """Return `wl-paste`'s and `wl-copy`'s flag for the primary selection, where it's asked."""
        return ["--primary"] if primary else []

    def x11(self, *, primary: bool) -> list[str]:
        """Return `xclip`'s selection: the primary one, or the clipboard."""
        return ["-selection", "primary" if primary else "clipboard"]

    def away(self) -> HostError:
        """Say why there's no clipboard: the service runs outside a graphical session."""
        return HostError(
            "the host service reaches no clipboard: it runs outside a graphical "
            "session (no `WAYLAND_DISPLAY` or `DISPLAY`), as when started from "
            "somewhere other than your desktop's terminal; stop it "
            "(`lup-dev host stop`) and the next launch starts it in yours"
        )

    async def ran(self, command: list[str]) -> bytes:
        """Run `command` and return what it prints, `limit` bytes at most, within `timeout`.

        Raise `HostError` where it doesn't run, fails, prints more, or doesn't
        finish in time, saying which.
        """
        said = shlex.join(command)
        try:
            # lup: ignore("subprocess", why="the host service runs the desktop's clipboard programs on its event loop, its output read bounded, which `programs` reads whole")
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as missing:
            message = f"`{said}` doesn't run on the host: {missing}"
            raise HostError(message) from missing
        if process.stdout is None or process.stderr is None:
            message = f"`{said}` started without its output"
            raise HostError(message)
        try:
            async with asyncio.timeout(self.timeout.total_seconds()):
                printed = bytearray()
                while chunk := await process.stdout.read(64 * 1024):
                    printed += chunk
                    if len(printed) > self.limit:
                        process.kill()
                        await process.wait()
                        message = (
                            f"the clipboard holds more than {self.limit} bytes, "
                            "which a room isn't given"
                        )
                        raise HostError(message)
                error = await process.stderr.read()
                status = await process.wait()
        except TimeoutError as slow:
            process.kill()
            await process.wait()
            message = f"`{said}` didn't answer within {self.timeout}"
            raise HostError(message) from slow
        if status != 0:
            reason = error.decode(errors="replace").strip() or f"status {status}"
            message = f"`{said}` failed: {reason}"
            raise HostError(message)
        return bytes(printed)

    async def given(self, command: list[str], data: bytes) -> None:
        """Run `command` with `data` on its input, within `timeout`.

        Its output goes nowhere: `xclip` and `wl-copy` leave a process behind to
        serve the clipboard, which would hold a pipe open. Raise `HostError`
        where it doesn't run, fails, or doesn't finish in time.
        """
        said = shlex.join(command)
        try:
            # lup: ignore("subprocess", why="the host service runs the desktop's clipboard programs on its event loop, their output going nowhere since each leaves a process serving the clipboard")
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as missing:
            message = f"`{said}` doesn't run on the host: {missing}"
            raise HostError(message) from missing
        try:
            async with asyncio.timeout(self.timeout.total_seconds()):
                await process.communicate(data)
        except TimeoutError as slow:
            process.kill()
            await process.wait()
            message = f"`{said}` didn't answer within {self.timeout}"
            raise HostError(message) from slow
        if process.returncode != 0:
            message = f"`{said}` failed with status {process.returncode}"
            raise HostError(message)
