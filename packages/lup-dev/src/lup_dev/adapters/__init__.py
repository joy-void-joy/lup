"""Each runtime's hooks in lup's own words: the only code that names a runtime.

Each runtime's module builds its `Adapter`, what lup needs of it: how its hooks
are answered, how the host service reads them, adds to their answers and starts
a turn of an idle session, and what a launch of it runs. The command line lists
them.
"""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path, PurePosixPath

from lup.events import SessionEvent
from lup.sessions.declaration import Declaration
from lup.sessions.terminal import Hook
from lup.tools.serving import Notice
from lup.types import JsonObject, Model
from lup_dev.host.courier import Heard, Spawned, Telling
from lup_dev.host.protocol import Register
from lup_dev.host.records import Queues, Reader, Records
from lup_dev.host.written import Checked, Places
from lup_dev.launch.clis import Channel
from lup_dev.policy.checkpoint import Bench
from lup_dev.policy.runtime import Runtime


class Pushing(Model, arbitrary_types_allowed=True):
    """How lup's tool server starts a turn of a runtime's idle session: what it declares, and the notice it pushes."""

    capabilities: dict[str, JsonObject]
    """What the server declares as experimental, for the runtime to take what it pushes."""
    notice: Callable[[str, str], Notice]
    """The notice for a message: its text and a token in, the notice out, its
    turn's prompt carrying the token whole."""


class Adapter(Model, arbitrary_types_allowed=True):
    """A runtime lup knows: how its hooks are answered, and what a launch of it needs."""

    runtime: Runtime
    hook: Callable[[str, Bench], str]
    """Answers one of its hooks: a payload in, what the hook prints out."""
    unanswered: Callable[[str, str], str]
    """Answers a hook lup's judge couldn't: the payload and why in, what the hook
    prints out."""
    heard: Callable[[str], Heard]
    """Reads one of its hooks as the host service does: who's speaking, about
    which call, and whether a launch's judge reads it. Raises `ValueError` where
    the payload isn't one of its hooks."""
    told: Callable[[str, str, Telling], str | None]
    """Adds to a hook's answer: the payload, the answer (the judge's, or none)
    and what to add in, what the hook prints out instead; none where nothing is
    added, so the answer goes out as it is."""
    spawned: Callable[[str, Register], Spawned | None]
    """Reads how the subagent one of its hooks fires for was spawned, as the
    runtime recorded it: the payload in, and the launch whose room ran the
    hook, in whose own runtime directory alone a record the payload names is
    read, in the home it registered (`lup_dev.host.homes.translated`); none
    for the session's own conversation, or where nothing's recorded."""
    woken: Callable[[str, str], str] | None
    """Starts a turn of an idle session: its id and what to tell it in, the line
    written to its messaging socket out; none where the runtime has no way, a gap
    its module declares."""
    pushing: Pushing | None
    """Starts a turn of an idle session through lup's tool server, on its own
    connection; none where the runtime takes nothing a server pushes, a gap its
    module declares."""
    hooks: Callable[[Callable[[type[SessionEvent]], list[str]], timedelta], list[Hook]]
    """The hooks a launched session runs at the events the host service hears,
    each running the command given for its event and waiting up to a timeout."""
    channel: Channel
    """Its release channel, which a launch fetches the latest CLI from."""
    agent: Callable[[], Declaration]
    """The declaration a launched session runs."""
    login: Callable[[Path], Path]
    """Where it keeps its login in a home of its own at the directory given, an
    account's among them: the file its sign-in writes."""
    records: Records
    """Where it keeps each session's record on this machine, which a module copies."""
    directory: Path
    """The operator's own directory for it, where it keeps their history and
    login, and the records `records` finds; every room on it mounted it
    read-write before rooms had homes of their own."""
    written: Callable[[Places], Checked]
    """Checks what a host session of it acts on in `directory`, which rooms
    could have written: the directories rooms write in, a line out for each
    thing there that runs, loads or acts without asking on the host, what of it
    looks planted, and what to do, and how to replace its login apart
    (`lup_dev.host.written`)."""
    resumed: Callable[[list[str]], str | None]
    """Says which session a launch's arguments for its CLI resume, by its id;
    none where they resume none, or open its picker."""
    recorded: Callable[[PurePosixPath], str | None]
    """Says whose own record is at a place in one of its homes: the session's
    id, by the name it files the record under there, as `records` finds it;
    none for any other place. What lup moves into a home on the host keeps
    that home for each session it moved (`lup_dev.migration`)."""
    reader: Reader
    """Reads the copies of its records: which are sessions, and what was said in each."""
    queues: Queues | None
    """Reads what it holds queued for each conversation of a running session,
    which ends a held call of lup's; none where its records don't say, a gap its
    module declares."""
