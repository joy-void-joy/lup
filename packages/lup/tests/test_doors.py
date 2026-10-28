"""The doors a module's method is reached through: what each puts on the method, and what each refuses as it's put on."""

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel

import lup
from lup.doors import (
    DoorError,
    Method,
    Observing,
    Refusing,
    RequestDoor,
    ToolDoor,
    ViewDoor,
    declared,
    opened,
    refuse_taken,
    served,
)
from lup.events import Launched, Publishing, Stopped, TurnEnded
from lup.publishing import Place, Refusal
from lup.tools.tool import Accepted

if TYPE_CHECKING:
    from collections.abc import Awaitable


class Asked(BaseModel):
    """What a method takes."""

    city: str


class Replied(BaseModel):
    """What a request replies."""

    weather: str


class Caller(BaseModel):
    """Someone a method is handed as who asks it: the library knows none of the environment's."""

    name: str


class Serving(BaseModel):
    """A class of methods, one behind each door."""

    seen: list[str] = []

    @lup.tool(reads=True)
    async def forecast(self, asked: Asked, by: Caller) -> str:
        """Forecast a city's weather.

        Read whole by the agent calling it.
        """
        return f"rain in {asked.city}, for {by.name}"

    @lup.request
    async def state(self, asked: Asked, by: Caller) -> Replied:
        """Say a city's weather, as a room asks it."""
        return Replied(weather=f"dry in {asked.city}, for {by.name}")

    @lup.on(Launched)
    @lup.on(Stopped)
    async def keep(self, event: Launched | Stopped) -> None:
        """Note each launch's opening and end."""
        self.seen.append(event.named())

    @lup.on(Publishing)
    async def refuse(self, event: Publishing) -> list[Refusal]:
        """Refuse every post."""
        del event
        return [Refusal(what="a post", place=Place(within="all of it"), steer="no")]


def test_each_method_says_its_doors_read_through_its_class() -> None:
    methods = served(Serving)
    assert list(methods) == ["forecast", "state", "keep", "refuse"]
    assert methods["forecast"].doors == [ToolDoor(reads=True)]
    assert methods["state"].doors == [RequestDoor()]
    assert methods["keep"].events() == [Stopped, Launched]
    assert methods["refuse"].doors == [Refusing()]
    assert isinstance(Serving.keep, Method)


def test_a_method_read_through_an_instance_is_called_as_any() -> None:
    serving = Serving()
    caller = Caller(name="kai")
    assert asyncio.run(serving.forecast(Asked(city="Oslo"), by=caller)) == (
        "rain in Oslo, for kai"
    )
    assert asyncio.run(serving.state(Asked(city="Rome"), by=caller)) == Replied(
        weather="dry in Rome, for kai"
    )
    asyncio.run(serving.keep(Launched()))
    asyncio.run(serving.keep(Stopped()))
    assert serving.seen == ["launched", "stopped"]


def test_a_tool_says_what_it_is_with_no_instance_and_hands_its_caller_on() -> None:
    [spec] = declared(Serving).values()
    assert (spec.name, spec.summary, spec.reads) == (
        "forecast",
        "Forecast a city's weather.",
        True,
    )
    tool = served(Serving)["forecast"].tool(Serving(), Caller(name="ana"))
    assert asyncio.run(tool.call({"city": "Lima"})) == Accepted(
        value=Asked(city="Lima"), answer="rain in Lima, for ana"
    )


def test_a_method_taking_who_asks_it_isnt_called_with_no_one() -> None:
    tool = served(Serving)["forecast"].tool(Serving())
    with pytest.raises(DoorError, match="`forecast` takes who asks it, `by`"):
        asyncio.run(tool.call({"city": "Lima"}))


def test_a_plain_function_s_tool_takes_no_caller() -> None:
    async def weather(asked: Asked, by: Caller) -> str:
        """Look a city up."""
        return f"{asked.city} {by.name}"

    with pytest.raises(DoorError, match="the tool `weather` takes `by`"):
        lup.tool(weather)


def test_a_method_takes_one_model_then_by() -> None:
    async def loose(self: Serving, asked: Asked, caller: Caller) -> str:
        """Look a city up."""
        return f"{asked.city} {caller.name}"

    with pytest.raises(DoorError, match="`loose` takes `asked`, `caller`"):
        lup.tool(loose)


def test_a_method_behind_a_door_is_async() -> None:
    def sync(self: Serving, event: Stopped) -> Awaitable[None]:
        """Not async."""
        return asyncio.sleep(0)

    with pytest.raises(
        DoorError, match="`sync` is reached through a door, so it's async"
    ):
        lup.on(Stopped)(sync)


def test_a_request_takes_a_model_and_replies_one() -> None:
    async def words(self: Serving, asked: Asked, by: Caller) -> str:
        """Say it in words."""
        return asked.city

    with pytest.raises(DoorError, match="the request `words` must take"):
        opened(words, RequestDoor())


