"""Reaching the host service: finding it on its control socket, or starting it; and from a room, on its launch's request socket.

`docs/launch.md`, *On the host: the service*: one service per user, started by the
first launch that finds none answering, and running until it's stopped, as the
engine is found or started on demand. A client that finds no service starts
`lup-dev host` as a detached process, and waits through `lup_dev.clock` until its
control socket answers, so tests drive the time.

A program in a room reaches the service through `RoomClient`, one typed request
on `/run/lup/request.sock`, which the service answers with the launch it knows by
the socket (`docs/host-tools.md`, *The room's requests*).

A request whose reply comes only once something happens, such as an approval's
answer, holds its connection open (`HostClient.held`, `Outstanding`), with no
time limit: it's waited on for as long as the operator takes.
"""

import select
import socket
import sys
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, override

from pydantic import TypeAdapter

from lup.programs import detached
from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.host.protocol import (
    Done,
    HostError,
    Listed,
    ListLaunches,
    Refused,
    Register,
    Registered,
    Reply,
    Request,
    Stop,
    Unregister,
)
from lup_dev.layout import ROOM_SOCKETS, HostLayout, LaunchSockets

if TYPE_CHECKING:
    from collections.abc import Callable


def read_reply[R: Reply](answer: bytes, reply: type[R]) -> R:
    """Read the service's answer as `reply`; a refusal raises `HostError` with the service's reason."""
    replied = TypeAdapter[R | Refused](reply | Refused).validate_json(answer)
    if isinstance(replied, Refused):
        raise HostError(replied.error)
    return replied


def sent(path: Path, request: Request, timeout: timedelta | None) -> socket.socket:
    """Connect to the host service's socket at `path` and send one request, its end marked; return the connection, its reply to read.

    Each read waits `timeout` at most; none waits for as long as it takes.
    Finding no service to ask on `path` raises `HostError`.
    """
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(None if timeout is None else timeout.total_seconds())
        connection.connect(str(path))
        connection.sendall(request.model_dump_json().encode())
        connection.shutdown(socket.SHUT_WR)
    except (FileNotFoundError, ConnectionRefusedError) as gone:
        connection.close()
        message = f"no host service answers on {path}"
        raise HostError(message) from gone
    except OSError:
        connection.close()
        raise
    return connection


def asked[R: Reply](
    path: Path, request: Request, reply: type[R], timeout: timedelta
) -> R:
    """Send one request on the host service's socket at `path`, and read its reply as `reply`.

    A refusal raises `HostError` with the service's reason, as does finding no
    service to ask on `path`, or a connection closed without a reply.
    """
    with (
        sent(path, request, timeout) as connection,
        connection.makefile("rb") as stream,
    ):
        answer = stream.read()
    if not answer:
        message = "the host service closed the connection without answering"
        raise HostError(message)
    return read_reply(answer, reply)


class Outstanding(Model, arbitrary_types_allowed=True):
    """A request whose reply comes later, once what it waits for happens: its connection held open.

    The connection is readable once the reply is there, or once the service
    closed it without one, as a service stopping does; so a terminal can wait on
    it beside its own input (`select`).
    """

    connection: socket.socket

    def fileno(self) -> int:
        """Return the connection's descriptor, which `select` watches."""
        return self.connection.fileno()

    def ready(self) -> bool:
        """Say whether the reply is there to read, or the connection closed without one, without waiting."""
        readable, _, _ = select.select([self.connection], [], [], 0)
        return bool(readable)

    def reply[R: Reply](self, reply: type[R]) -> R | None:
        """Read the reply as `reply`, waiting for it; none where the service closed the connection without one.

        A refusal raises `HostError` with the service's reason.
        """
        with self.connection.makefile("rb") as stream:
            answer = stream.read()
        return read_reply(answer, reply) if answer else None

    def close(self) -> None:
        """Close the connection; a reply that comes later goes unread."""
        self.connection.close()


class RoomClient(Model):
    """Reaches the host service from a room's program, on the launch's `request.sock`.

    The service knows the launch by the socket, so a request names nothing of it;
    and the room can't start a service, so finding none is said.
    """

    socket: Path = LaunchSockets(directory=ROOM_SOCKETS).request
    """The launch's request socket, where the room mounts it."""
    timeout: timedelta = timedelta(minutes=1)
    """How long to wait for one reply."""

    def ask[R: Reply](self, request: Request, reply: type[R]) -> R:
        """Send one request, and read its reply as `reply`.

        A refusal raises `HostError` with the service's reason, as does finding no
        service to ask: outside a room, or with the host service stopped.
        """
        return asked(self.socket, request, reply, self.timeout)


