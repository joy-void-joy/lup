"""A typed function as a tool: its spec, and each call validated, reviewed, then run."""

import asyncio

import pytest
from pydantic import BaseModel

from lup.sessions.submission import Answer, End, GiveUp, KeepGoing, Toolbox
from lup.tools import Allow, Deny, Submit, lup_tool
from lup.tools.tool import Accepted, Refused, ToolError


class Query(BaseModel):
    city: str


class Weather(BaseModel):
    summary: str


NOWHERE = Query(city="")


@lup_tool
async def weather(query: Query) -> Weather:
    """Look up today's weather in a city."""
    return Weather(summary=f"sunny in {query.city}")


def test_a_tool_is_named_and_described_by_its_function() -> None:
    spec = weather.spec()
    assert spec.name == "weather"
    assert spec.description == "Look up today's weather in a city."
    assert spec.input_schema["required"] == ["city"]


def test_a_call_validates_then_runs() -> None:
    outcome = asyncio.run(weather.call({"city": "Paris"}))
    assert isinstance(outcome, Accepted)
    assert Weather.model_validate_json(outcome.answer).summary == "sunny in Paris"


def test_an_invalid_call_is_refused_with_every_error() -> None:
    outcome = asyncio.run(weather.call({"town": "Paris"}))
    assert isinstance(outcome, Refused)
    assert "city" in outcome.rejection.reason


def test_a_hook_denies_before_the_function_runs() -> None:
    async def no_paris(query: Query) -> Allow | Deny:
        return Deny(reason="not Paris") if query.city == "Paris" else Allow()

    guarded = weather.model_copy(update={"before": [no_paris]})
    denied = asyncio.run(guarded.call({"city": "Paris"}))
    assert isinstance(denied, Refused)
    assert denied.rejection.reason == "not Paris"
    assert isinstance(asyncio.run(guarded.call({"city": "Rome"})), Accepted)


def test_a_function_without_one_model_isnt_a_tool() -> None:
    async def two(a: Query, b: Query = NOWHERE) -> Weather:
        """Two inputs."""
        return Weather(summary="")

    with pytest.raises(ToolError, match="takes 2 parameters"):
        lup_tool(two)


def test_a_function_without_a_docstring_isnt_a_tool() -> None:
    async def bare(query: Query) -> Weather:
        return Weather(summary="")

    with pytest.raises(ToolError, match="docstring"):
        lup_tool(bare)


def test_a_typed_turn_ends_only_once_an_answer_is_accepted() -> None:
    toolbox = Toolbox(tools=[Submit(Query)], output="submit", attempts=3)
    assert isinstance(toolbox.end(), KeepGoing)
    refused = asyncio.run(toolbox.call("submit", {"town": "Rome"}))
    assert refused.error
    assert isinstance(toolbox.end(), KeepGoing)
    # Two refused endings and one rejection use the three attempts.
    assert isinstance(toolbox.end(), GiveUp)
    accepted = asyncio.run(toolbox.call("submit", {"city": "Rome"}))
    assert not accepted.error
    assert isinstance(toolbox.end(), End)
    assert toolbox.accepted() == Query(city="Rome")


def test_an_untyped_turn_may_always_end() -> None:
    assert isinstance(Toolbox(tools=[], attempts=3).end(), End)


def test_a_call_to_an_unknown_tool_says_which_exist() -> None:
    toolbox = Toolbox(tools=[weather], attempts=3)
    answer = asyncio.run(toolbox.call("forecast", {}))
    assert answer == Answer(
        text="There's no tool named forecast; the tools are: weather.", error=True
    )
