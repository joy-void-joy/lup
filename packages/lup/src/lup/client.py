"""The concrete session surface every consumer holds.

Top-level rather than inside `sessions` because it is what the package root
exports and what a reader meets first — a front door reached through the
package named for the machinery behind it is the shape that made every early
example open a session by importing an adapter instead. What holds it here
rather than one directory down is measured rather than assumed: `create_client`
below routes a model id to whichever provider serves it and `providers` builds
a `Client` back, so the two entries import each other, and moving that routing
to the provider edge is what would settle the placement.

Consumers never hold a capability ABC. ``Client`` is a plain class
parametrized by one swappable ``SessionOpener`` engine: adapters, wrappers,
and tests supply the opener, and the behavior every caller shares — opening a
session, running one turn on it — lives here once.
"""

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Literal, overload

from pydantic import BaseModel

from lup.sessions.events import (
    SessionHandle,
    SessionId,
    TurnInput,
    TurnRequest,
    TurnResult,
    turn_request,
)

type SessionOpener = Callable[
    [SessionId | None], AbstractAsyncContextManager[SessionHandle]
]


class Client:
    """Open configured conversations and run turns on them."""

    def __init__(self, opener: SessionOpener) -> None:
        self.opener = opener

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        """Open a new or resumed session."""
        return self.opener(resume)

    @overload
    async def query[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnResult[T]: ...

    @overload
    async def query(self, request: str | TurnInput) -> TurnResult[None]: ...

    @overload
    async def query[T: BaseModel](
        self, request: str | TurnInput, output_type: type[T]
    ) -> TurnResult[T]: ...

    async def query[T: BaseModel | None](
        self,
        request: TurnRequest[T] | str | TurnInput,
        output_type: type[BaseModel] | None = None,
    ) -> TurnResult[T] | TurnResult[BaseModel] | TurnResult[None]:
        """Open one session, run one turn, and always close the session.

        The overloads carry the same inference `turn_request` protects: a
        prepared request keeps its own parameter, a bare prompt resolves to
        `None`, and a prompt plus a model resolves to that model.
        """
        async with self.open() as handle:
            # Matched on the material rather than on the prepared request: `str`
            # is one of these alternatives and cannot answer for itself, so no
            # base class can carry this for the whole union. Each arm starts its
            # own turn because `TurnRequest` is invariant — a union of them binds
            # no single output type at `start`.
            match request:
                case str() | TurnInput():  # lup: ignore[own-model-dispatch]
                    if output_type is None:
                        turn = await handle.session.start(turn_request(request))
                    else:
                        turn = await handle.session.start(
                            turn_request(request, output_type)
                        )
                case _:
                    turn = await handle.session.start(request)
            return await turn.turn.result()


type Provider = Literal["claude", "codex"]
"""A provider by name, for the one route that dispatches rather than names."""

PROVIDER_PREFIXES: dict[str, Provider] = {
    "claude-": "claude",
    "gpt-": "codex",
    "o1-": "codex",
    "o3-": "codex",
    "o4-": "codex",
}
"""Which vendor's models a model id belongs to, by prefix.

A default rather than a fixture: a vendor ships a new family under a prefix
nobody here has heard of, and an adopter says so by passing its own table
instead of waiting for this one to catch up. First match wins, longest prefix
first, so a narrower entry can sit beside a broader one.
"""


def provider_for(
    model: str, prefixes: Mapping[str, Provider] = PROVIDER_PREFIXES
) -> Provider | None:
    """Which provider serves this model id, or None when nothing claims it."""
    for prefix in sorted(prefixes, key=len, reverse=True):
        if model.startswith(prefix):
            return prefixes[prefix]
    return None


def create_client(
    model: str,
    *,
    provider: Provider | None = None,
    system_prompt: str = "",
    cwd: Path | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    prefixes: Mapping[str, Provider] = PROVIDER_PREFIXES,
) -> Client:
    """Open a session with whichever provider serves this model.

    The convenience over :func:`create_claude` and :func:`create_codex`, for
    the common path where a caller has a model id and does not want to also
    know which vendor owns which prefix. A caller that *does* know says so with
    ``provider``, which skips the table entirely -- that is the escape hatch
    for a model id no prefix claims, and for pointing one vendor's client at
    another's compatible endpoint.

    Deliberately narrower than the two named constructors, and this is the
    reason: dispatch cannot carry typed provider options. ``create_claude``
    takes a ``ClaudeSessionConfig`` and the checker holds it to that; there is
    no type this could accept that would mean "whichever config the model
    turns out to select". So the common arguments are here, the whole
    declaration is there, and neither pretends to be the other.

    An unrecognised model raises rather than guessing a provider. Guessing
    would open a session against the wrong vendor and fail somewhere downstream
    in that vendor's vocabulary, which is a worse error arriving later.
    """
    selected = provider or provider_for(model, prefixes)
    if selected is None:
        known = ", ".join(sorted(prefixes))
        raise LookupError(
            f"no provider claims model {model!r}; known prefixes are {known}. "
            "Pass provider= to say which one serves it, or extend prefixes="
        )
    # Imported per call for the reason the package root defers them: an
    # adapter reaches its provider's whole tool ecosystem, and a caller
    # routing to one should not pay for the other.
    match selected:
        case "claude":
            from lup.providers.claude.runtime import create_claude

            return create_claude(
                model=model,
                system_prompt=system_prompt,
                cwd=cwd,
                base_url=base_url,
                api_key=api_key,
            )
        case "codex":
            from lup.providers.codex.runtime import create_codex

            return create_codex(
                model=model,
                system_prompt=system_prompt,
                cwd=cwd,
                base_url=base_url,
                api_key=api_key,
            )
