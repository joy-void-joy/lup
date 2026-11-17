"""The promises' library side: the harness a promise reaches lup through, and what it answers.

A promise imports this and `lup` alone, which an import contract holds: the
harness (`Testing`, handed to a scenario as `by`), lup as it starts it
(`Started`), the step a law reads (`Step`), what a call through a door answers,
what checking a promise found (`Kept`, `Broken`), and `raises`, which says a
block fails. `lup` re-exports the promise door, `lup.promise`. Checking
promises is the environment's (`lup.environment.testing`). Its reasons are in
`README.md` here.
"""

from lup.doors.door import Accepted, Refused, Rejection
from lup.doors.tool import ToolSpec
from lup.shell.draft import Comment, Draft, Marked, Quote
from lup.shell.wire import (
    Answered,
    Delivered,
    Drafted,
    Erase,
    Hello,
    Mark,
    Opened,
    Send,
    Unanswered,
    Unwatch,
    Watch,
    Write,
)
from lup.testing.harness import (
    Acted,
    Answering,
    Broken,
    BrokenLawError,
    Call,
    Kept,
    Page,
    ProgramRun,
    Ran,
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

__all__ = [
    "Accepted",
    "Acted",
    "Answered",
    "Answering",
    "Broken",
    "BrokenLawError",
    "Call",
    "Comment",
    "Delivered",
    "Draft",
    "Drafted",
    "Erase",
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
    "Refused",
    "Rejection",
    "Scripted",
    "Send",
    "Sent",
    "Served",
    "Started",
    "Step",
    "Testing",
    "ToolCall",
    "ToolSpec",
    "Unanswered",
    "Unwatch",
    "Viewed",
    "Watch",
    "Write",
    "raises",
]
