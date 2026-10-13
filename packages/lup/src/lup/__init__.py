"""Build with Claude and Codex agents from code.

`lup` is what a project's production code imports, as opposed to `lup_dev`, which
the project uses only while it's being developed. It grows to hold
(`DESIGN.md`, *Calling agents from code*):
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
from lup.errors import LupError
from lup.sessions.errors import (
    AgentUnavailableError,
    AuthMissingError,
    OutputMissingError,
    ProblemReportedError,
    RuntimeMissingError,
    ToolsPresentError,
    TurnError,
    TurnTimeoutError,
    UsageLimitReachedError,
)
from lup.sessions.layers import Recovery, SessionLayers, Submission
from lup.sessions.results import Rejection, TurnResult, Usage
from lup.sessions.surface import Agent

__all__ = [
    "Agent",
    "AgentUnavailableError",
    "AuthMissingError",
    "Claude",
    "Codex",
    "LupError",
    "OutputMissingError",
    "ProblemReportedError",
    "Recovery",
    "Rejection",
    "RuntimeMissingError",
    "SessionLayers",
    "Submission",
    "ToolsPresentError",
    "TurnError",
    "TurnResult",
    "TurnTimeoutError",
    "Usage",
    "UsageLimitReachedError",
]
