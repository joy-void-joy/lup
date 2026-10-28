"""Build with Claude and Codex agents from code.

`lup` is the library core: what code calling agents imports, wherever it runs, as
opposed to `lup_dev`, the environment, which only a project's sessions need. It
grows to hold (`DESIGN.md`, *Calling agents from code*):
- clients for Claude and Codex, whose `ask` returns a typed answer, and
  conversations with their history;
- tools written as plain Python functions;
- rooms: an agent working on a task inside a container, waited on, left running
  as a spawned session, or opened in a terminal;
- coordination between the agents a project runs, and request budgets shared
  across processes;
- runs, durable work that outlives the call that started it, and the outcome
  loop that compares versions of a project's agents by how they fared;
- traces and cost for every call;
- a fake agent, and a guard that keeps tests from reaching real agents or the
  network.

It holds the first slice (`docs/library.md`): asking either runtime from code, a
typed answer through the output tool, the layers an ask runs in, its record, and
the fake and the guard (`lup.testing`). Beside it, each declaration compiles for a
terminal too, and a room opens that terminal in a container (`lup.rooms`,
`docs/launch.md`).

It holds, too, the doors a module's methods are reached through, each a
decorator (`lup.doors`): `lup.tool`, which a plain function given to an ask is
made a tool with too, `lup.request`, `lup.on`, `lup.view` and `lup.command`; lup's events, one
class each (`lup.events`); what a hook at `Publishing` reads and refuses
(`lup.publishing`); and the building blocks a view is laid out from
(`lup.blocks`). `lup_dev` serves them.

    translator = Claude(model="opus", system_prompt=PROMPT)
    result = await translator.ask(segment.model_dump_json(), Translations)
    result.output  # Translations

`Claude` and `Codex` import their runtime's SDK when an ask first runs, so
`import lup` reaches neither, a declaration compiles for a terminal without either,
and a project installs only the extra it asks through (`lup[claude]`,
`lup[codex]`). Code that shouldn't care which it gets takes an `Agent`.
"""

from lup.adapters.claude import Claude
from lup.adapters.codex import Codex
from lup.blocks import (
    Banner,
    Blocks,
    Code,
    Diff,
    Drawer,
    FileBytes,
    FileText,
    Fold,
    FoldKind,
    Gauge,
    Line,
    Load,
    Mark,
    Markdown,
    OfAgent,
    Offer,
    Span,
    Ticking,
    Tone,
    Verb,
    Watch,
)
from lup.doors import command, on, request, tool, view
from lup.errors import LupError
from lup.events import (
    CallFinished,
    CallStarted,
    ConversationEnded,
    Event,
    Launched,
    Publishing,
    SessionStarted,
    Stopped,
    TurnEnded,
    TurnStarted,
)
from lup.publishing import Part, Place, Post, Published, Push, Refusal
from lup.sessions.errors import (
    AgentUnavailableError,
    AuthMissingError,
    BlockedError,
    OutputMissingError,
    RuntimeMissingError,
    StoppedError,
    ToolsPresentError,
    TurnError,
    TurnTimeoutError,
    UsageLimitReachedError,
)
from lup.sessions.layers import Recovery, SessionLayers, Submission
from lup.sessions.results import Friction, HowItWent, Rejection, TurnResult, Usage
from lup.sessions.surface import Agent

__all__ = [
    "Agent",
    "AgentUnavailableError",
    "AuthMissingError",
    "Banner",
    "BlockedError",
    "Blocks",
    "CallFinished",
    "CallStarted",
    "Claude",
    "Code",
    "Codex",
    "ConversationEnded",
    "Diff",
    "Drawer",
    "Event",
    "FileBytes",
    "FileText",
    "Fold",
    "FoldKind",
    "Friction",
    "Gauge",
    "HowItWent",
    "Launched",
    "Line",
    "Load",
    "LupError",
    "Mark",
    "Markdown",
    "OfAgent",
    "Offer",
    "OutputMissingError",
    "Part",
    "Place",
    "Post",
    "Published",
    "Publishing",
    "Push",
    "Recovery",
    "Refusal",
    "Rejection",
    "RuntimeMissingError",
    "SessionLayers",
    "SessionStarted",
    "Span",
    "Stopped",
    "StoppedError",
    "Submission",
    "Ticking",
    "Tone",
    "ToolsPresentError",
    "TurnEnded",
    "TurnError",
    "TurnResult",
    "TurnStarted",
    "TurnTimeoutError",
    "Usage",
    "UsageLimitReachedError",
    "Verb",
    "Watch",
    "command",
    "on",
    "request",
    "tool",
    "view",
]
