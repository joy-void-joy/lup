"""`ask` through the real layers, with the fake standing in for the runtime's adapter."""

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, overload, override

import pytest
from pydantic import BaseModel
from tenacity import stop_after_attempt, wait_none

from lup import (
    AgentUnavailableError,
    OutputMissingError,
    Recovery,
    SessionLayers,
    TurnResult,
    TurnTimeoutError,
    UsageLimitReachedError,
)
from lup.sessions.contract import Adapter, RawTurn, Seam, TurnRequest, seam
from lup.sessions.declaration import Asking, Declaration
from lup.sessions.surface import Agent
from lup.testing.fake import Submitting, UnscriptedAskError
from lup.tools import Allow, Deny, Submit

if TYPE_CHECKING:
    from pathlib import Path

    from lup.testing import FakeAgents


class Unreachable(Adapter):
    @override
    async def run(self, request: TurnRequest) -> RawTurn:
        message = "a test reached the runtime's own adapter"
        raise AssertionError(message)


class Probe(Declaration, Agent):
    """A declaration for no runtime: its asks run on whatever the seam chooses."""

    runtime = "probe"

    @overload
    async def ask(self, prompt: str, output: None = None) -> TurnResult[str]: ...

    @overload
    async def ask[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T]
    ) -> TurnResult[T]: ...

    @override
    async def ask[T: BaseModel](
        self, prompt: str, output: type[T] | Submit[T] | None = None
    ) -> TurnResult[T] | TurnResult[str]:
        return await Asking(declaration=self, runtime_adapter=Unreachable()).ask(
            prompt, output
        )


class Forecast(BaseModel):
    probability: float
    sources: list[str] = []


FAST = SessionLayers(recovery=Recovery(stop=stop_after_attempt(3), wait=wait_none()))


def probe(layers: SessionLayers = FAST) -> Probe:
    return Probe(model="test", layers=layers)


def test_a_typed_answer_comes_back_as_its_model(fake_agents: FakeAgents) -> None:
    fake_agents.answer(Forecast, Forecast(probability=0.3))
    result = asyncio.run(probe().ask("Will it rain?", Forecast))
    assert result.output == Forecast(probability=0.3)
    assert result.rejected == []
    [call] = fake_agents.calls
    assert call.prompt == "Will it rain?"
    assert call.output is Forecast


def test_an_untyped_answer_is_the_final_text(fake_agents: FakeAgents) -> None:
    fake_agents.answer_text("Bonjour")
    result = asyncio.run(probe().ask("Translate hello"))
    assert result.output == "Bonjour"


def test_a_rejected_submission_is_kept_beside_the_accepted_one(
    fake_agents: FakeAgents,
) -> None:
    fake_agents.reject_then(Forecast, {"probability": "high"}, Forecast(probability=0.9))
    result = asyncio.run(probe().ask("Will it rain?", Forecast))
    assert result.output.probability == 0.9
    [rejection] = result.rejected
    assert rejection.submitted == {"probability": "high"}
    assert "probability" in rejection.reason


def test_a_hook_on_the_output_tool_reviews_the_answer(fake_agents: FakeAgents) -> None:
    async def cites_sources(forecast: Forecast) -> Allow | Deny:
        if not forecast.sources:
            return Deny(reason="Cite at least one source.")
        return Allow()

    reviewed = Submit(Forecast, before=[cites_sources])
    fake_agents.reject_then(
        Forecast, {"probability": 0.5}, Forecast(probability=0.5, sources=["met office"])
    )
    result = asyncio.run(probe().ask("Will it rain?", reviewed))
    assert result.output.sources == ["met office"]
    assert [each.reason for each in result.rejected] == ["Cite at least one source."]


def test_no_accepted_answer_within_the_attempts_raises_with_every_rejection(
    fake_agents: FakeAgents,
) -> None:
    fake_agents.queue(Forecast, Submitting(submissions=[{"probability": "x"}] * 3))
    with pytest.raises(OutputMissingError) as raised:
        asyncio.run(probe().ask("Will it rain?", Forecast))
    assert len(raised.value.rejected) == 3


def test_an_unscripted_ask_names_its_model_and_prompt(fake_agents: FakeAgents) -> None:
    with pytest.raises(UnscriptedAskError, match=r"Forecast.*Will it rain"):
        asyncio.run(probe().ask("Will it rain?", Forecast))


def test_an_unavailable_runtime_is_retried(fake_agents: FakeAgents) -> None:
    fake_agents.fail(Forecast, AgentUnavailableError("overloaded"))
    fake_agents.answer(Forecast, Forecast(probability=0.1))
    result = asyncio.run(probe().ask("Will it rain?", Forecast))
    assert result.output.probability == 0.1
    assert len(fake_agents.calls) == 2


def test_other_errors_are_not_retried(fake_agents: FakeAgents) -> None:
    fake_agents.fail(None, UsageLimitReachedError("spent"))
    with pytest.raises(UsageLimitReachedError):
        asyncio.run(probe().ask("hello"))
    assert len(fake_agents.calls) == 1


def test_recovery_gives_up_after_its_attempts(fake_agents: FakeAgents) -> None:
    for _ in range(3):
        fake_agents.fail(None, AgentUnavailableError("overloaded"))
    with pytest.raises(AgentUnavailableError):
        asyncio.run(probe().ask("hello"))
    assert len(fake_agents.calls) == 3


class Hanging(Seam, Adapter):
    @override
    def adapter(self, declaration: Declaration) -> Adapter:
        return self

    @override
    async def run(self, request: TurnRequest) -> RawTurn:
        await asyncio.Event().wait()
        message = "unreachable"
        raise AssertionError(message)


def test_the_timeout_interrupts_the_turn() -> None:
    token = seam.set(Hanging())
    try:
        with pytest.raises(TurnTimeoutError):
            asyncio.run(probe(SessionLayers(timeout=timedelta(0))).ask("hello"))
    finally:
        seam.reset(token)


def test_the_trace_keeps_each_ask_whole(fake_agents: FakeAgents, tmp_path: Path) -> None:
    trace = tmp_path / "traces" / "calls.jsonl"
    layers = FAST.model_copy(update={"trace": trace})
    fake_agents.reject_then(Forecast, {"probability": "x"}, Forecast(probability=0.4))
    fake_agents.fail(None, UsageLimitReachedError("spent"))
    asyncio.run(probe(layers).ask("Will it rain?", Forecast))
    with pytest.raises(UsageLimitReachedError):
        asyncio.run(probe(layers).ask("hello"))
    answered, failed = [json.loads(line) for line in trace.read_text().splitlines()]
    assert answered["prompt"] == "Will it rain?"
    assert answered["output"] == {"probability": 0.4, "sources": []}
    assert len(answered["rejected"]) == 1
    assert failed["error"] == "UsageLimitReachedError: spent"
    assert failed["output"] is None
