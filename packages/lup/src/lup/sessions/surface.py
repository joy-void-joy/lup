"""What every provider's agents, sessions and turns answer, for code naming none.

Each provider carries its own classes, and they hold exactly what that
provider supports: ``CodexTurn`` steers and ``ClaudeTurn`` has no ``steer`` at
all, because Claude's adapter provides none — a capability is present or
absent on the type, never present and ``None``. Code that has to work over
either provider — the resolver, a relay, a background agent — names these
protocols instead, and asks only for what both answer.

Structural rather than nominal, so nothing registers against them: the
provider classes satisfy them by having the methods, and so does a test's
double.
"""

from collections.abc import AsyncIterable, AsyncIterator, Awaitable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, Self, overload

from pydantic import BaseModel

from lup.sessions.events import (
    AnyTurnBlock,
    LiveTurnEvent,
    SessionId,
    SessionSummary,
    TurnEvent,
    TurnInput,
    TurnMessage,
    TurnResult,
)
from lup.sessions.layers import SessionLayers


class Turn[T: BaseModel | None](
    Awaitable[TurnResult[T]], AsyncIterable[AnyTurnBlock], Protocol
):
    """One turn of a conversation, started the first time anything asks.

    Awaiting it is its result; iterating it is its completed blocks, in the
    order they finished. Either starts it, and so do ``events``, ``live`` and
    ``interrupt``, which is what keeps the submission tool bound before the
    provider accepts the prompt. It starts once however many ask, and awaiting
    it again — after iterating, or after awaiting — returns the same result.
    """

    def events(self) -> AsyncIterator[TurnEvent]:
        """Every durable event of this turn, from its first, as they happen."""
        ...

    def live(self) -> AsyncIterator[LiveTurnEvent]:
        """The durable events and the deltas between them, as they happen."""
        ...

    async def interrupt(self) -> None:
        """Stop this turn, returning once it has stopped."""
        ...


class Conversation(Protocol):
    """One open session with a provider, whichever provider it is."""

    @property
    def id(self) -> SessionId:
        """The provider's own identity for this conversation, which resumes it."""
        ...

    @overload
    def ask(self, prompt: str | TurnInput) -> Turn[None]: ...

    @overload
    def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T]
    ) -> Turn[T]: ...

    async def history(self) -> list[TurnMessage]:
        """Every message of this conversation, as the provider recorded it."""
        ...


class Agent(Protocol):
    """One declared agent: what opens its sessions and lists the old ones."""

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[Conversation]:
        """Open a new conversation, or resume the one ``resume`` names."""
        ...

    @overload
    async def ask(self, prompt: str | TurnInput) -> TurnResult[None]: ...

    @overload
    async def ask[T: BaseModel](
        self, prompt: str | TurnInput, output: type[T]
    ) -> TurnResult[T]: ...

    async def sessions(self) -> list[SessionSummary]:
        """The conversations the provider has on record for this agent's workspace."""
        ...

    def layered(self, layers: SessionLayers) -> Self:
        """This agent with ``layers`` laid over its own, the fields set there winning.

        How a caller holding an agent it did not declare imposes a layer on
        every session it opens — the resolver's correction cycles on whatever
        worker a recipe hands it — without knowing which provider it holds.
        """
        ...
