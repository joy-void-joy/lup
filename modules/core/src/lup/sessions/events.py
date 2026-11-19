"""A session's events, which a module's methods hear through `@lup.on`: each a class, carrying the agent whose conversation it's of and its own facts.

Each runtime's hooks are read as them in the runtime's adapter (`lup.runtimes`),
so nothing hearing one names a runtime. The agent is the one the session's room
vouches for (`lup.Agent.of`): an event a room sends naming another is refused.
Each is named on the wire by its `kind`, which a hook's call carries it with.
"""

from typing import Annotated, Literal
lazy from pathlib import Path

from pydantic import Field, JsonValue

from lup.doors.events import Event
lazy from lup.doors.parties import Agent

type Begun = Literal["start", "resume", "fork", "clear", "compact"]
"""How a session's conversation began, as its runtime says it: started afresh,
resumed, forked from another's, cleared, or begun again on a summary of itself."""


class SessionEvent(Event):
    """Something that happened in a session: the agent whose conversation it's of, and its own facts."""

    agent: Agent


class SessionStarted(SessionEvent):
    """A session's conversation began: started, resumed, forked, cleared or compacted."""

    kind: Literal["session-started"] = "session-started"
    begun: Begun
    runtime: str
    """The runtime it runs on, by lup's name for it (`lup.runtimes`)."""
    known_as: str
    """The runtime's own id for the session, which its record is filed under."""
    worktree: Path
    """The worktree it runs in, as its room mounts it."""


class TurnStarted(SessionEvent):
    """A conversation's turn started on a prompt, or a prompt reached a turn under way."""

    kind: Literal["turn-started"] = "turn-started"
    prompt: str


class CallStarting(SessionEvent):
    """A tool call is about to run: a method hearing it may refuse it, raising `RefusedError` with the words the agent reads as its answer."""

    kind: Literal["call-starting"] = "call-starting"
    call: str
    """The runtime's id for the call, the same at its start and its end."""
    tool: str
    """The tool called, by the runtime's name for it."""
    given: JsonValue = None
    """What the tool was given, as the runtime sends it."""
    writes: list[Path] = []
    """The files a file tool writes, read from what it was given: none for any
    other tool, a command among them, which can write anything."""


class CallFinished(SessionEvent):
    """A tool call finished: a method hearing it may answer words, told to the agent beside the call's result."""

    kind: Literal["call-finished"] = "call-finished"
    call: str
    tool: str
    writes: list[Path] = []
    failed: bool = False
    """Whether the call failed, rather than ran: where a runtime says so."""


class TurnEnded(SessionEvent):
    """A conversation ended their turn: their last words, or the error that ended it."""

    kind: Literal["turn-ended"] = "turn-ended"
    said: str = ""
    failed: bool = False
    """Whether the turn ended on an error from the model's API, `said` its text."""


class ConversationStarted(SessionEvent):
    """A subagent's conversation started in the session."""

    kind: Literal["conversation-started"] = "conversation-started"
    called: str = ""
    """The runtime's kind for the subagent, where it says one."""


class ConversationEnded(SessionEvent):
    """A subagent's conversation ended their turn, with their last words; the session's own goes on."""

    kind: Literal["conversation-ended"] = "conversation-ended"
    said: str = ""


class SessionEnded(SessionEvent):
    """A session's runtime ended: its process gone, its room stopping."""

    kind: Literal["session-ended"] = "session-ended"


type Happened = Annotated[
    SessionStarted
    | TurnStarted
    | CallStarting
    | CallFinished
    | TurnEnded
    | ConversationStarted
    | ConversationEnded
    | SessionEnded,
    Field(discriminator="kind"),
]
"""Any of a session's events, as a hook's call carries it: the one its `kind` names."""
