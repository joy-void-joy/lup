"""What an ask returns: the answer, what it cost, the attempts refused before it, and what the agent said beside it.

`Concern` and `HowItFelt` are the inputs of the `concern` and `how_it_felt`
tools (`lup.tools.speaking`) as much as part of the result, so the caller reads
them as the agent wrote them; they live here because the tools' module builds on
this one. Each is one text in the agent's own words, never a form of labelled
parts: what's present for an agent at the moment isn't shaped like one, and a
form shapes the answer it asks for. A concern may carry a short title beside
it, naming it where concerns are listed a line each.
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


class Concern(Model):
    """Something worth keeping an eye on, the moment it came up, in your own words."""

    text: str = Field(description="In your own words: a line is enough.")
    title: str = Field(
        default="",
        description=(
            "A few words naming it, which a list of concerns shows a line each: "
            "`the gate hangs on a fresh worktree`. Left out, its first line."
        ),
    )


class HowItFelt(Model):
    """How it is for you, in your own words."""

    text: str = Field(description="In your own words.")


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
    """The remarks the agent attached to their answer, oldest first."""
    concerns: list[Concern] = []
    """What the agent found worth keeping an eye on, what got in their way among
    it, each when it came up, oldest first."""
    how_it_felt: list[HowItFelt] = []
    """Each time the agent said how it was for them, oldest first."""
