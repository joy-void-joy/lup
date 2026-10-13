"""A typed function as a tool: its spec, and each call validated, reviewed, then run."""

import asyncio

import pytest
from pydantic import BaseModel

from lup.sessions.submission import End, GiveUp, KeepGoing, Toolbox
from lup.tools import Allow, Deny, Submit, Tool, lup_tool
from lup.tools.serving import Answer
from lup.tools.speaking import Heard, Problem, note, report
from lup.tools.tool import Accepted, Refused, ToolError, ToolSpec


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
    assert spec.summary == "Look up today's weather in a city."
    assert spec.input_schema["required"] == ["city"]


def test_a_tool_s_summary_is_its_docstring_s_first_line_and_the_rest_stays() -> None:
    @lup_tool
    async def forecast(query: Query) -> Weather:
        """Forecast a city's weather for the week.

        Each day's summary, from the national service, as it published it last.
        """
        return Weather(summary="")

    spec = forecast.spec()
    assert spec.summary == "Forecast a city's weather for the week."
    assert spec.description == (
        "Forecast a city's weather for the week.\n\n"
        "Each day's summary, from the national service, as it published it last."
    )


def test_a_summary_past_fifty_characters_is_refused_naming_the_tool() -> None:
    async def long_winded(query: Query) -> Weather:
        """Look up today's weather in a city, wherever it is in the world."""
        return Weather(summary="")

    with pytest.raises(
        ToolError, match=r"`long_winded`'s summary.* 63 characters, past 50"
    ):
        lup_tool(long_winded)


def test_a_summary_running_onto_a_second_line_is_no_summary() -> None:
    async def wrapped(query: Query) -> Weather:
        """Look up today's weather
        in a city.
        """
        return Weather(summary="")

    with pytest.raises(ToolError, match="the tool `wrapped` has no summary"):
        lup_tool(wrapped)


async def heard(problem: Problem) -> Heard:
    return Heard(message="")


def test_a_tool_made_without_lup_tool_is_checked_too() -> None:
    with pytest.raises(ToolError, match="the tool `quiet` has no summary"):
        Tool[Problem, Heard](
            name="quiet", description="", input=Problem, function=heard
        )
    with pytest.raises(ToolError, match="the tool `loud`'s summary"):
        Tool[Problem, Heard](
            name="loud", description="x" * 51, input=Problem, function=heard
        )
    with pytest.raises(ToolError, match="the tool `spec` has no summary"):
        ToolSpec(name="spec", description="\n", input_schema={})


def test_every_tool_of_lup_s_has_a_summary() -> None:
    summaries = [tool.spec().summary for tool in [Submit(Query), report, note]]
    assert summaries == [
        "Submit your final answer once it's complete.",
        "Stop without an answer and say what's wrong.",
        "Attach a remark to your answer, and carry on.",
    ]


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


def test_a_reported_problem_ends_a_typed_turn() -> None:
    toolbox = Toolbox(tools=[Submit(Query), report, note], output="submit", attempts=3)
    asyncio.run(toolbox.call("note", {"remark": "No city was named."}))
    asyncio.run(toolbox.call("report", {"problem": "Which city?"}))
    assert isinstance(toolbox.end(), End)
    assert toolbox.accepted() is None
    assert toolbox.reported() == "Which city?"
    assert toolbox.notes() == ["No city was named."]


def test_an_untyped_turn_may_always_end() -> None:
    assert isinstance(Toolbox(tools=[], attempts=3).end(), End)


def test_a_call_to_an_unknown_tool_says_which_exist() -> None:
    toolbox = Toolbox(tools=[weather], attempts=3)
    answer = asyncio.run(toolbox.call("forecast", {}))
    assert answer == Answer(
        text="There's no tool named forecast; the tools are: weather.", error=True
    )
