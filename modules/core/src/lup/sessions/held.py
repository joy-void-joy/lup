"""What crosses between the machine and the process holding one session, its holder: how a holder is started, what it's told to do, and where its session stands.

A holder is a process of its own on the operator's machine, one per session,
started by the machine and outliving the machine's restarts, so replacing the
machine's code cuts no turn (`README.md` here, *Holding*). It listens on two
sockets: one in the session's room's own directory, which the room's first
program connects to and runs the runtime on, so nothing else in the room can
type a turn as the operator; and one only the machine reaches, in its own
directory in memory, where it's told what to do, one message a connection, and
answers where its session stands.
"""

from pathlib import Path
from typing import Literal

from lup.runtimes.runtime import Begin
from lup.types import Model


class Holds(Model):
    """How a holder is started: the session it holds, on which runtime, begun how and where, and its two sockets."""

    session: str
    """lup's id for the session."""
    runtime: str
    """The runtime, by lup's name for it."""
    begin: Begin
    worktree: Path
    """The worktree the session runs in, as its room mounts it."""
    room: Path
    """The socket the room's first program connects to, in the room's own
    directory of sockets."""
    control: Path
    """The socket the machine tells it what to do on, in a directory no room
    mounts."""


class Order(Model):
    """What the machine tells a holder to do: start a turn on its words, interrupt the turn under way, end the session, or only say where it stands."""

    order: Literal["turn", "interrupt", "end", "standing"]
    text: str = ""
    """The words a turn starts on, or joins the turn under way with."""


class Standing(Model):
    """Where a held session stands, as its holder says it."""

    connected: bool = False
    """Whether the room has connected, its runtime running."""
    up: bool = False
    """Whether the runtime is ready for a turn."""
    busy: bool = False
    """Whether a turn is under way."""
    known_as: str | None = None
    """The runtime's own id for the session, once it's said."""
    failed: str | None = None
    """Why the runtime refused to open the session, where it did."""
    ending: bool = False
    """Whether it's been told to end, and is waiting for its runtime to."""
