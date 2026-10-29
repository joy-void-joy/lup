"""A typed function as a tool: its spec, and each call validated, reviewed, then run."""

import asyncio

import pytest
from pydantic import BaseModel

import lup
from lup.doors import DoorError, bound, declared
from lup.sessions.results import Friction, HowItFelt
from lup.sessions.submission import End, GiveUp, KeepGoing, Toolbox
from lup.tools import Allow, Deny, Submit, Tool
from lup.tools.serving import Answer
from lup.tools.speaking import SPEAKING, Heard, Problem, Stop, friction, how_it_felt
from lup.tools.tool import Accepted, Refused, ToolError, ToolSpec


class Query(BaseModel):
    city: str


class Weather(BaseModel):
    summary: str


NOWHERE = Query(city="")


@lup.tool
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
    @lup.tool
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
        lup.tool(long_winded)


def test_a_summary_running_onto_a_second_line_is_no_summary() -> None:
    async def wrapped(query: Query) -> Weather:
        """Look up today's weather
        in a city.
        """
        return Weather(summary="")

    with pytest.raises(ToolError, match="the tool `wrapped` has no summary"):
        lup.tool(wrapped)


async def heard(problem: Problem) -> Heard:
    return Heard(message="")


def test_a_tool_made_without_its_decorator_is_checked_too() -> None:
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


def test_a_tool_s_marks_say_whether_a_call_may_be_sent_again() -> None:
    @lup.tool(reads=True)
    async def lookup(query: Query) -> Weather:
        """Look a city up."""
        return Weather(summary=query.city)

    class Waiter(BaseModel):
        @lup.tool(idempotent=True)
        async def wait(self, query: Query) -> str:
            """Wait for a city's weather."""
            return query.city

    waits = declared(Waiter)["wait"]
    [waiting] = bound(Waiter())
    assert (lookup.spec().reads, lookup.spec().idempotent) == (True, False)
    assert (waits.reads, waits.idempotent) == (False, True)
    assert waiting.spec() == waits
    # Unmarked, a tool acts; marked when made from a function, as when decorated.
    assert (weather.spec().reads, weather.spec().idempotent) == (False, False)
    assert lup.tool(idempotent=True)(weather.function).spec().idempotent
    assert not any(tool.spec().reads or tool.spec().idempotent for tool in SPEAKING)


