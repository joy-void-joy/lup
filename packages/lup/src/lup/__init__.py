"""Lup's deliberately small, provider-neutral runtime front door.

Two kinds of name are exported here, and the distinction is why the second kind
is reached the way it is.

The vocabulary -- sessions, turns, requests, results, and which vendor claims a
model id -- is provider-neutral and free to import: naming it costs
`lup.sessions` and the routing table at the vendor edge, three modules more
and no measurable time, with neither SDK among them. The **constructors** are
not, because each one reaches an adapter, and an adapter reaches the tool
ecosystem its provider speaks. Imported eagerly here, `import
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

from collections.abc import Callable, Sequence
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

from lup.providers.routing import PROVIDER_ROUTES, Provider, ProviderRoute, provider_for
from lup.sessions.client import Client
from lup.sessions.events import (
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
    from lup.providers.claude.runtime import create_claude
    from lup.providers.codex.runtime import create_codex

# Where each deferred name actually lives, so the resolution below is a lookup
# rather than a branch per provider -- a third adapter is one row.
# lup: ignore[library-default] — the constructors this library authors and the
# modules it defines them in, so the table is what lup ships rather than a
# choice made for an adopter: a provider arrives here as an adapter, and a row
# an adopter replaced would point `from lup import create_claude` at something
# lup never wrote.
CONSTRUCTORS = {
    "create_claude": "lup.providers.claude.runtime",
    "create_codex": "lup.providers.codex.runtime",
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
    return getattr(import_module(CONSTRUCTORS[name]), name)


def create_client(
    model: str,
    *,
    provider: Provider | None = None,
    system_prompt: str = "",
    cwd: Path | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    routes: Sequence[ProviderRoute] = PROVIDER_ROUTES,
) -> Client:
    """Open a session with whichever provider serves this model.

    The convenience over :func:`create_claude` and :func:`create_codex`, for
    the common path where a caller has a model id and does not want to also
    know which vendor owns which prefix. A caller that *does* know says so with
    ``provider``, which skips the routes entirely -- that is the escape hatch
    for a model id nothing claims, and for pointing one vendor's client at
    another's compatible endpoint.

    Here rather than beside ``Client`` because this is the only name at the
    front door that has to know what is behind every door it opens. Written
    one module down it made that module and ``providers`` import each other,
    for the sake of a routing table the vendor edge was already keeping in
    another shape.

    Deliberately narrower than the two named constructors, and this is the
    reason: dispatch cannot carry typed provider options. ``create_claude``
    takes a ``ClaudeSessionConfig`` and the checker holds it to that; there is
    no type this could accept that would mean "whichever config the model
    turns out to select". So the common arguments are here, the whole
    declaration is there, and neither pretends to be the other.

    An unrecognised model raises rather than guessing a provider. Guessing
    would open a session against the wrong vendor and fail somewhere
    downstream in that vendor's vocabulary, which is a worse error arriving
    later.
    """
    selected = provider or provider_for(model, routes)
    if selected is None:
        claimed = ", ".join(sorted({route.provider for route in routes}))
        raise LookupError(
            f"no provider claims model {model!r}; routes are declared for "
            f"{claimed}. Pass provider= to say which one serves it, or extend "
            "routes="
        )
    # Resolved through the same table the deferred constructors above use, for
    # the reason that table exists: a third adapter is one row rather than one
    # more arm of a match nobody remembers to widen. `CONSTRUCTORS` is not a
    # parameter here because it says outright that it is not an adopter's to
    # replace. Imported per call for the reason it defers at all -- an adapter
    # reaches its provider's whole tool ecosystem, and a caller routing to one
    # should not pay for the other.
    named = f"create_{selected}"
    factory = getattr(import_module(CONSTRUCTORS[named]), named)
    return factory(
        model=model,
        system_prompt=system_prompt,
        cwd=cwd,
        base_url=base_url,
        api_key=api_key,
    )


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
