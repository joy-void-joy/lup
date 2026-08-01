"""Immutable semantic values shared by all runtime implementations."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Literal, overload

from pydantic import BaseModel, ConfigDict, Field

from lup.runtime.contracts import (
    EventStream,
    ForkSession,
    Interrupt,
    Session,
    Steer,
    SubmittedOutputStore,
    Turn,
)
from lup.types import JsonObject, Usage

FROZEN = ConfigDict(frozen=True)
FROZEN_ARBITRARY = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class SessionId(BaseModel):
    """Opaque native conversation identity."""

    model_config = FROZEN

    value: str


class TurnId(BaseModel):
    """Opaque native turn identity."""

    model_config = FROZEN

    value: str


class TurnIdentifiers(BaseModel):
    """Identities attached to one accepted turn."""

    model_config = FROZEN

    session: SessionId
    turn: TurnId


class TurnInput(BaseModel):
    """Portable user input for one turn."""

    model_config = FROZEN

    text: str


class TurnTextBlock(BaseModel):
    """One completed assistant text block."""

    model_config = FROZEN

    type: Literal["text"] = "text"
    text: str


class TurnThinkingBlock(BaseModel):
    """One completed reasoning block."""

    model_config = FROZEN

    type: Literal["thinking"] = "thinking"
    thinking: str
    redacted: bool = False


class TurnToolCallBlock(BaseModel):
    """One completed tool invocation."""

    model_config = FROZEN

    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: JsonObject = Field(default_factory=dict)


class TurnToolResultBlock(BaseModel):
    """One completed tool result."""

    model_config = FROZEN

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    content: str
    is_error: bool = False


type TurnBlock = (
    TurnTextBlock | TurnThinkingBlock | TurnToolCallBlock | TurnToolResultBlock
)


class TurnMessage(BaseModel):
    """A portable transcript message derived from canonical blocks."""

    model_config = FROZEN

    role: Literal["user", "assistant", "tool", "system"]
    blocks: list[TurnBlock]


class TurnStartedEvent(BaseModel):
    """A native turn was accepted."""

    model_config = FROZEN

    type: Literal["turn_started"] = "turn_started"
    identifiers: TurnIdentifiers


class BlockStartedEvent(BaseModel):
    """A native content block started."""

    model_config = FROZEN

    type: Literal["block_started"] = "block_started"
    identifiers: TurnIdentifiers
    block: TurnBlock


class BlockDeltaEvent(BaseModel):
    """One text or thinking delta from an active native block."""

    model_config = FROZEN

    type: Literal["block_delta"] = "block_delta"
    identifiers: TurnIdentifiers
    delta: str


class BlockCompletedEvent(BaseModel):
    """One native content block completed."""

    model_config = FROZEN

    type: Literal["block_completed"] = "block_completed"
    identifiers: TurnIdentifiers
    block: TurnBlock


class TurnCompletedEvent(BaseModel):
    """A native turn reached a terminal state."""

    model_config = FROZEN

    type: Literal["turn_completed"] = "turn_completed"
    identifiers: TurnIdentifiers


type TurnEvent = (
    TurnStartedEvent
    | BlockStartedEvent
    | BlockDeltaEvent
    | BlockCompletedEvent
    | TurnCompletedEvent
)


class SubmissionDecision(BaseModel):
    """A reflection gate's decision about validated output."""

    model_config = FROZEN

    accepted: bool
    message: str = ""


type SubmissionGate[T] = Callable[[T], Awaitable[SubmissionDecision]]
type SubmissionGateResolver = Callable[
    [type[BaseModel]], SubmissionGate[BaseModel] | None
]


class TurnRequest[T: BaseModel | None](BaseModel):
    """Per-turn input and optional validated output type."""

    model_config = FROZEN_ARBITRARY

    input: TurnInput
    output_type: type[T] | None = None


@overload
def turn_request(input: str | TurnInput) -> TurnRequest[None]: ...


@overload
def turn_request[T: BaseModel](
    input: str | TurnInput,
    output_type: type[T],
) -> TurnRequest[T]: ...


def turn_request[T: BaseModel](
    input: str | TurnInput,
    output_type: type[T] | None = None,
) -> TurnRequest[T] | TurnRequest[None]:
    """Construct a request while preserving its output type relationship.

    The overload pair is what preserves it. Collapsed into this single
    implementation signature, ``T`` is left unsolved when the argument is
    omitted, and pyright infers ``TurnRequest[Unknown] | TurnRequest[None]``
    there and ``TurnRequest[Summary] | TurnRequest[None]`` when a model is
    passed. The overloads pin each direction to one exact type.
    """
    prompt = input if isinstance(input, TurnInput) else TurnInput(text=input)
    if output_type is None:
        return TurnRequest[None](input=prompt)
    return TurnRequest[T](input=prompt, output_type=output_type)


class TurnResult[T: BaseModel | None](BaseModel):
    """Successful terminal result; failures are represented only by errors."""

    model_config = FROZEN

    output: T
    messages: list[TurnMessage]
    blocks: list[TurnBlock]
    usage: Usage
    duration: timedelta
    identifiers: TurnIdentifiers


class SessionHandle(BaseModel):
    """Transparent composition of a session and optional fork capability."""

    model_config = FROZEN_ARBITRARY

    session: Session
    fork: ForkSession | None = None


class TurnHandle[T: BaseModel | None](BaseModel):
    """Transparent composition of an accepted turn's capabilities."""

    model_config = FROZEN_ARBITRARY

    turn: Turn[T]
    events: EventStream | None = None
    interrupt: Interrupt | None = None
    steer: Steer | None = None


class TurnToolBinding[T: BaseModel](BaseModel):
    """Turn-local schema, store, and optional reflection gate."""

    model_config = FROZEN_ARBITRARY

    output_type: type[T]
    store: SubmittedOutputStore
    gate: SubmissionGate[T] | None = None
