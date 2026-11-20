"""The one interface every runtime lup holds sessions on is behind, so nothing outside `lup.runtimes` names one.

A runtime is four interfaces, each filled by the runtime's own class: its room
(`Rooming`), what a session's room needs to run it, the files lup writes for it,
its variables and its command, held by lup or in a terminal, where it keeps its
login and the history rooms share; its hooks (`Hooks`), read as lup's events and
answered; how a session held over its input and output is spoken to
(`Holder`); and where its newest CLI is fetched from (`Channel`). Each runtime
is an entry of the `Runtimes` selection `Core` holds, so a project drops or
replaces one as it would any entry (`README.md` here).
"""

from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import Literal, override

from lup.declaration.grammar import Named
from lup.sessions.events import Happened
from lup.types import Model, MutableModel


class Bridge(Model):
    """The programs lup runs in a session's room for its runtime, from the machine's own lup: each a command, as the list of its words."""

    hook: list[str]
    """Run at each of the runtime's hooks, its payload on its input, the hook's
    name appended to its words: it prints what the runtime is answered."""
    tools: list[str]
    """Serves lup's tools to the runtime, over MCP's standard input and output."""


class Begin(Model):
    """How a session's conversation is begun on its runtime: started, resumed, or forked from another's."""

    begun: Literal["start", "resume", "fork"]
    session: str
    """lup's id for the session, a UUID, which a runtime naming its sessions up
    front names it by."""
    known_as: str | None = None
    """The runtime's own id for the session resumed, or for the one forked from;
    none for a start."""
    model: str | None = None
    """The model it runs on, as the runtime names one; none for the runtime's own
    choice, or the operator's."""
    effort: str | None = None
    """The effort it runs at, as the runtime names one; none for its own."""


class Placed(Model):
    """Where a session's things are, in its room."""

    worktree: Path
    """The worktree it runs in, which is where it starts."""
    home: Path
    """The room's home, `HOME`."""
    runtime: Path
    """The runtime's own directory, the session's alone, where its settings,
    state and login are."""
    session: Path
    """lup's own files for the session, read-only in the room: its settings,
    its guidance."""


class Placing(Model):
    """A file lup writes for a session, mounted read-only where the runtime reads it in the room: its place among the session's files, and where it lands."""

    name: str
    """Its name among lup's files for the session (`Placed.session`)."""
    at: Path
    """Where it lands in the room."""


class Prepared(Model):
    """What a session's room needs to run its runtime: the files lup writes, where any lands outside them, the variables it runs with, and its command."""

    files: dict[str, str] = {}
    """Each file lup writes among the session's own (`Placed.session`), by its
    name, with its text."""
    homed: dict[str, str] = {}
    """Each file lup writes in the runtime's own directory before it starts
    (`Placed.runtime`), by its path there, with its text: where the runtime
    reads its state, which it writes on."""
    placed: list[Placing] = []
    """Files of the session's that land elsewhere in the room, as a runtime
    reading its requirements from a fixed path needs."""
    env: dict[str, str] = {}
    command: list[str]
    """The runtime's command in the room, its CLI's path first."""


class Stamp(Model):
    """lup's stamp on a call to one of its own tools: the conversation making it, in the field of what the call is given that lup's tool server reads it back from and removes."""

    field: str = "lup_conversation"
    conversation: str
    """The runtime's own id for the subagent making the call."""


class Answer(Model):
    """lup's answer to one of a runtime's hooks, before the runtime spells it."""

    told: str = ""
    """Words the agent is told beside what the hook is about: a prompt, a
    call's result, their session's start."""
    refused: str | None = None
    """For a call about to run, the words it's refused with, which the agent
    reads as its answer; none to let it run."""
    stamp: Stamp | None = None
    """For a call to lup's own tools by a subagent, the conversation making
    it, stamped into what the call is given; none to leave it."""


class Spoken(Model):
    """What a hook answers its runtime: what it prints, and the status it ends with."""

    output: str = ""
    status: int = 0


class Heard(Model):
    """One of a runtime's hooks, as lup reads it: the event, and whether it's a call to lup's own tools, whose input a stamp says the conversation of."""

    event: Happened | None
    """The event, the agent in it the one the runtime says the conversation
    is; none for a hook lup reads nothing of."""
    conversation: str | None = None
    """The runtime's own id for the subagent whose conversation it is; none
    for the session's own."""
    ours: bool = False
    """Whether it's a call to one of lup's own tools, stamped as it starts."""


