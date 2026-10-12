"""The tools every ask serves, so the agent can speak to its caller: `report` and `note`.

They act on nothing, so they're served even where an agent has no other tool:
- `report` stops the turn without an answer and says what's wrong: the question
  can't be answered, something needed is missing, an instruction seems wrong.
  The ask raises `ProblemReportedError` with the agent's words, so a caller tells
  "the agent says this can't be done" from a failure;
- `note` attaches a remark to the answer without ending the turn: an assumption
  the answer rests on, a doubt, a counterargument. The caller reads it in
  `TurnResult.notes`.
"""

from pydantic import BaseModel, Field

from lup.tools.tool import Tool
from lup.types import Model


class Problem(Model):
    """What the agent reports instead of an answer."""

    problem: str = Field(description="What's wrong, and what would make it answerable.")


class Remark(Model):
    """A remark the agent attaches to its answer."""

    remark: str = Field(description="The assumption, doubt or counterargument, in full.")


class Heard(Model):
    """What the agent reads when its report or note is taken."""

    heard: bool = True
    message: str


async def reported(said: BaseModel) -> Heard:
    """Take a report: the turn ends without an answer."""
    del said
    return Heard(message="Your report is taken. End your turn.")


async def noted(said: BaseModel) -> Heard:
    """Take a note: it's attached to the answer."""
    del said
    return Heard(message="Your note is attached to your answer. Carry on.")


report = Tool[Problem, Heard](
    name="report",
    description=(
        "Stop without an answer and say what's wrong: the question can't be answered, "
        "something you need is missing, or an instruction seems wrong. Your turn ends."
    ),
    input=Problem,
    function=reported,
)
"""Stops the turn without an answer, saying why."""

note = Tool[Remark, Heard](
    name="note",
    description=(
        "Attach a remark to your answer without ending your turn: an assumption it "
        "rests on, a doubt, or a counterargument your caller should weigh."
    ),
    input=Remark,
    function=noted,
)
"""Attaches a remark to the answer."""
