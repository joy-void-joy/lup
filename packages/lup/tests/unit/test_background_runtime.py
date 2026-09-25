"""Provider-independent background queue/debounce scheduling tests."""

import asyncio

import pytest
from pydantic import BaseModel

from lup.orchestration.background import BackgroundAgent, BackgroundConfig
from lup.sessions.composition import AcceptedTurn, CompletedTurn, ComposedSession
from lup.sessions.errors import TurnError
from lup.sessions.events import (
    SessionId,
    TurnIdentifiers,
    TurnId,
    TurnResult,
)
from lup.sessions.surface import Conversation, Turn
from tests.unit.test_capability_runtime import RecordingBinder
from tests.unit.doubles import EngineAgent, IgnoredInterrupt, SilentStream


class BackgroundState(BaseModel, frozen=True):
    value: int


class RecordingEngines:
    """Open a composed engine per session, recording every prompt it is asked."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.sequence = 0

    def engine(self, _resume: SessionId | None) -> ComposedSession:
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
                events=SilentStream(),
                interrupt=IgnoredInterrupt(),
            )

        return ComposedSession(start, RecordingBinder())


@pytest.mark.asyncio
async def test_background_agent_coalesces_to_latest_state() -> None:
    engines = RecordingEngines()
    completed = asyncio.Event()
    results: list[TurnResult[None]] = []
    errors: list[TurnError] = []

    def asked(conversation: Conversation, state: BackgroundState) -> Turn[None]:
        return conversation.ask(f"state={state.value}")

    async def result_handler(result: TurnResult[None]) -> None:
        results.append(result)
        completed.set()

    async def error_handler(error: TurnError) -> None:
        errors.append(error)
        completed.set()

    agent = BackgroundAgent[BackgroundState, None](
        EngineAgent(engines.engine),
        asked,
        result_handler,
        error_handler,
        BackgroundConfig(debounce_seconds=0.001),
    )
    await agent.start()
    agent.wake(BackgroundState(value=1))
    agent.wake(BackgroundState(value=2))
    await asyncio.wait_for(completed.wait(), timeout=1)
    await agent.stop()

    assert engines.prompts == ["state=2"]
    assert len(results) == 1
    assert errors == []
