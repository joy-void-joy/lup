"""A declaration compiled for a terminal, in lup's own terms, which each adapter spells.

`Declaration.terminal(settings)` turns a declaration into what starts its runtime's
CLI for a person at a terminal (`DESIGN.md`, *Calling agents from code*): the command line, the
variables, the files to write before it runs, and what to mount for it. The
settings say what lup adds to the session: the hooks, the tool servers, the
guidance, the session's settings, the paths to trust, and where its messaging
socket goes. A room then runs the result in its container (`lup.rooms`).
"""

import inspect
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Self

from pydantic import AfterValidator, model_validator

from lup.errors import LupError
from lup.events import SessionEvent
from lup.rooms.container import AbsolutePath, Mount
from lup.sessions import bridge
from lup.types import Model


class TerminalError(LupError):
    """A declaration that couldn't be compiled for a terminal."""


class Cli(Model):
    """A runtime's CLI, as a room mounts and runs it: the program, and what ships with it.

    A CLI that is one file is mounted alone. One that runs helpers shipped beside
    it, found by their place next to the program, is mounted with the whole
    directory it ships in, at its path, so it finds them in the room as on the host.

    >>> Cli(program=Path("/opt/cli/bin/agent"), directory=Path("/opt/cli")).mount
    Mount(source=PosixPath('/opt/cli'), target=None, read_only=True, receives=False)
    """

    program: AbsolutePath
    """The binary the terminal runs."""
    directory: AbsolutePath | None = None
    """The directory the program ships in, with the helpers it runs, mounted whole;
    none mounts the program alone."""

    @model_validator(mode="after")
    def program_inside(self) -> Self:
        """Refuse a program outside the directory it's said to ship in, which the room wouldn't hold."""
        if self.directory is not None and not self.program.is_relative_to(
            self.directory
        ):
            message = f"the CLI {self.program} isn't inside {self.directory}"
            raise ValueError(message)
        return self

    @property
    def mount(self) -> Mount:
        """Return what the room mounts for the CLI, read-only: its directory, or the program alone."""
        return Mount(
            source=self.program if self.directory is None else self.directory,
            read_only=True,
        )


def whole_seconds(timeout: timedelta) -> timedelta:
    """Return `timeout`, refusing one that isn't a positive number of whole seconds, which is how hooks and tool servers are timed."""
    if timeout <= timedelta(0) or timeout.microseconds:
        message = f"a timeout is a positive number of whole seconds, not {timeout}"
        raise ValueError(message)
    return timeout


class Hook(Model):
    """A command the runtime runs at an event, with the event's payload on its input."""

    event: type[SessionEvent]
    """The event, one of a session's (`lup.events`), which each adapter spells as
    its runtime's own."""
    matcher: str | None = None
    """Which calls or sources it runs for, as the runtime matches them; none for all."""
    command: list[str]
    """The program and its arguments, quoted for the runtime's shell when compiled."""
    timeout: Annotated[timedelta, AfterValidator(whole_seconds)] | None = None
    """How long the runtime waits for it; none keeps the runtime's own default."""


class ToolServer(Model):
    """An MCP server the session loads, listening on a Unix socket in the room.

    The session reaches it through lup's bridge (`lup.sessions.bridge`), a
    stdio server carrying its standard input and output to the socket across
    the server's restarts, so the server itself runs wherever the socket's other
    end is: on the host, through a directory the room mounts.
    """

    name: str
    """The name the session knows the server by, which its tools' names carry."""
    socket: AbsolutePath
    """The socket the server listens on, at its path in the room."""
    timeout: Annotated[timedelta, AfterValidator(whole_seconds)] | None = None
    """How long the runtime waits on one call, a call held for the operator
    among them; none keeps the runtime's own limit."""
    pushes: bool = False
    """Whether it pushes messages to the session unasked, each starting a turn
    of an idle session, where the runtime takes them; one that doesn't says so
    in its adapter."""


def cache_lifetime(lifetime: timedelta) -> timedelta:
    """Return `lifetime`, refusing any but the two a prompt cache can have: five minutes or an hour."""
    if lifetime not in [timedelta(minutes=5), timedelta(hours=1)]:
        message = f"a prompt cache lives five minutes or an hour, not {lifetime}"
        raise ValueError(message)
    return lifetime


