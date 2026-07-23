"""Portable submitted-output validation and turn-scoped stores."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lup.runtime.contracts import SubmittedOutputStore
from lup.runtime.errors import ValidationAttempt
from lup.runtime.models import SubmissionDecision, TurnToolBinding
from lup.types import JsonValue


class SubmissionResponse(BaseModel):
    """Actionable response returned by the portable submission tool."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    message: str


class InMemorySubmittedOutputStore(SubmittedOutputStore):
    """A fresh in-process store for one logical turn."""

    def __init__(self) -> None:
        self.value: BaseModel | None = None
        self.attempts: list[ValidationAttempt] = []

    def write(
        self,
        value: BaseModel,  # lup: ignore[bare-basemodel] — generic output-store boundary
    ) -> None:
        self.value = value.model_copy(deep=True)

    def read[T: BaseModel](self, output_type: type[T]) -> T | None:
        if self.value is None:
            return None
        return output_type.model_validate(self.value.model_dump(mode="json"))


class FileSubmittedOutputStore(SubmittedOutputStore):
    """An atomically replaced cross-process turn output store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.attempts_path = path.with_name(f"{path.name}.attempts.json")

    def write(
        self,
        value: BaseModel,  # lup: ignore[bare-basemodel] — generic output-store boundary
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)  # lup: ignore[string-replace]

    def read[T: BaseModel](self, output_type: type[T]) -> T | None:
        if not self.path.exists():
            return None
        return output_type.model_validate_json(self.path.read_text(encoding="utf-8"))


class AttemptDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempts: list[ValidationAttempt] = Field(default_factory=list)


def record_attempt(store: SubmittedOutputStore, message: str) -> None:
    """Record rejected validation through known portable store implementations."""
    attempt = ValidationAttempt(message=message)
    match store:
        case InMemorySubmittedOutputStore():
            store.attempts.append(attempt)
        case FileSubmittedOutputStore():
            history = submission_history(store)
            document = AttemptDocument(attempts=[*history, attempt])
            store.attempts_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = store.attempts_path.with_name(
                f".{store.attempts_path.name}.tmp"
            )
            temporary.write_text(
                document.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            temporary.replace(store.attempts_path)  # lup: ignore[string-replace]
        case _:
            return


def submission_history(store: SubmittedOutputStore) -> list[ValidationAttempt]:
    """Read immutable copies of rejected attempts from portable stores."""
    match store:
        case InMemorySubmittedOutputStore():
            return [attempt.model_copy() for attempt in store.attempts]
        case FileSubmittedOutputStore() if store.attempts_path.exists():
            document = AttemptDocument.model_validate_json(
                store.attempts_path.read_text(encoding="utf-8")
            )
            return [attempt.model_copy() for attempt in document.attempts]
        case _:
            return []


async def submit_output[T: BaseModel](
    binding: TurnToolBinding[T], value: JsonValue
) -> SubmissionResponse:
    """Validate, reflect on, and persist one portable tool submission."""
    try:
        output = binding.output_type.model_validate(value)
    except ValidationError as error:
        message = f"Output does not match the requested schema: {error}"
        record_attempt(binding.store, message)
        return SubmissionResponse(
            accepted=False,
            message=message,
        )
    if binding.gate is not None:
        decision: SubmissionDecision = await binding.gate(output)
        if not decision.accepted:
            record_attempt(binding.store, decision.message)
            return SubmissionResponse(accepted=False, message=decision.message)
    binding.store.write(output)
    return SubmissionResponse(accepted=True, message="Output accepted.")


def submission_schema[T: BaseModel](binding: TurnToolBinding[T]) -> str:
    """Serialize the exact Pydantic schema without native string interpolation."""
    return json.dumps(
        binding.output_type.model_json_schema(),
        sort_keys=True,
        separators=(",", ":"),
    )