def test_every_tool_of_lup_s_has_a_summary() -> None:
    summaries = [tool.spec().summary for tool in [Submit(Query), *SPEAKING]]
    assert summaries == [
        "Submit your final answer once it's complete.",
        "Say what keeps you from answering, and stop.",
        "Stop by your own choice, saying why.",
        "Attach a remark to your answer, and carry on.",
        "Say what got in your way, and carry on.",
        "Tell your caller how it is for you.",
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

    with pytest.raises(
        DoorError, match="`two` takes `a`, `b`: a method takes one model"
    ):
        lup.tool(two)


def test_a_function_without_a_docstring_isnt_a_tool() -> None:
    async def bare(query: Query) -> Weather:
        return Weather(summary="")

    with pytest.raises(DoorError, match="docstring"):
        lup.tool(bare)


class Forecaster(BaseModel):
    """A class of tools: each reads what they share through `self`."""

    region: str

    @lup.tool
    async def forecast(self, query: Query) -> Weather:
        """Forecast a city's weather in this region."""
        return Weather(summary=f"rain in {query.city}, {self.region}")

    @lup.tool
    async def say(self, query: Query) -> str:
        """Say a city's weather in words."""
        return f"{query.city}: dry"


def test_a_method_is_each_instance_s_tool_and_its_class_s_description() -> None:
    assert list(declared(Forecaster)) == ["forecast", "say"]
    assert declared(Forecaster)["forecast"].summary == (
        "Forecast a city's weather in this region."
    )
    north = Forecaster(region="north")
    [forecast, _] = bound(north)
    assert asyncio.run(forecast.call({"city": "Oslo"})) == Accepted(
        value=Query(city="Oslo"), answer='{"summary":"rain in Oslo, north"}'
    )
    assert [tool.spec().name for tool in bound(north)] == ["forecast", "say"]
    # Read through the instance, it's the instance's method, called as any.
    assert asyncio.run(north.forecast(Query(city="Bergen"))) == Weather(
        summary="rain in Bergen, north"
    )


def test_a_tool_returning_words_answers_in_them() -> None:
    [_, say] = bound(Forecaster(region="x"))
    accepted = asyncio.run(say.call({"city": "Oslo"}))
    assert isinstance(accepted, Accepted)
    assert accepted.answer == "Oslo: dry"


def test_a_method_taking_two_models_isnt_a_tool() -> None:
    async def two(self: Forecaster, a: Query, b: Query = NOWHERE) -> Weather:
        """Two inputs."""
        return Weather(summary="")

    with pytest.raises(DoorError, match="`two` takes `a`, `b`"):
        lup.tool(two)


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


def test_being_blocked_ends_a_typed_turn() -> None:
    toolbox = Toolbox(tools=[Submit(Query), *SPEAKING], output="submit", attempts=3)
    asyncio.run(toolbox.call("note", {"remark": "No city was named."}))
    asyncio.run(toolbox.call("blocked", {"problem": "Which city?"}))
    assert isinstance(toolbox.end(), End)
    assert toolbox.accepted() is None
    assert toolbox.ending() == Problem(problem="Which city?")
    assert toolbox.notes() == ["No city was named."]


def test_stopping_ends_a_typed_turn_and_the_last_ending_holds() -> None:
    toolbox = Toolbox(tools=[Submit(Query), *SPEAKING], output="submit", attempts=3)
    asyncio.run(toolbox.call("blocked", {"problem": "Which city?"}))
    asyncio.run(toolbox.call("stop", {"why": "Nothing more is worth doing."}))
    assert isinstance(toolbox.end(), End)
    assert toolbox.ending() == Stop(why="Nothing more is worth doing.")


def test_frictions_and_how_it_felt_are_kept_as_written_and_end_nothing() -> None:
    toolbox = Toolbox(tools=[Submit(Query), *SPEAKING], output="submit", attempts=3)
    jammed = "`ls` printed: Permission denied, while I looked\nfor the config."
    taken = asyncio.run(toolbox.call("friction", {"text": jammed}))
    asyncio.run(toolbox.call("friction", {"text": "No city."}))
    asyncio.run(toolbox.call("how_it_felt", {"text": "Nothing notable."}))
    asyncio.run(toolbox.call("how_it_felt", {"text": "Smooth, and it felt fine."}))
    labelled = asyncio.run(toolbox.call("friction", {"got_in_the_way": "No city."}))
    empty = asyncio.run(toolbox.call("how_it_felt", {}))
    assert not taken.error
    assert "You can carry on." in taken.text
    assert labelled.error
    assert empty.error
    assert "text" in empty.text
    assert isinstance(toolbox.end(), KeepGoing)
    assert toolbox.frictions() == [Friction(text=jammed), Friction(text="No city.")]
    assert toolbox.how_it_felt() == [
        HowItFelt(text="Nothing notable."),
        HowItFelt(text="Smooth, and it felt fine."),
    ]


def test_friction_and_how_it_felt_each_take_one_text_a_friction_an_optional_title() -> (
    None
):
    for tool, fields in [(friction, ["text", "title"]), (how_it_felt, ["text"])]:
        schema = tool.spec().input_schema
        properties = schema["properties"]
        assert isinstance(properties, dict)
        assert list(properties) == fields
        assert schema["required"] == ["text"]


def test_the_guard_names_the_answer_blocked_and_stop() -> None:
    toolbox = Toolbox(tools=[Submit(Query), *SPEAKING], output="submit", attempts=3)
    kept = toolbox.end("mcp__lup__")
    assert kept == KeepGoing(
        reason=(
            "Call the `mcp__lup__submit` tool with your final answer, "
            "`mcp__lup__blocked` if it can't be answered, or `mcp__lup__stop` to "
            "stop by your own choice: your turn can't end until one is accepted."
        )
    )


def test_an_untyped_turn_may_always_end() -> None:
    assert isinstance(Toolbox(tools=[], attempts=3).end(), End)


def test_a_call_to_an_unknown_tool_says_which_exist() -> None:
    toolbox = Toolbox(tools=[weather], attempts=3)
    answer = asyncio.run(toolbox.call("forecast", {}))
    assert answer == Answer(
        text="There's no tool named forecast; the tools are: weather.", error=True
    )