class Starter(ABC):
    """Starts the host service as a process of its own."""

    @abstractmethod
    def start(self, log: Path) -> None:
        """Start the service, detached, appending what it prints to `log`."""


class Detached(Model, Starter):
    """Starts `lup-dev host` in a session of its own, which outlives whoever starts it."""

    command: list[str] = [sys.executable, "-m", "lup_dev.cli", "host"]
    """The command running the service: the running `lup_dev`'s, by default."""

    @override
    def start(self, log: Path) -> None:
        program, *arguments = self.command
        detached(program, *arguments, log=log)


class HostClient(Model, arbitrary_types_allowed=True):
    """Reaches the host service on its control socket, starting it where none answers."""

    layout: HostLayout
    clock: Clock
    starter: Starter
    patience: timedelta = timedelta(seconds=10)
    """How long a service just started, or just stopped, may take to show it."""
    poll: timedelta = timedelta(milliseconds=50)
    """How often to look meanwhile."""
    timeout: timedelta = timedelta(minutes=1)
    """How long to wait for one reply."""

    def answers(self) -> bool:
        """Say whether a service answers on the control socket.

        A socket file with no service behind it, left by one that died, refuses.
        """
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(str(self.layout.control))
            except FileNotFoundError, ConnectionRefusedError:
                return False
        return True

    def ensure(self) -> None:
        """Find the service, or start it and wait until it answers."""
        if self.answers():
            return
        self.starter.start(self.layout.log)
        self.wait(
            self.answers,
            f"the host service didn't answer on {self.layout.control} within "
            f"{self.patience}; what it printed is in {self.layout.log}",
        )

    def wait(self, done: Callable[[], bool], failure: str) -> None:
        """Wait through the clock until `done()`, raising `failure` after `patience`."""
        began = self.clock.now()
        while not done():
            if self.clock.now() - began >= self.patience:
                raise HostError(failure)
            self.clock.sleep(self.poll.total_seconds())

    def ask[R: Reply](self, request: Request, reply: type[R]) -> R:
        """Send one request, and read its reply as `reply`.

        A refusal raises `HostError` with the service's reason, as does finding no
        service to ask.
        """
        return asked(self.layout.control, request, reply, self.timeout)

    def held(self, request: Request) -> Outstanding:
        """Send one request whose reply comes once what it waits for happens, starting the service where none runs.

        Its reply waits on the connection returned, for as long as it takes.
        """
        self.ensure()
        return Outstanding(connection=sent(self.layout.control, request, None))

    def rejoined(self, request: Request) -> Outstanding:
        """Send a held request again, once the service that held it stopped: to the one that runs next.

        It waits `patience` for one to answer first, as a service restarted by
        another's hand does, an approval restarting it on the copy just
        installed, so as not to start one of its own meanwhile; then it starts
        one where none answers.
        """
        began = self.clock.now()
        while not self.answers() and self.clock.now() - began < self.patience:
            self.clock.sleep(self.poll.total_seconds())
        return self.held(request)

    def register(self, launch: Register) -> Path:
        """Have the service serve a launch, starting it if none runs.

        Return the launch's socket directory, which its room mounts.
        """
        self.ensure()
        return self.ask(launch, Registered).directory

    def launches(self) -> list[Register]:
        """List the launches the service serves, starting it if none runs.

        A service started serves every launch recorded, so none recorded is missed.
        """
        self.ensure()
        return self.ask(ListLaunches(), Listed).launches

    def unregister(self, launch: str) -> None:
        """End a launch: its sockets closed, its directory removed.

        A service is started if none runs, since the launch stays recorded until
        one ends it.
        """
        self.ensure()
        self.ask(Unregister(launch=launch), Done)

    def stop(self) -> bool:
        """Stop the service, and wait until its socket is gone; say whether one ran."""
        if not self.answers():
            return False
        self.ask(Stop(), Done)
        self.wait(
            lambda: not self.answers(),
            f"the host service said it stops, but still answers on "
            f"{self.layout.control} after {self.patience}",
        )
        return True
