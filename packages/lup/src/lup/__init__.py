"""Lup's deliberately small, provider-neutral runtime front door.

Two kinds of name are exported here, and the distinction is why the second kind
is reached the way it is.

The vocabulary -- sessions, turns, requests, results -- is provider-neutral and
free to import: naming it costs nothing beyond the runtime package itself. The
**constructors** are not, because each one reaches an adapter, and an adapter
reaches the tool ecosystem its provider speaks. Imported eagerly here, `import
lup` pulls 811 modules and roughly 1.3 seconds, including an ASGI server and a
CLI framework, on behalf of a caller who may have wanted a type annotation.

So `create_claude` and `create_codex` resolve on first access instead. A reader
still writes `from lup import create_claude` and a checker still sees the real
signature -- the `TYPE_CHECKING` block below is what it reads -- while a module
that only annotates against `Client` pays for none of it.

That laziness is also what keeps the harder promise: neither provider SDK is
imported by `import lup`, nor by naming a constructor, but only by opening a
session with one.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from lup.client import Client, Provider, create_client
from lup.runtime.models import (
    SessionHandle,
    SessionId,
    TurnHandle,
    TurnId,
    TurnInput,
    TurnRequest,
    TurnResult,
    turn_request,
)

if TYPE_CHECKING:
    from lup.adapters.claude.runtime import create_claude
    from lup.adapters.codex.runtime import create_codex

# Where each deferred name actually lives, so the resolution below is a lookup
# rather than a branch per provider -- a third adapter is one row.
CONSTRUCTORS = {
    "create_claude": "lup.adapters.claude.runtime",
    "create_codex": "lup.adapters.codex.runtime",
}


def __getattr__(name: str) -> Callable[..., Client]:
    """Resolve a constructor on first access, and nothing else.

    PEP 562's module hook, used for exactly the names above. Anything else
    raises the ``AttributeError`` Python would have raised anyway, in the same
    words, so a typo at the front door reads as a typo rather than as an import
    failure somewhere inside an adapter.

    The return type is the one thing every constructor here agrees on. Each
    takes its own provider's options, which is why the checker reads the
    signatures from the ``TYPE_CHECKING`` block above rather than from this.
    """
    if name not in CONSTRUCTORS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(CONSTRUCTORS[name]), name)


__all__ = [  # lup: ignore[all-export] -- the package-root public API
    "Client",
    "Provider",
    "SessionHandle",
    "SessionId",
    "TurnHandle",
    "TurnId",
    "TurnInput",
    "TurnRequest",
    "TurnResult",
    "create_claude",
    "create_client",
    "create_codex",
    "turn_request",
]
