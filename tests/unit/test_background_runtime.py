"""Provider-independent background queue/debounce scheduling tests."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from pydantic import BaseModel, ConfigDict

from lup.runtime.background import BackgroundAgent, BackgroundConfig
from lup.runtime.composition import AcceptedTurn, CompletedTurn, ComposedSession
from lup.runtime.contracts import SessionFactory
from lup.runtime.errors import TurnError
from lup.runtime.models import (
    SessionHandle,
    SessionId,
    TurnIdentifiers,
    TurnId,
    TurnInput,
    TurnRequest,
    TurnResult,
    turn_request,
)
from tests.unit.test_capability_runtime import RecordingBinder


class BackgroundState(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: int


class RecordingFactory(SessionFactory):
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.sequence = 0

    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        return self.session_context()

    @asynccontextmanager
    async def session_context(self) -> AsyncIterator[SessionHandle]:
        binder = RecordingBinder()

        async def start(text: str) -> AcceptedTurn:
            self.prompts.append(text)
            self.sequence += 1

            async def complete() -> CompletedTurn:
                return CompletedTurn()

            return AcceptedTurn(
                identifiers=TurnIdentifiers(
                    session=SessionId(value="background"),
                    turn=TurnId(value=f"turn-{self.sequence}"),
                ),
                complete=complete,
            )

        session = ComposedSession(start, binder)
        try:
            yield SessionHandle(session=session)
        finally:
            await session.abort_active()


@pytest.mark.asyncio
async def test_background_agent_coalesces_to_latest_state() -> None:
    factory = RecordingFactory()
    completed = asyncio.Event()
    results: list[TurnResult[None]] = []
    errors: list[TurnError] = []

    def request(state: BackgroundState) -> TurnRequest[None]:
        return turn_request(TurnInput(text=f"state={state.value}"))

    async def result_handler(result: TurnResult[None]) -> None:
        results.append(result)
        completed.set()

    async def error_handler(error: TurnError) -> None:
        errors.append(error)
        completed.set()

    agent = BackgroundAgent[BackgroundState, None](
        factory,
        request,
        result_handler,
        error_handler,
        BackgroundConfig(debounce_seconds=0.001),
    )
    await agent.start()
    agent.wake(BackgroundState(value=1))
    agent.wake(BackgroundState(value=2))
    await asyncio.wait_for(completed.wait(), timeout=1)
    await agent.stop()

    assert factory.prompts == ["state=2"]
    assert len(results) == 1
    assert errors == []
