"""Debounced background turns on one persistent session.

A runtime-level consumer of the session capabilities: callers push
replaceable typed state, wakes inside the debounce window coalesce, and each
surviving wake becomes one turn on a single long-lived session. Distinct
from :mod:`lup.orchestration.realtime`, which owns a persistent agent's full sleep/wake
lifecycle (scheduler state machine, reminders, subprocess relay) and sits a
layer above this engine.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field

from lup.sessions.errors import TurnError
from lup.sessions.events import TurnResult
from lup.sessions.surface import Agent, Conversation, Turn

logger = logging.getLogger(__name__)


class BackgroundConfig(BaseModel, frozen=True):
    """Scheduling behavior independent from provider construction."""

    debounce_seconds: float = Field(default=0.1, ge=0)


type StateToTurn[S: BaseModel, T: BaseModel | None] = Callable[
    [Conversation, S], Turn[T]
]
"""How the latest state is put to the session: asked as one turn of it.

A callable rather than a prompt, because asking is where the turn's output
type is named, and naming it at the call is what keeps the result typed.
"""
type BackgroundResultHandler[T: BaseModel | None] = Callable[
    [TurnResult[T]], Awaitable[None]
]
type BackgroundErrorHandler = Callable[[TurnError], Awaitable[None]]


class BackgroundAgent[S: BaseModel, T: BaseModel | None]:
    """Coalesce wakes and execute the latest typed state in one persistent session."""

    def __init__(
        self,
        agent: Agent,
        state_to_turn: StateToTurn[S, T],
        result_handler: BackgroundResultHandler[T],
        error_handler: BackgroundErrorHandler,
        config: BackgroundConfig | None = None,
    ) -> None:
        self.agent = agent
        self.state_to_turn = state_to_turn
        self.result_handler = result_handler
        self.error_handler = error_handler
        self.config = config or BackgroundConfig()
        self.changed = asyncio.Event()
        self.pending: S | None = None
        self.task: asyncio.Task[None] | None = None
        self.stopping = False

    async def start(self) -> None:
        """Start one scheduler task; provider resources remain lazily opened there."""
        if self.task is not None and not self.task.done():
            raise RuntimeError("background agent is already started")
        self.stopping = False
        self.task = asyncio.create_task(self.run())

    def wake(self, state: S) -> None:
        """Replace pending state and wake the debounce loop."""
        if self.stopping:
            raise RuntimeError("background agent is stopping")
        self.pending = state.model_copy(deep=True)
        self.changed.set()

    async def stop(self) -> None:
        """Stop scheduling and abort an unfinished native turn on context exit."""
        self.stopping = True
        self.changed.set()
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                logger.debug("background agent scheduler stopped by cancellation")
            self.task = None

    async def run(self) -> None:
        async with self.agent.open() as conversation:
            while not self.stopping:
                await self.changed.wait()
                self.changed.clear()
                if self.stopping:
                    break
                await self.debounce()
                state = self.pending
                self.pending = None
                if state is None:
                    continue
                try:
                    result = await self.state_to_turn(conversation, state)
                except TurnError as error:
                    await self.error_handler(error)
                else:
                    await self.result_handler(result)

    async def debounce(self) -> None:
        """Restart the window while additional wakes arrive."""
        while self.config.debounce_seconds > 0:
            try:
                await asyncio.wait_for(
                    self.changed.wait(), timeout=self.config.debounce_seconds
                )
            except TimeoutError:
                return
            self.changed.clear()
            if self.stopping:
                return
