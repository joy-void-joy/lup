"""Narrow, independently constructible runtime capability contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from lup.runtime.models import (
        LiveTurnEvent,
        SessionHandle,
        TurnEvent,
        TurnHandle,
        TurnId,
        TurnInput,
        TurnRequest,
        TurnResult,
        TurnToolBinding,
    )


class Session(ABC):
    """Start one acknowledged turn in a conversation."""

    @abstractmethod
    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> TurnHandle[T]:
        """Bind the request and return its accepted native turn."""


class Turn[T: BaseModel | None](ABC):
    """Resolve one accepted logical turn."""

    @abstractmethod
    async def result(self) -> TurnResult[T]:
        """Wait for successful terminal completion."""


class EventStream(ABC):
    """Expose a turn's events, durable or live, in native arrival order.

    Two accessors over one ordering. ``live()`` yields everything
    ``events()`` does *plus* deltas, so the two are a subset and a superset
    rather than two views that can disagree — a consumer picks one and gets
    consistent behaviour either way.
    """

    @abstractmethod
    def events(self) -> AsyncIterator[TurnEvent]:
        """Iterate the durable events once, in native arrival order.

        Everything that happened and nothing in flight, so the result folds
        into an exact transcript.
        """

    @abstractmethod
    def live(self) -> AsyncIterator[LiveTurnEvent]:
        """Iterate durable events and in-flight deltas once, interleaved.

        Raises :class:`DeltaStreamingDisabled` when the session was not
        built to stream partials, because silently yielding no deltas would
        read as a quiet turn rather than as a session built without them.
        """


class Interrupt(ABC):
    """Interrupt an active turn."""

    @abstractmethod
    async def interrupt(self) -> None:
        """Request interruption and wait for native acknowledgement."""


class Steer(ABC):
    """Append input to an active turn."""

    @abstractmethod
    async def steer(self, input: TurnInput) -> None:
        """Append input without creating a second turn."""


class ForkSession(ABC):
    """Fork a conversation at an optional completed turn."""

    @abstractmethod
    def fork(
        self, at: TurnId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        """Open the fork as an independent session."""


class SubmittedOutputStore(ABC):
    """Persist and retrieve validated per-turn submitted output."""

    @abstractmethod
    def write(
        self,
        value: BaseModel,  # lup: ignore[bare-basemodel] — generic output-store boundary
    ) -> None:
        """Replace the value held by this turn-scoped store."""

    @abstractmethod
    def read[T: BaseModel](self, output_type: type[T]) -> T | None:
        """Read and validate the current value, if one was submitted."""


class TurnToolBinder(ABC):
    """Install, replace, or remove the portable submission tool."""

    @abstractmethod
    async def bind[T: BaseModel](self, binding: TurnToolBinding[T] | None) -> None:
        """Finish binding before native turn input is accepted."""
