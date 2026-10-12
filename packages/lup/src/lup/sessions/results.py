"""What an ask returns: the answer, what it cost, and the attempts refused before it."""

from datetime import timedelta

from pydantic import JsonValue

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
