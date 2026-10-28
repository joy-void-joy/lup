"""A declaration compiled for a terminal, in lup's own terms, which each adapter spells.

`Declaration.terminal(settings)` turns a declaration into what starts its runtime's
CLI for a person at a terminal (`DESIGN.md`, *Calling agents from code*): the command line, the
variables, the files to write before it runs, and what to mount for it. The
settings say what lup adds to the session: the hooks, the tool servers, the
guidance, the session's settings, the paths to trust, and where its messaging
socket goes. A room then runs the result in its container (`lup.rooms`).
"""

import inspect
import json
import os
import shutil
import stat
import tomllib
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Self

import tomlkit
from pydantic import AfterValidator, JsonValue, TypeAdapter, model_validator
from tomlkit.items import InlineTable, Table

from lup.errors import LupError
from lup.events import SessionEvent
from lup.rooms.container import AbsolutePath, Mount
from lup.rooms.homes import landed, landings
from lup.sessions import bridge
from lup.types import JsonObject, Model

if TYPE_CHECKING:
    from tomlkit import TOMLDocument


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


class RuntimeHome(Model):
    """Where the runtime of a terminal session keeps its directory, in place of the operator's own (`docs/launch.md`, *A home of the rooms' own*).

    Its directory is the launch's own, made fresh and gone with it: the
    configuration copied in from the layers below, the settings, the state, and
    whatever else the runtime writes there, so nothing a room leaves in it
    reaches another room. Only what its adapter names as history (the
    conversations' records, the prompts' history) is shared, each item a link
    from the directory into `shared`, so a conversation resumes in any room
    given that home. It logs in with `login`, an account's file.
    """

    directory: AbsolutePath
    """The launch's own directory for the runtime, mounted read-write at its
    path, which the runtime's variable names. It must sit under no directory
    a room writes, and be made fresh for the launch."""
    shared: AbsolutePath
    """The history the rooms given it share, mounted read-write at its path.
    It must sit under no directory a room writes: a mount point can't be moved
    from inside a room, but a directory above one can, with a link left in its
    place for the host to follow as it mounts the home."""
    login: AbsolutePath
    """The account's login, the file the runtime's sign-in writes, mounted
    read-write alone where the runtime reads it in `directory`, so a sign-in
    in one room is every room's on the account. It must be there, a file: an
    empty one is no login, which the runtime's sign-in fills. The same rule
    holds for it as for `shared`."""
    operators: bool = True
    """Whether the operator's own configuration is the lowest layer, what
    credentials and commands it holds left out."""
    layer: AbsolutePath | None = None
    """A layer of configuration over the operator's, laid out as the runtime's
    own directory: a profile's. None for none, as is a directory that isn't
    there."""


class TerminalSettings(Model):
    """What lup adds to a terminal session of a declaration's runtime."""

    directory: AbsolutePath
    """The launch's own directory, where the compiled files are written; it's
    mounted read-only into the room at its path."""
    home: RuntimeHome | None = None
    """The home of the rooms' own the runtime keeps its history, state,
    configuration and login in; none gives it the room's own home, its state
    gone with the launch, with nothing of the operator's."""
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


class Copy(Model):
    """Configuration a launch copies into its own directory before the command runs, for the room to read there.

    A link is copied as the link, never followed on the host: a room that
    once wrote where it's copied from could have aimed one at the operator's
    keys, and in the room it reaches only what the room has at its path.
    What isn't a file, a directory or a link is left out, a pipe among it,
    which a read would wait on.
    """

    source: AbsolutePath
    """A file, or a directory copied whole; nothing is copied where it isn't
    there, or is a link."""
    destination: AbsolutePath
    leaving: list[str] = []
    """Names directly inside a directory left out of its copy."""

    def made(self) -> None:
        """Copy the source to the destination, over what an earlier copy put there, links as links.

        Nothing in the destination is written through: where an earlier
        layer's copy left a link, or an entry of another kind, where this one
        puts something, it's removed first, since that link came from a
        directory a room may once have written.
        """
        if not self.source.is_symlink():
            copied(self.source, self.destination, self.leaving)


