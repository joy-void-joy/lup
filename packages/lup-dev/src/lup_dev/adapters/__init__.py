"""Each runtime's hooks in lup's own words: the only code that names a runtime.

Each runtime's module builds its `Adapter`, what lup needs of it: how its hooks
are answered, how the host service reads them, adds to their answers and starts
a turn of an idle session, and what a launch of it runs. The command line lists
them.
"""

from collections.abc import Callable
from datetime import timedelta

from lup.events import SessionEvent
from lup.sessions.declaration import Declaration
from lup.sessions.terminal import Hook
from lup.tools.serving import Notice
from lup.types import JsonObject, Model
from lup_dev.host.courier import Heard, Spawned, Telling
from lup_dev.host.records import Reader, Records
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
    spawned: Callable[[str], Spawned | None]
    """Reads how the subagent one of its hooks fires for was spawned, as the
    runtime recorded it: the payload in; none for the session's own
    conversation, or where nothing's recorded."""
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
    records: Records
    """Where it keeps each session's record on this machine, which a module copies."""
    reader: Reader
    """Reads the copies of its records: which are sessions, and what was said in each."""
