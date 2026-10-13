"""Reaching the host service: finding it on its control socket, or starting it.

`docs/launch.md`, *On the host: the service*: one service per user, started by the
first launch that finds none answering, and running until it's stopped, as the
engine is found or started on demand. A client that finds no service starts
`lup-dev host` as a detached process, and waits through `lup_dev.clock` until its
control socket answers, so tests drive the time.
"""

import socket
import sys
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import TYPE_CHECKING, override

import sh
from pydantic import TypeAdapter

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
from lup_dev.layout import HostLayout

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


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
        log.parent.mkdir(parents=True, exist_ok=True)
        program, *arguments = self.command
        with log.open("ab") as appended:
            sh.Command(program)(
                *arguments,
                _bg=True,
                _bg_exc=False,
                _new_session=True,
                _out=appended,
                _err=appended,
            )


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
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout.total_seconds())
                connection.connect(str(self.layout.control))
                connection.sendall(request.model_dump_json().encode())
                connection.shutdown(socket.SHUT_WR)
                with connection.makefile("rb") as stream:
                    answer = stream.read()
        except (FileNotFoundError, ConnectionRefusedError) as gone:
            message = f"no host service answers on {self.layout.control}"
            raise HostError(message) from gone
        if not answer:
            message = "the host service closed the connection without answering"
            raise HostError(message)
        replied = TypeAdapter[R | Refused](reply | Refused).validate_json(answer)
        if isinstance(replied, Refused):
            raise HostError(replied.error)
        return replied

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
