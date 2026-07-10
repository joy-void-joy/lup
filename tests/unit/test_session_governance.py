# lup: ignore[empty-collection]
# Test fixtures and assertions construct these shapes deliberately.
"""Budget and timeout governance on the session wrappers.

The wrappers are engine-agnostic — they govern any ``Session`` that
reports normalized usage — so these tests drive them over plain fakes:
cost accumulates across turns and stamps results, the turn after the
budget is crossed is refused, cumulative engines replace the running
total instead of adding to it, and a slow turn is cancelled at the wall
clock.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest

from lup.adapters.clients.sessions.budget import BudgetedSession, BudgetedSessions
from lup.adapters.clients.sessions.Session import Session
from lup.adapters.clients.sessions.Sessions import Sessions
from lup.adapters.clients.sessions.timeout import TimeoutSession, TimeoutSessions
from lup.adapters.errors import BudgetExceededError, TurnTimeoutError
from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse, LupResultMessage, Usage


def response_with_usage(usage: Usage | None) -> LupResponse:
    return LupResponse(result=LupResultMessage(usage=usage))


class FakeSession(Session):
    """Scripted session: one prepared response per send, optional delay."""

    def __init__(self, responses: list[LupResponse], *, delay: float = 0.0) -> None:
        self.responses = responses
        self.delay = delay
        self.prompts: list[str] = []
        self.id = "fake-1"

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        self.prompts.append(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.responses[len(self.prompts) - 1]

    async def interrupt(self) -> None:
        raise NotImplementedError


class FakeSessions(Sessions):
    """Opener yielding one scripted session, recording resume ids."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.resumes: list[str | None] = []

    @asynccontextmanager
    async def open(self, *, resume: str | None = None) -> AsyncGenerator[Session, None]:
        self.resumes.append(resume)
        yield self.session


def per_input_token(usage: Usage) -> float:
    return usage.input_tokens / 1_000_000


class TestBudgetedSession:
    async def test_cost_accumulates_and_stamps_result(self) -> None:
        inner = FakeSession(
            [
                response_with_usage(Usage(input_tokens=1_000_000)),
                response_with_usage(Usage(input_tokens=1_000_000)),
            ]
        )
        conv = BudgetedSession(inner, usage_cost=per_input_token)

        first = await conv.send("one")
        assert first.result is not None
        assert first.result.total_cost_usd == pytest.approx(1.0)

        second = await conv.send("two")
        assert second.result is not None
        assert second.result.total_cost_usd == pytest.approx(2.0)
        assert conv.turns_usage.input_tokens == 2_000_000

    async def test_cumulative_usage_replaces_instead_of_adding(self) -> None:
        """Engines reporting session totals (Codex) compose cumulative metering."""
        inner = FakeSession(
            [
                response_with_usage(Usage(input_tokens=1_000_000)),
                response_with_usage(Usage(input_tokens=2_000_000)),  # running total
            ]
        )
        conv = BudgetedSession(inner, usage_cost=per_input_token, cumulative=True)

        await conv.send("one")
        second = await conv.send("two")
        assert second.result is not None
        assert second.result.total_cost_usd == pytest.approx(2.0)
        assert conv.turns_usage.input_tokens == 2_000_000

    async def test_budget_refuses_turn_after_crossing(self) -> None:
        inner = FakeSession([response_with_usage(Usage(input_tokens=1_000_000))] * 3)
        conv = BudgetedSession(inner, usage_cost=per_input_token, max_budget_usd=1.5)

        await conv.send("cost 1.0 — under budget")
        await conv.send("cost 2.0 — crosses budget mid-flight")

        with pytest.raises(BudgetExceededError, match="budget"):
            await conv.send("refused")
        assert len(inner.prompts) == 2

    async def test_usage_less_turn_leaves_cost_unknown(self) -> None:
        inner = FakeSession([response_with_usage(None)])
        conv = BudgetedSession(inner, usage_cost=per_input_token, max_budget_usd=1.0)

        response = await conv.send("one")
        assert response.result is not None
        assert response.result.total_cost_usd is None
        assert conv.cost_usd is None


class TestTimeoutSession:
    async def test_slow_turn_is_cancelled(self) -> None:
        inner = FakeSession([response_with_usage(None)], delay=10)
        conv = TimeoutSession(inner, seconds=0.05)

        with pytest.raises(TurnTimeoutError, match="wall-clock"):
            await conv.send("hi")

    async def test_fast_turn_passes_through(self) -> None:
        inner = FakeSession([response_with_usage(Usage(input_tokens=1))])
        conv = TimeoutSession(inner, seconds=5.0)

        response = await conv.send("hi")
        assert response.result is not None
        assert conv.id == "fake-1"


class TestSessionsWrappers:
    async def test_open_threads_resume_through_and_wraps(self) -> None:
        inner_session = FakeSession([])
        inner = FakeSessions(inner_session)
        wrapped = BudgetedSessions(
            TimeoutSessions(inner, seconds=1.0),
            usage_cost=per_input_token,
        )

        async with wrapped.open(resume="sess-9") as session:
            assert isinstance(session, BudgetedSession)
            assert isinstance(session.inner, TimeoutSession)
            assert session.id == "fake-1"
        assert inner.resumes == ["sess-9"]
