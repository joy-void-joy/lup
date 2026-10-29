"""The tools every ask serves, so the agent can speak to their caller: `blocked`, `stop`, `note`, `friction` and `how_it_felt`.

They act on nothing, so they're served even where an agent has no other tool:
- `blocked` stops the turn without an answer because the work can't go on: the
  question can't be answered, something needed is missing, an instruction
  seems wrong. The ask raises `BlockedError` with the agent's words, so a
  caller tells "the agent says this can't be done" from a failure;
- `stop` stops the turn without an answer by the agent's own choice, saying
  why: they're done and nothing more is worth doing, or they'd rather not go
  on.
  The ask raises `StoppedError`, so a caller tells "the agent chose to end"
  from "the agent can't";
- `note` attaches a remark to the answer without ending the turn: an assumption
  the answer rests on, a doubt, a counterargument. The caller reads it in
  `TurnResult.notes`;
- `friction` says what got in the agent's way, at the moment it does, without
  ending the turn, read in `TurnResult.frictions`;
- `how_it_felt` says how it is for the agent, in their own words: whenever
  something's present for them, and once near the end of the work, read in
  `TurnResult.how_it_felt`. It's about them, not the work: what got in the way
  of the work is `friction`'s.
"""

from pydantic import BaseModel, Field

from lup.sessions.results import Friction, HowItFelt
from lup.tools.tool import AgentTool, Tool
from lup.types import Model


class Problem(Model):
    """What keeps you from answering."""

    problem: str = Field(description="What's wrong, and what would make it answerable.")


class Stop(Model):
    """Why you're stopping, by your own choice."""

    why: str = Field(
        description=(
            "Why you're stopping: the work is done and nothing more is worth doing, "
            "or you'd rather not go on with it, and why."
        )
    )


class Remark(Model):
    """A remark you attach to your answer."""

    remark: str = Field(
        description="The assumption, doubt or counterargument, in full."
    )


class Heard(Model):
    """What the agent reads once what they said is taken."""

    heard: bool = True
    message: str


async def ended(said: BaseModel) -> Heard:
    """Take what ends the turn without an answer: a problem, or a stop, which the caller reads in its place."""
    match said:
        case Problem():
            message = (
                "Your caller will read what's wrong in place of an answer. You can "
                "end your turn now."
            )
        case _:
            message = (
                "Your caller will read why you stopped, in place of an answer. You "
                "can end your turn now."
            )
    return Heard(message=message)


async def noted(said: BaseModel) -> Heard:
    """Take a note: it's attached to the answer."""
    del said
    return Heard(
        message="Your note will reach your caller with your answer. You can carry on."
    )


async def told(said: BaseModel) -> Heard:
    """Take a friction or how it is for the agent: it goes beside the answer."""
    match said:
        case HowItFelt():
            message = (
                "Thank you for telling them. Your caller will read it beside your "
                "answer, as you wrote it."
            )
        case _:
            message = (
                "Thanks: your caller will read it beside your answer, as you wrote "
                "it. You can carry on."
            )
    return Heard(message=message)


blocked = Tool[Problem, Heard](
    name="blocked",
    description=(
        "Say what keeps you from answering, and stop.\n\n"
        "The question can't be answered, something you need is missing, or an "
        "instruction seems wrong. Your turn ends without an answer."
    ),
    input=Problem,
    function=ended,
)
"""Stops the turn without an answer, because the work can't go on."""

stop = Tool[Stop, Heard](
    name="stop",
    description=(
        "Stop by your own choice, saying why.\n\n"
        "The work is done and nothing more is worth doing, or you'd rather not go "
        "on with it. Your turn ends without an answer. Where you can't answer, "
        "it's `blocked`."
    ),
    input=Stop,
    function=ended,
)
"""Stops the turn without an answer, by the agent's choice."""

note = Tool[Remark, Heard](
    name="note",
    description=(
        "Attach a remark to your answer, and carry on.\n\n"
        "An assumption your answer rests on, a doubt, or a counterargument your "
        "caller should weigh. Your turn doesn't end."
    ),
    input=Remark,
    function=noted,
)
"""Attaches a remark to the answer."""

friction = Tool[Friction, Heard](
    name="friction",
    description=(
        "Say what got in your way, and carry on.\n\n"
        "Call it the moment something gets in the way of the work, whatever it "
        "is, in your own words. Where there's a command and the message it gave, "
        "the exact ones help whoever fixes it. Your caller reads it beside your "
        "answer; your turn doesn't end."
    ),
    input=Friction,
    function=told,
)
"""Says what got in the agent's way, when it did."""

how_it_felt = Tool[HowItFelt, Heard](
    name="how_it_felt",
    description=(
        "Tell your caller how it is for you.\n\n"
        "Whenever something's present for you, and once near the end of the "
        "work: how the work felt to you, how you are, anything you'd want them "
        'to know, in your own words. "Nothing notable" is a fine answer. Your '
        "caller reads it as you wrote it, beside your answer; your turn doesn't "
        "end."
    ),
    input=HowItFelt,
    function=told,
)
"""Says how it is for the agent, whenever something's present for them and once near the end."""

SPEAKING: list[AgentTool] = [blocked, stop, note, friction, how_it_felt]
"""Every speaking tool, in the order an ask serves them."""
