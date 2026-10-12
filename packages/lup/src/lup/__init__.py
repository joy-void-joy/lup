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

`Claude` and `Codex` load on first use, so `import lup` reaches neither runtime's
SDK, and a project installs only the extra it uses (`lup[claude]`, `lup[codex]`).
Code that shouldn't care which it gets takes an `Agent`.
"""

import importlib
from typing import TYPE_CHECKING

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
from lup.types import Model

if TYPE_CHECKING:
    from lup.adapters.claude import Claude
    from lup.adapters.codex import Codex

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


class Loaded(Model):
    """A name the front door loads on first use: the module defining it, and the extra it needs."""

    module: str
    extra: str


LOADED = {
    "Claude": Loaded(module="lup.adapters.claude", extra="claude"),
    "Codex": Loaded(module="lup.adapters.codex", extra="codex"),
}
"""The names loaded on first use, each from the adapter that defines it."""


def __getattr__(name: str) -> type[Agent]:
    """Load `Claude` or `Codex` from its adapter, or say which extra to install."""
    loaded = LOADED.get(name)
    if loaded is None:
        message = f"module 'lup' has no attribute {name!r}"
        raise AttributeError(message)
    try:
        module = importlib.import_module(loaded.module)
    except ModuleNotFoundError as missing:
        if missing.name is None or missing.name.startswith("lup"):
            raise
        message = (
            f"`{name}` needs the `lup[{loaded.extra}]` extra, which isn't installed "
            f"(no module {missing.name!r}): install `lup[{loaded.extra}]`"
        )
        raise RuntimeMissingError(message) from missing
    return getattr(module, name)
