"""What an ask returns: the answer, what it cost, the attempts refused before it, and what the agent said beside it.

`Friction` and `HowItWent` are the inputs of the `friction` and `how_it_went`
tools (`lup.tools.speaking`) as much as part of the result, so the caller reads
them as the agent wrote them; they live here because the tools' module builds on
this one.
"""

from datetime import timedelta

from pydantic import Field, JsonValue

from lup.types import Model


class Usage(Model):
    """The tokens one ask used, and its cost where the runtime reports it."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    """None where the runtime reports tokens only."""


class Rejection(Model):
    """One refused submission: what the agent submitted, and why it was refused.

    `submitted` is the arguments as the agent sent them, whether or not they parse
    as the output model.
    """

    submitted: JsonValue
    reason: str


class Friction(Model):
    """What got in the agent's way, at the moment it did."""

    got_in_the_way: str = Field(
        description=(
            "What got in the way, in your words: the exact command and the message "
            "it gave, where there is one."
        )
    )
    trying: str = Field(default="", description="What you were trying to do.")
    would_change: str = Field(
        default="", description="What you'd change so it doesn't happen again."
    )


class HowItWent(Model):
    """How a piece of work went as a whole, as openly as the agent likes; every field left out says nothing was notable."""

    got_in_the_way: str = Field(
        default="",
        description="What got in the way: the exact command and message where there's one.",
    )
    smooth: str = Field(default="", description="What was smooth.")
    would_change: str = Field(default="", description="What you'd change.")
    felt: str = Field(default="", description="How it felt.")


class TurnResult[T](Model):
    """One ask's answer.

    `output` is an instance of the output model for a typed ask, or the final
    message's text for an untyped one.
    """

    output: T
    usage: Usage
    duration: timedelta
    session_id: str
    rejected: list[Rejection] = []
    """The submissions refused before the accepted one, oldest first."""
    notes: list[str] = []
    """The remarks the agent attached to its answer, oldest first."""
    frictions: list[Friction] = []
    """What got in the agent's way, each when it did, oldest first."""
    how_it_went: HowItWent | None = None
    """How the agent said the work went, where it said; the last, if it said twice."""