class SessionSettings(Model):
    """The session's settings, in lup's terms (`docs/launch.md`, *The settings compiled for each runtime*).

    Each is none where it isn't given, which leaves it to the runtime: to the
    person's own settings, or the runtime's default. A runtime with no setting
    for one leaves it out, and says so in its adapter.
    """

    subagent_cache: Annotated[timedelta, AfterValidator(cache_lifetime)] | None = None
    """How long the prompt cache of the requests outside the main conversation lives:
    subagents and background work."""
    auto_memory: bool | None = None
    """Whether the runtime keeps and reads its own memory between sessions."""
    idle_compaction: bool | None = None
    """Whether the runtime may compact a long conversation while the session sits
    idle. Compaction when the context fills isn't a session setting: it stays
    the runtime's own."""
    removed_tools: list[str] | None = None
    """Built-in tools removed from the session's context, by the runtime's names
    for them; none removes none."""
    account_connectors: bool | None = None
    """Whether the session fetches the connectors the operator's account brings
    with its login, whose tools reach their mail and files."""


class TerminalSettings(Model):
    """What lup adds to a terminal session of a declaration's runtime."""

    directory: AbsolutePath
    """The launch's own directory, where the compiled files are written; it's
    mounted read-only into the room at its path."""
    cli: Cli | None = None
    """The runtime's CLI, mounted read-only into the room; none for the one its SDK bundles."""
    hooks: list[Hook] = []
    servers: list[ToolServer] = []
    """The MCP servers lup gives the session, each named once."""
    messages: AbsolutePath | None = None
    """Where the session's own messaging socket goes, at its path in the room,
    so a message from outside can reach the session, idle or not; none leaves it
    where the runtime puts it. A runtime with no such socket says so in its
    adapter."""
    guidance: str | None = None
    """Instructions given at system level, beside the runtime's own prompt; none
    gives none. The repository's own instruction files aren't loaded either way."""
    session: SessionSettings = SessionSettings()
    """The session settings imposed: each one given outranks the person's own
    runtime settings."""
    defaults: SessionSettings = SessionSettings()
    """lup's defaults: each one given is passed only where the person's own
    runtime settings, read once at launch, don't set it, so theirs outrank it."""
    trusted: list[AbsolutePath] = []
    """The paths the runtime trusts without asking: the worktree, and a linked
    worktree's main repository, which the runtimes ask about too."""

    @model_validator(mode="after")
    def servers_named_once(self) -> Self:
        """Refuse two tool servers of one name, which the session would know as one."""
        named = Counter(server.name for server in self.servers)
        twice = [name for name, count in named.items() if count > 1]
        if twice:
            message = f"more than one tool server is named {', '.join(twice)}"
            raise ValueError(message)
        return self

    @property
    def bridge(self) -> Path:
        """Where lup's bridge is written, in the launch's directory, for each tool server's stdio entry to run."""
        return self.directory / "mcp-bridge.py"

    def bridged(self, server: ToolServer) -> list[str]:
        """Return the command a runtime runs as `server`'s stdio server: lup's bridge to its socket, on the room's Python, isolated from any project's environment (`-I`).

        >>> settings = TerminalSettings(directory=Path("/launch"))
        >>> settings.bridged(ToolServer(name="lup", socket=Path("/run/lup/mcp.sock")))
        ['python3', '-I', '/launch/mcp-bridge.py', '/run/lup/mcp.sock']
        """
        return ["python3", "-I", str(self.bridge), str(server.socket)]

    def bridges(self) -> dict[Path, str]:
        """Return the bridge's file to write, by its path, where the session has tool servers; nothing otherwise."""
        if not self.servers:
            return {}
        return {self.bridge: inspect.getsource(bridge)}

    def passed(self, theirs: list[str]) -> SessionSettings:
        """Return the session settings a terminal passes, where the person's own set the fields `theirs` names.

        Each field `session` gives is passed; each `defaults` gives, only where
        theirs don't set it; a field neither gives is left to the runtime. Each
        adapter reads which fields theirs set from its runtime's own files.
        Raise `TerminalError` naming a field in `theirs` that isn't a session
        setting.

        >>> settings = TerminalSettings(
        ...     directory=Path("/launch"),
        ...     session=SessionSettings(auto_memory=True),
        ...     defaults=SessionSettings(auto_memory=False, account_connectors=False),
        ... )
        >>> passed = settings.passed(["auto_memory", "account_connectors"])
        >>> passed.auto_memory, passed.account_connectors
        (True, None)
        """
        fields = list(SessionSettings.model_fields)
        unknown = [field for field in theirs if field not in fields]
        if unknown:
            message = (
                f"{', '.join(unknown)} aren't session settings; {', '.join(fields)} are"
            )
            raise TerminalError(message)
        imposed = self.session.model_dump(exclude_none=True)
        defaulted = {
            field: value
            for field, value in self.defaults.model_dump(exclude_none=True).items()
            if field not in theirs
        }
        return SessionSettings.model_validate({**defaulted, **imposed})


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
