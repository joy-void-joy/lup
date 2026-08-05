"""Typed errors for unsuccessful turns and invalid session transitions."""

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field

from lup.runtime.models import AnyTurnBlock, TurnIdentifiers
from lup.types import Usage


class ValidationAttempt(BaseModel):
    """One rejected structured-output submission."""

    model_config = ConfigDict(frozen=True)

    message: str


class TurnFailure(BaseModel):
    """Partial evidence available when a logical turn fails."""

    model_config = ConfigDict(frozen=True)

    message: str
    blocks: list[AnyTurnBlock] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    duration: timedelta = timedelta()
    identifiers: TurnIdentifiers | None = None
    validation_history: list[ValidationAttempt] = Field(default_factory=list)


class TurnError(Exception):
    """Base for failures carrying complete available partial evidence."""

    def __init__(self, failure: TurnFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class ProviderTurnError(TurnError):
    """The provider rejected or failed a turn."""


class TurnTimeoutError(TurnError):
    """The whole logical turn exceeded its deadline."""


class BudgetExceededError(TurnError):
    """The whole logical turn exhausted its configured budget."""


class TurnInterruptedError(TurnError):
    """The active turn ended because interruption was requested."""


class TurnAbortedError(TurnError):
    """The session closed before the active turn completed."""


class StructuredOutputError(TurnError):
    """A required valid submission was not produced."""


class TurnAlreadyActiveError(RuntimeError):
    """A session was asked to start a second concurrent turn."""


class DeltaStreamingDisabled(RuntimeError):
    """A live view was asked of a session built without partial streaming.

    Raised rather than yielding a delta-free stream, because a stream that
    is quiet because nothing was configured looks exactly like one that is
    quiet because nothing happened.
    """