def test_a_hook_takes_the_events_it_runs_at() -> None:
    async def keep(self: Serving, event: Stopped) -> None:
        """Keep."""

    stopping = opened(keep, Observing(event=Stopped))
    with pytest.raises(DoorError, match="runs at `Launched`, but takes `event`"):
        stopping.through(Observing(event=Launched))


def test_a_hook_at_publishing_answers_its_refusals_and_elsewhere_nothing() -> None:
    async def silent(self: Serving, event: Publishing) -> None:
        """Answer nothing."""

    async def refusing(self: Serving, event: TurnEnded) -> list[Refusal]:
        """Refuse a turn's end."""
        return []

    with pytest.raises(DoorError, match="returns its refusals"):
        opened(silent, Refusing())
    with pytest.raises(DoorError, match="returns its refusals"):
        opened(refusing, Observing(event=TurnEnded))


def test_a_hook_at_publishing_runs_at_nothing_else() -> None:
    async def both(self: Serving, event: Publishing | Stopped) -> list[Refusal]:
        """Refuse."""
        return []

    async def either(self: Serving, event: Publishing | Stopped) -> None:
        """Observe."""

    refusing = opened(both, Refusing())
    with pytest.raises(DoorError, match="`both` runs at `Publishing` beside another"):
        refusing.through(Observing(event=Stopped))
    observing = opened(either, Observing(event=Stopped))
    with pytest.raises(DoorError, match="`either` runs at `Publishing` beside another"):
        observing.through(Refusing())


def test_a_hook_runs_at_an_event_once() -> None:
    async def twice(self: Serving, event: Stopped) -> None:
        """Observe."""

    once = opened(twice, Observing(event=Stopped))
    with pytest.raises(DoorError, match="`twice` runs at `Stopped` already"):
        once.through(Observing(event=Stopped))


def test_one_method_is_reached_through_one_audience_s_doors() -> None:
    async def keep(self: Serving, event: Stopped) -> None:
        """Observe."""

    hooked = opened(keep, Observing(event=Stopped))
    with pytest.raises(DoorError, match="`keep` is a hook at `Stopped` already"):
        hooked.through(ToolDoor())


def test_a_door_reads_annotations_as_it_s_put_on() -> None:
    async def unnamed(self: Serving, asked: Asked, by: Caller) -> str:
        """Look a city up."""
        return asked.city

    def annotate(spelling: int) -> dict[str, object]:
        """Evaluate its annotations as one naming what its module imports under `TYPE_CHECKING` alone does."""
        del spelling
        message = "name 'Nobody' is not defined"
        raise NameError(message, name="Nobody")

    unnamed.__annotate__ = annotate
    with pytest.raises(DoorError, match="annotations name `Nobody`"):
        opened(unnamed, ToolDoor())


def test_a_method_isn_t_named_as_a_field() -> None:
    class Base(BaseModel):
        seen: str = ""

    class Shadowing(Base):
        pass

    with pytest.raises(DoorError, match="`Shadowing`'s method `seen` takes the name"):
        refuse_taken(Shadowing, "seen")


def test_a_view_says_where_its_placed_and_when_its_answered_again() -> None:
    class Views(BaseModel):
        @lup.view(
            place=lup.Drawer(letter="v", called="the conversation", colour="cyan"),
            watch=lup.Watch(on=[TurnEnded], longest=timedelta(minutes=1)),
        )
        async def conversation(self, viewed: lup.OfAgent) -> lup.Blocks:
            """The whole conversation."""
            return lup.Blocks(blocks=[lup.Line.of("1", viewed.session)])

    door = Views.conversation.viewing()
    assert door is not None
    assert isinstance(door.place, lup.Drawer)
    assert door.place.letter == "v"
    assert door.watch.on == [TurnEnded]
    answer = asyncio.run(
        Views().conversation(lup.OfAgent(runtime="claude", session="s1"))
    )
    assert answer.text() == "s1"


def test_a_view_takes_what_its_viewed_and_answers_blocks() -> None:
    async def said(self: Serving, viewed: Asked) -> str:
        """Words, not blocks."""
        return viewed.city

    async def shown(self: Serving, viewed: Asked) -> lup.Blocks:
        """Placed under an agent, but taking a city."""
        return lup.Blocks()

    async def bare(self: Serving, viewed: Asked) -> lup.Blocks:
        return lup.Blocks()

    with pytest.raises(DoorError, match="returns `str`"):
        opened(said, ViewDoor())
    placed = ViewDoor(place=lup.Drawer(letter="v", called="it", colour="cyan"))
    with pytest.raises(DoorError, match="takes the agent it's of"):
        opened(shown, placed)
    with pytest.raises(DoorError, match="takes the agent it's of"):
        opened(shown, ViewDoor(place=lup.Banner()))
    with pytest.raises(DoorError, match="needs a docstring"):
        opened(bare, ViewDoor())