def copied(source: Path, destination: Path, leaving: list[str]) -> None:
    """Copy what's at `source` to `destination`, links as links, what isn't a file, a directory or a link left out, as are `leaving`'s names directly inside a directory; nothing where nothing is there."""
    try:
        seen = source.lstat()
    except FileNotFoundError:
        return
    if not (
        stat.S_ISDIR(seen.st_mode)
        or stat.S_ISREG(seen.st_mode)
        or stat.S_ISLNK(seen.st_mode)
    ):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    there = destination.is_symlink() or destination.exists()
    keeps = there and not destination.is_symlink() and destination.is_dir()
    if there and not (keeps and stat.S_ISDIR(seen.st_mode)):
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    if stat.S_ISLNK(seen.st_mode):
        destination.symlink_to(source.readlink())
        return
    if stat.S_ISREG(seen.st_mode):
        shutil.copy2(source, destination, follow_symlinks=False)
        return
    destination.mkdir(exist_ok=True)
    for each in sorted(source.iterdir()):
        if each.name not in leaving:
            copied(each, destination / each.name, [])


type Syntax = Literal["json", "toml"]
"""How a runtime writes its settings file."""


class Preference(Model):
    """One preference a runtime saves in its settings file, by the keys leading to it, a table's before its own."""

    keys: list[str]

    @property
    def name(self) -> str:
        """Its keys, dotted, as the runtime's docs name it.

        >>> Preference(keys=["tui", "theme"]).name
        'tui.theme'
        """
        return ".".join(self.keys)

    def held(self, table: JsonObject) -> JsonValue:
        """Return its value in `table`; none where it isn't there.

        >>> Preference(keys=["tui", "theme"]).held({"tui": {"theme": "dark"}})
        'dark'
        """
        current: JsonValue = table
        for key in self.keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current


class Setting(Model):
    """A preference with the value it's set to."""

    preference: Preference
    value: JsonValue


class Preferences(Model):
    """What a runtime saves as it runs that a launch carries back at its end: each preference of an allowlist that changed, into a layer of the person's own over the operator's (`carried`), never into the operator's own configuration."""

    saved: AbsolutePath
    """The launch's own settings file, which the runtime writes as it runs."""
    into: AbsolutePath
    """Where they're carried: a layer's file over the operator's, a profile's."""
    syntax: Syntax
    written: list[Setting]
    """Each preference of the allowlist, with its value as the launch wrote
    it, none where it left it unset."""
    largest: int = 4096
    """The most bytes a value carried may take as JSON: the room wrote it, and
    every later room on the layer reads it."""

    def carried(self) -> list[str]:
        """Carry each preference the runtime saved that differs from what the launch wrote into `into`, keeping the rest of that file, and say each carried, or why none was.

        `saved` is read without following a link; where it isn't there, as
        where the launch ended before the runtime started, nothing is carried
        or said. A value past `largest` is left, and said.
        """
        try:
            final = parsed(read(self.saved), self.syntax)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as failed:
            return [f"No preference was carried back from {self.saved}: {failed}"]
        changed = [
            Setting(preference=each.preference, value=value)
            for each in self.written
            if (value := each.preference.held(final)) is not None
            and value != each.value
        ]
        large = [each for each in changed if len(json.dumps(each.value)) > self.largest]
        kept = [each for each in changed if each not in large]
        said = [
            f"Left `{each.preference.name}` as it was: what the session saved there "
            f"is more than {self.largest:,} bytes."
            for each in large
        ]
        if not kept:
            return said
        self.into.parent.mkdir(parents=True, exist_ok=True)
        before = self.into.read_text() if self.into.is_file() else ""
        self.into.write_text(updated(before, self.syntax, kept))
        return [
            *said,
            *(
                f"Kept `{each.preference.name}` = {json.dumps(each.value)} in "
                f"{self.into}, as the session saved it."
                for each in kept
            ),
        ]


def read(path: Path) -> str:
    """Read `path`'s text, never through a link."""
    handle = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(handle, encoding="utf-8") as opened:
        return opened.read()


def parsed(text: str, syntax: Syntax) -> JsonObject:
    """Read a settings file's text as its syntax writes it, an empty file as empty. Raise `ValueError` where it doesn't parse into a table."""
    if not text.strip():
        return {}
    match syntax:
        case "json":
            loaded = TypeAdapter[JsonValue](JsonValue).validate_json(text)
        case "toml":
            loaded = TypeAdapter[JsonValue](JsonValue).validate_python(
                tomllib.loads(text)
            )
    match loaded:
        case dict():
            return loaded
        case _:
            message = "it holds no table"
            raise ValueError(message)