class Hook(Model):
    """One of a runtime's hooks lup listens at: its name, as the runtime names it, and the calls it's for, where it says."""

    name: str
    matcher: str | None = None


class Holding(MutableModel, ABC):
    """A session held over its runtime's input and output, as the process holding it speaks to it: the lines it writes, and what it reads of the lines the runtime writes.

    Each line is one JSON message, written with its newline by whoever holds it.
    """

    opening: list[str] = []
    """The lines to write as soon as the runtime is connected."""
    known_as: str | None = None
    """The runtime's own id for the session, once it says it."""
    busy: bool = False
    """Whether a turn is under way, as the runtime last said."""
    up: bool = False
    """Whether the session is ready for a turn: the runtime has said its id,
    and, where it needs one, a thread is open."""
    failed: str | None = None
    """Why the runtime refused to open the session, where it did: its own
    words."""

    @abstractmethod
    def turn(self, text: str) -> list[str]:
        """Return the lines starting a turn on `text`, as the operator's words, or adding it to the turn under way."""

    @abstractmethod
    def interrupt(self) -> list[str]:
        """Return the lines ending the turn under way, if one is."""

    @abstractmethod
    def read(self, line: str) -> list[str]:
        """Read one line the runtime wrote, keeping what it says of the session, and return the lines to write in answer, a request of the runtime's answered."""


class Fetched(Model):
    """A CLI fetched from its vendor: its version, the directory holding it, and its program's path there."""

    version: str
    directory: Path
    program: PurePosixPath
    """The program, relative to `directory`."""


class Channel(Model, ABC):
    """Where a runtime's newest CLI is fetched from, each checked against the checksum its vendor publishes."""

    @abstractmethod
    def latest(self) -> str:
        """Return the newest version its vendor publishes."""

    @abstractmethod
    def fetched(self, version: str, into: Path) -> Fetched:
        """Fetch `version` into the directory `into`, which is made, checking it against its vendor's checksum, and say where its program is."""


class Rooming(Model, ABC):
    """What a runtime needs in a session's room: what lup writes and runs there, and what of its own directory is a login or history."""

    @abstractmethod
    def prepared(
        self,
        begin: Begin,
        placed: Placed,
        bridge: Bridge,
        guidance: str,
        *,
        held: bool,
    ) -> Prepared:
        """Return what a session's room needs to run it: begun as `begin` says, its things where `placed` says, lup's programs `bridge`'s, told `guidance` at system level, held by lup over its input and output, or in a terminal."""

    @abstractmethod
    def login(self) -> str:
        """Return the file its sign-in writes, by its name in its own directory, which an account's login is mounted as."""

    @abstractmethod
    def kept(self) -> list[str]:
        """Return what of its own directory is the history every room of a project shares, each by its name there: what resuming or forking a session reads."""


class Hooks(Model, ABC):
    """A runtime's hooks, as lup listens at them, reads them and answers them."""

    @abstractmethod
    def hooks(self) -> list[Hook]:
        """Return the hooks lup listens at, each run with the bridge's hook command."""

    @abstractmethod
    def heard(self, hook: str, payload: bytes, session: str) -> Heard:
        """Read the hook named `hook` of the session lup knows as `session`, its payload `payload`, as lup's event.

        Raise `ValueError` where the payload isn't one of the hook's.
        """

    @abstractmethod
    def answered(self, hook: str, payload: bytes, answer: Answer) -> Spoken:
        """Spell lup's `answer` to the hook named `hook`, its payload `payload`, as the runtime reads one."""


class Holder(Model, ABC):
    """How a runtime's session is held over its input and output."""

    @abstractmethod
    def holding(self, begin: Begin, worktree: Path) -> Holding:
        """Return how a session begun as `begin` says, in `worktree`, is held, its opening lines among it."""


class Runtime(Model):
    """A runtime lup holds sessions on: everything lup needs of it, each part an interface its own classes fill, so nothing outside `lup.runtimes` names one."""

    name: str
    """lup's name for it, as a session, a profile's defaults and its account's
    logins name it."""
    ceiling: int | None = None
    """The most bytes of guidance it takes at a session's start; none where it
    sets no limit lup knows of."""
    rooming: Rooming
    hooks: Hooks
    holder: Holder
    channel: Channel


class Runtimes(Named[Runtime]):
    """The runtimes a project's sessions may run on, each by its name."""

    @override
    def named(self, entry: Runtime) -> str:
        return entry.name
