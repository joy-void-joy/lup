"""Lup's deliberately small, provider-neutral runtime front door.

Two kinds of name are exported here, and the distinction is why the second kind
is reached the way it is.

The vocabulary -- sessions, turns, results, and the protocols code naming no
provider holds -- is provider-neutral and free to import: naming it costs
`lup.sessions`, with neither SDK among it. The **agents** are not, because
each one is declared in terms of the tools its provider speaks, and those
reach an MCP server and the rest of that ecosystem. Imported eagerly here,
`import lup` would pull several hundred modules on behalf of a caller who may
have wanted a type annotation.

So `Claude` and `Codex` resolve on first access instead. A reader still
writes `from lup import Claude` and a checker still sees the real class --
the `TYPE_CHECKING` block below is what it reads -- while a module that only
annotates against `Agent` pays for none of it.

This module is a re-export and nothing else: every name here is defined in
the module a reader could import it from, and nothing inside the library
imports from here.

That laziness is also what keeps the harder promise: neither provider SDK is
imported by `import lup`, nor by naming an agent, but only by opening a
session with one.
"""

from importlib import import_module
from typing import TYPE_CHECKING

from lup.sessions.events import (
    SessionId,
    SessionSummary,
    TurnId,
    TurnInput,
    TurnMessage,
    TurnResult,
)
from lup.sessions.surface import Agent, Conversation, Turn
from lup.types import CustomModel

if TYPE_CHECKING:
    from lup.providers.claude import Claude
    from lup.providers.codex import Codex

# Where each deferred name actually lives, so the resolution below is a lookup
# rather than a branch per provider -- a third adapter is one row.
# lup: ignore[library-default] — the agents this library authors and the
# modules it defines them in, so the table is what lup ships rather than a
# choice made for an adopter: a provider arrives here as an adapter, and a row
# an adopter replaced would point `from lup import Claude` at something lup
# never wrote.
AGENTS = {
    "Claude": "lup.providers.claude",
    "Codex": "lup.providers.codex",
}


def __getattr__(name: str) -> "type[Claude] | type[Codex]":
    """Resolve an agent on first access, and nothing else.

    PEP 562's module hook, used for exactly the names above. Anything else
    raises the ``AttributeError`` Python would have raised anyway, in the same
    words, so a typo at the front door reads as a typo rather than as an import
    failure somewhere inside an adapter.
    """
    if name not in AGENTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(AGENTS[name]), name)


__all__ = [  # lup: ignore[all-export] -- the package-root public API
    "Agent",
    "Claude",
    "Codex",
    "Conversation",
    "CustomModel",
    "SessionId",
    "SessionSummary",
    "Turn",
    "TurnId",
    "TurnInput",
    "TurnMessage",
    "TurnResult",
]