def placed(table: JsonObject, keys: list[str], value: JsonValue) -> JsonObject:
    """Return `table` with `value` set at the end of `keys`, each table on the way made where it isn't one.

    >>> placed({"tui": {"vim": True}}, ["tui", "theme"], "dark")
    {'tui': {'vim': True, 'theme': 'dark'}}
    """
    first, *rest = keys
    if not rest:
        return {**table, first: value}
    inner = table.get(first)
    below: JsonObject = inner if isinstance(inner, dict) else {}
    return {**table, first: placed(below, rest, value)}


def updated(text: str, syntax: Syntax, settings: list[Setting]) -> str:
    """Return a settings file's `text` with each of `settings` set, the rest of it kept as written, a TOML file's comments among it.

    >>> theme = Preference(keys=["tui", "theme"])
    >>> print(updated("", "toml", [Setting(preference=theme, value="light")]), end="")
    [tui]
    theme = "light"
    """
    match syntax:
        case "json":
            table = parsed(text, syntax)
            for each in settings:
                table = placed(table, each.preference.keys, each.value)
            return json.dumps(table, indent=2) + "\n"
        case "toml":
            document = tomlkit.parse(text)
            for each in settings:
                *tables, last = each.preference.keys
                holding: TOMLDocument | Table | InlineTable = document
                for key in tables:
                    if key not in holding:
                        holding[key] = tomlkit.table()
                    inner = holding[key]
                    if not isinstance(inner, Table | InlineTable):
                        inner = tomlkit.table()
                        holding[key] = inner
                    holding = inner
                holding[last] = each.value
            return tomlkit.dumps(document)


type Why = Literal["credential", "command", "unread"]
"""Why something of the configuration copied in was left out: it would hand
the room's code a credential, it would run a command in the room, or it
couldn't be read as configuration, a link lup doesn't follow among it."""


class Left(Model):
    """Something of the configuration copied into a room that was left out, said with where it was, and why."""

    said: str
    why: Why


class Shared(Model):
    """The history a runtime's directory links into: where it is, and each item there, made where it isn't, with whether it's a directory."""

    home: AbsolutePath
    items: dict[Path, bool] = {}


class Terminal(Model):
    """A declaration compiled for a terminal: how to start its runtime's CLI.

    Before the command runs, the runtime's own directory (`home`) is made, the
    files written, the directories made, the copies copied and the links made,
    what each mount inside `home` lands on made there, and each item of the
    history it links into made where it isn't (`prepare`); the mounts are what
    the CLI needs in the room, beside the room's own.
    """

    command: list[str]
    """The CLI and its arguments; a launch's own arguments go after them."""
    env: dict[str, str] = {}
    files: dict[Path, str] = {}
    """Each file's path on the host, and its text."""
    directories: list[Path] = []
    """Each directory made empty."""
    copies: list[Copy] = []
    """Each copied, in order, a later one over an earlier at the same place."""
    links: dict[Path, Path] = {}
    """Each link made, by its place, to what it names."""
    mounts: list[Mount] = []
    home: AbsolutePath | None = None
    """The runtime's own directory for the launch, made fresh: what each mount
    inside it lands on is made there; none where the runtime has none."""
    shared: Shared | None = None
    """The history the runtime's directory links into, which rooms write: each
    item is made there, never through a link (`lup.rooms.homes`); none where
    nothing is shared."""
    left_out: list[Left] = []
    """What of the configuration copied in was left out, and why, for the
    launch to say."""
    preferences: Preferences | None = None
    """What the runtime saves as it runs that the launch carries back at its
    end; none where nothing is."""

    def prepare(self) -> None:
        """Make what the command needs before it runs: the runtime's directory and what's in it, and the history it links into."""
        if self.home is not None:
            self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        for path, text in self.files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        for directory in self.directories:
            directory.mkdir(parents=True, exist_ok=True)
        for copy in self.copies:
            copy.made()
        for link, target in self.links.items():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.unlink(missing_ok=True)
            link.symlink_to(target)
        if self.home is not None:
            landed(self.home, landings(self.home, list(self.mounts)))
        if self.shared is not None:
            self.shared.home.mkdir(mode=0o700, parents=True, exist_ok=True)
            landed(self.shared.home, self.shared.items)
