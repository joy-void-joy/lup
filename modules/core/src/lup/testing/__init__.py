"""The promises' library side: the harness a promise reaches lup through, and what it answers.

A promise imports this and `lup` alone, which an import contract holds: the
harness (`Testing`, handed to a scenario as `by`), lup as it starts it
(`Started`), the step an invariant reads (`Step`), what a call through a door answers,
the guidance a started lup renders (`Guidance`), what checking a promise found
(`Kept`, `Broken`), and `raises`, which says a block fails. `lup` re-exports the
promise door, `lup.promise`. Checking promises is the environment's
(`lup.environment.testing`). Its reasons are in `README.md` here.
"""

from lup.command_line.answering import Typed
from lup.doors.door import Accepted, Refused, Rejection
from lup.doors.events import Heeded
from lup.doors.tool import ToolSpec
from lup.shell.draft import Comment, Draft, Marked, Quote, Within
from lup.shell.wire import (
    Answered,
    Delivered,
    Drafted,
    Erase,
    Hello,
    Mark,
    Opened,
    Reviewed,
    Send,
    Told,
    Unanswered,
    Unwatch,
    Watch,
    Write,
)
from lup.testing.git import RealGit
from lup.testing.harness import (
    Acting,
    Answering,
    Broken,
    BrokenInvariantError,
    Call,
    Kept,
    Page,
    ProgramRun,
    Ran,
    Repository,
    Responding,
    Scripted,
    Sent,
    Served,
    Started,
    Step,
    Testing,
    ToolCall,
    Viewed,
)
from lup.testing.raising import Raised, raises
from lup.told.guidance import Guidance, Section

__all__ = [
    "Accepted",
    "Acting",
    "Answered",
    "Answering",
    "Broken",
    "BrokenInvariantError",
    "Call",
    "Comment",
    "Delivered",
    "Draft",
    "Drafted",
    "Erase",
    "Guidance",
    "Heeded",
    "Hello",
    "Kept",
    "Mark",
    "Marked",
    "Opened",
    "Page",
    "ProgramRun",
    "Quote",
    "Raised",
    "Ran",
    "RealGit",
    "Refused",
    "Rejection",
    "Repository",
    "Responding",
    "Reviewed",
    "Scripted",
    "Section",
    "Send",
    "Sent",
    "Served",
    "Started",
    "Step",
    "Testing",
    "Told",
    "ToolCall",
    "ToolSpec",
    "Typed",
    "Unanswered",
    "Unwatch",
    "Viewed",
    "Watch",
    "Within",
    "Write",
    "raises",
]
