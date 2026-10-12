"""A declaration compiled for a terminal, in lup's own terms, which each adapter spells.

`Declaration.terminal(settings)` turns a declaration into what starts its runtime's
CLI for a person at a terminal (`DESIGN.md`, *The library*): the command line, the
variables, the files to write before it runs, and what to mount for it. The
settings say what lup adds to the session: the hooks, the guidance, the session's
settings and the paths to trust. A room then runs the result in its container
(`lup.rooms`).
"""

from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator

from lup.errors import LupError
from lup.rooms.container import AbsolutePath, Mount
from lup.types import Model


class TerminalError(LupError):
    """A declaration that couldn't be compiled for a terminal."""


type Event = Literal[
    "session-started",
    "call-started",
    "call-finished",
    "turn-ended",
    "conversation-ended",
]
"""When a hook runs, in lup's own words, which each adapter spells as its runtime's events.

A session started, resumed or cleared; a tool call about to run; a tool call
finished, whether it succeeded or failed; the session's turn ending; a subagent's
conversation ending.
"""


def whole_seconds(timeout: timedelta) -> timedelta:
    """Return `timeout`, refusing one that isn't a positive number of whole seconds, which is how hooks are timed."""
    if timeout <= timedelta(0) or timeout.microseconds:
        message = (
            f"a hook's timeout is a positive number of whole seconds, not {timeout}"
        )
        raise ValueError(message)
    return timeout


class Hook(Model):
    """A command the runtime runs at an event, with the event's payload on its input."""

    event: Event
    matcher: str | None = None
    """Which calls or sources it runs for, as the runtime matches them; none for all."""
    command: list[str]
    """The program and its arguments, quoted for the runtime's shell when compiled."""
    timeout: Annotated[timedelta, AfterValidator(whole_seconds)] | None = None
    """How long the runtime waits for it; none keeps the runtime's own default."""


def cache_lifetime(lifetime: timedelta) -> timedelta:
    """Return `lifetime`, refusing any but the two a prompt cache can have: five minutes or an hour."""
    if lifetime not in [timedelta(minutes=5), timedelta(hours=1)]:
        message = f"a prompt cache lives five minutes or an hour, not {lifetime}"
        raise ValueError(message)
    return lifetime


class SessionSettings(Model):
    """The session's settings, in lup's terms (`DESIGN.md`, *Sessions*).

    A runtime with no setting for one leaves it out, and says so in its adapter.
    """

    subagent_cache: Annotated[timedelta, AfterValidator(cache_lifetime)] | None = None
    """How long the prompt cache of the requests outside the main conversation lives:
    subagents and background work. None keeps the runtime's own."""
    auto_memory: bool | None = None
    """Whether the runtime keeps and reads its own memory between sessions; none
    keeps the runtime's own setting."""
    removed_tools: list[str] = []
    """Built-in tools removed from the session's context, by the runtime's names for them."""


class TerminalSettings(Model):
    """What lup adds to a terminal session of a declaration's runtime."""

    directory: AbsolutePath
    """The launch's own directory, where the compiled files are written; it's
    mounted read-only into the room at its path."""
    cli: AbsolutePath | None = None
    """The runtime's CLI, mounted read-only into the room; none for the one its SDK bundles."""
    hooks: list[Hook] = []
    guidance: str | None = None
    """Instructions given at system level, beside the runtime's own prompt; none
    gives none. The repository's own instruction files aren't loaded either way."""
    session: SessionSettings = SessionSettings()
    trusted: list[AbsolutePath] = []
    """The paths the runtime trusts without asking: the worktree, and a linked
    worktree's main repository, which the runtimes ask about too."""


class Terminal(Model):
    """A declaration compiled for a terminal: how to start its runtime's CLI.

    The files are written before the command runs; the mounts are what the CLI
    needs in the room, beside the room's own.
    """

    command: list[str]
    """The CLI and its arguments; a launch's own arguments go after them."""
    env: dict[str, str] = {}
    files: dict[Path, str] = {}
    """Each file's path on the host, and its text."""
    mounts: list[Mount] = []
