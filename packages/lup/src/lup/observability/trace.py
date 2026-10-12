"""One record per ask, kept in a JSON Lines file when the declaration's trace layer names one.

A record is derived from the ask's result, or its error, and its request, so the
record and the result can't disagree. Everything is kept in full: the prompt,
the system prompt, the answer and every rejected attempt.
"""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, JsonValue

from lup.sessions.errors import OutputMissingError, ProblemReportedError
from lup.sessions.results import Rejection, TurnResult, Usage
from lup.types import Model

if TYPE_CHECKING:
    from pathlib import Path


class CallRecord(Model):
    """What one ask was, and what came of it."""

    runtime: str
    model: str
    started_at: datetime
    duration: timedelta
    prompt: str
    system_prompt: str | None
    output: JsonValue = None
    """The answer: the output model as JSON, or the text; none where the ask failed."""
    error: str | None = None
    """The error's type and message, where the ask failed."""
    rejected: list[Rejection] = []
    notes: list[str] = []
    """The remarks the agent attached, answering or reporting a problem."""
    usage: Usage | None = None
    """None where the ask failed before the runtime reported any."""

    def append(self, path: Path) -> None:
        """Append this record to the trace at `path`, as one JSON line."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as trace:
            trace.write(self.model_dump_json() + "\n")


class Kept(Model):
    """What a failed ask's record keeps beside its error."""

    rejected: list[Rejection] = []
    notes: list[str] = []


class Answered(Model):
    """The answer half of a record, read off the ask's result."""

    output: JsonValue
    """The output model as JSON, or the text."""
    usage: Usage
    duration: timedelta
    rejected: list[Rejection]
    notes: list[str]

    @classmethod
    def of[T: BaseModel | str](cls, result: TurnResult[T]) -> Answered:
        """Read the answer half off `result`."""
        output = result.output
        return cls(
            output=output if isinstance(output, str) else output.model_dump(mode="json"),
            usage=result.usage,
            duration=result.duration,
            rejected=result.rejected,
            notes=result.notes,
        )


class Asked(Model):
    """The request half of a record: who was asked what, and when."""

    runtime: str
    model: str
    system_prompt: str | None
    prompt: str
    started_at: datetime

    def answered(self, answer: Answered) -> CallRecord:
        """Return the record of this ask, answered."""
        return CallRecord(
            runtime=self.runtime,
            model=self.model,
            started_at=self.started_at,
            duration=answer.duration,
            prompt=self.prompt,
            system_prompt=self.system_prompt,
            output=answer.output,
            rejected=answer.rejected,
            notes=answer.notes,
            usage=answer.usage,
        )

    def failed(self, error: Exception, duration: timedelta) -> CallRecord:
        """Return the record of this ask failing with `error` after `duration`.

        A reported problem keeps the notes the agent attached before reporting, and
        a missing answer every rejected attempt.
        """
        match error:
            case ProblemReportedError(notes=notes):
                kept = Kept(notes=notes)
            case OutputMissingError(rejected=rejected):
                kept = Kept(rejected=rejected)
            case _:
                kept = Kept()
        return CallRecord(
            runtime=self.runtime,
            model=self.model,
            started_at=self.started_at,
            duration=duration,
            prompt=self.prompt,
            system_prompt=self.system_prompt,
            error=f"{type(error).__name__}: {error}",
            rejected=kept.rejected,
            notes=kept.notes,
        )
