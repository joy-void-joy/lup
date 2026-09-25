"""Inference pins for the one verb, ``ask``, on an agent and on its session.

``ask`` is overloaded so each call shape resolves to one exact type rather
than a union. The `assert_type` calls below are the regression guard: pyright
— which `lup-devtools dev check` runs — fails the moment a later
simplification collapses an overload set and widens what a call infers. Each
pin sits on a call that also executes, so the pinned shapes cannot drift away
from working code.
"""

from datetime import timedelta
from typing import assert_type

import pytest
from pydantic import BaseModel

from lup.sessions.capabilities import SessionEngine, TurnEngine
from lup.sessions.events import (
    SessionId,
    StartedTurn,
    TurnId,
    TurnIdentifiers,
    TurnInput,
    TurnRequest,
    TurnResult,
)
from lup.types import Usage
from lup.providers.claude import ClaudeTurn
from tests.unit.doubles import EngineAgent, IgnoredInterrupt, SilentStream, agent_over

IDENTIFIERS = TurnIdentifiers(
    session=SessionId(value="session"), turn=TurnId(value="turn")
)


class Summary(BaseModel, frozen=True):
    """A default-constructible output model, so the stub can submit one."""

    title: str = "pinned"


class StubTurn[T: BaseModel | None](TurnEngine[T]):
    """Complete immediately, submitting an instance of the requested model."""

    def __init__(self, request: TurnRequest[T]) -> None:
        self.request = request

    async def result(self) -> TurnResult[T]:
        output_type = self.request.output_type
        # Constructed here rather than through the shared `turn_result`: the
        # instance this builds is a `T` only by the request's own construction,
        # which is a fact `model_validate` accepts and no signature can state.
        return TurnResult[T].model_validate(
            {
                "output": None if output_type is None else output_type(),
                "messages": [],
                "blocks": [],
                "usage": Usage(),
                "duration": timedelta(),
                "identifiers": IDENTIFIERS,
            }
        )


class StubSession(SessionEngine):
    """Record the text every turn was started with."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def start[T: BaseModel | None](
        self, request: TurnRequest[T]
    ) -> StartedTurn[T]:
        self.prompts.append(request.input.text)
        return StartedTurn[T](
            turn=StubTurn(request),
            events=SilentStream(),
            interrupt=IgnoredInterrupt(),
        )

    def agent(self) -> EngineAgent:
        """An agent whose every opened session is this one."""
        return agent_over(self)


@pytest.mark.asyncio
async def test_a_one_shot_ask_infers_its_output_from_what_it_names() -> None:
    session = StubSession()
    agent = session.agent()

    plain = await agent.ask("summarize")
    typed = await agent.ask("summarize", Summary)
    from_input = await agent.ask(TurnInput(text="wrapped"))
    typed_input = await agent.ask(TurnInput(text="wrapped"), Summary)

    assert_type(plain, TurnResult[None])
    assert_type(typed, TurnResult[Summary])
    assert_type(from_input, TurnResult[None])
    assert_type(typed_input, TurnResult[Summary])
    assert plain.output is None
    assert typed.output.title == "pinned"
    assert session.prompts == ["summarize", "summarize", "wrapped", "wrapped"]


@pytest.mark.asyncio
async def test_a_session_turn_carries_its_output_type_until_awaited() -> None:
    session = StubSession()

    async with session.agent().open() as opened:
        plain = opened.ask("summarize")
        typed = opened.ask(TurnInput(text="wrapped"), Summary)

        assert_type(plain, ClaudeTurn[None])
        assert_type(typed, ClaudeTurn[Summary])
        assert session.prompts == []
        assert_type(await plain, TurnResult[None])
        assert (await typed).output.title == "pinned"

    assert session.prompts == ["summarize", "wrapped"]
