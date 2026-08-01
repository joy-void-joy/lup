"""Immutable semantic values shared by all runtime implementations."""

import json
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated, Literal, overload

from pydantic import BaseModel, ConfigDict, Discriminator, Field

from lup.runtime.contracts import (
    EventStream,
    ForkSession,
    Interrupt,
    Session,
    Steer,
    SubmittedOutputStore,
    Turn,
)
from lup.types import (
    JsonObject,
    LupContentBlock,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    Usage,
)

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


class TurnBlock(BaseModel):
    """One completed block of a turn, answering every question about itself.

    Whatever a caller needs to know about a block is declared here and
    answered — or declined — by the block, so a new kind of block is one class
    rather than an edit to every walk that would have to notice it. The
    declining answers are what make omission safe: a caller joining
    ``text_payload`` reaches every kind that carries prose, including kinds
    written long after the caller was.

    Pydantic's metaclass is an ``ABCMeta``, so ``telemetry_block`` binds like
    any abstract property: a kind that does not answer it cannot be built.
    """

    model_config = FROZEN

    @property
    @abstractmethod
    def telemetry_block(self) -> LupContentBlock:
        """This block as the telemetry vocabulary spells it."""

    @property
    def text_payload(self) -> str | None:
        """Prose this block carries verbatim, if it carries any.

        Everything that reads what a turn actually said asks this instead of
        naming the kinds of block that hold text.
        """
        return None

    @property
    def tool_call_name(self) -> str | None:
        """The tool this block invokes, if it invokes one."""
        return None

    @property
    def tool_arguments(self) -> JsonObject | None:
        """The arguments this block invokes its tool with, if it invokes one."""
        return None


class TurnTextBlock(TurnBlock):
    """One completed assistant text block."""

    type: Literal["text"] = "text"
    text: str

    @property
    def telemetry_block(self) -> LupContentBlock:
        return LupTextBlock(text=self.text)

    @property
    def text_payload(self) -> str | None:
        return self.text


class TurnThinkingBlock(TurnBlock):
    """One completed reasoning block."""

    type: Literal["thinking"] = "thinking"
    thinking: str
    redacted: bool = False

    @property
    def telemetry_block(self) -> LupContentBlock:
        return LupThinkingBlock(thinking=self.thinking, redacted=self.redacted)


class TurnToolCallBlock(TurnBlock):
    """One completed tool invocation."""

    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: JsonObject = Field(default_factory=dict)

    @property
    def telemetry_block(self) -> LupContentBlock:
        return LupToolUseBlock(id=self.id, name=self.name, input=self.arguments)

    @property
    def tool_call_name(self) -> str | None:
        return self.name

    @property
    def tool_arguments(self) -> JsonObject | None:
        return self.arguments


class TurnToolResultBlock(TurnBlock):
    """One completed tool result."""

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    content: str
    is_error: bool = False

    @property
    def telemetry_block(self) -> LupContentBlock:
        rendered = (
            json.dumps({"is_error": True, "content": self.content})
            if self.is_error
            else self.content
        )
        return LupToolResultBlock(tool_use_id=self.tool_call_id, content=rendered)


type AnyTurnBlock = Annotated[
    TurnTextBlock | TurnThinkingBlock | TurnToolCallBlock | TurnToolResultBlock,
    Discriminator("type"),
]
"""One block as a pydantic *field* validates it: the closed set, discriminated.

Annotations that only read a block name :class:`TurnBlock`, the base. A field
must name this alias instead — validating against the base alone would rebuild
every block as a base instance and drop its payload.
"""


class TurnMessage(BaseModel):
    """A portable transcript message derived from canonical blocks."""

    model_config = FROZEN

    role: Literal["user", "assistant", "tool", "system"]
    blocks: list[AnyTurnBlock]


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
    block: AnyTurnBlock


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
    block: AnyTurnBlock


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


@overload  # lup: The overload seems superfluous? Can't we just TurnRequest[T: BaseModel | None] ?
def turn_request(input: TurnInput) -> TurnRequest[None]: ...


@overload
def turn_request[T: BaseModel](
    input: TurnInput,
    output_type: type[T],
) -> TurnRequest[T]: ...


def turn_request[T: BaseModel](
    input: TurnInput,
    output_type: type[T] | None = None,
) -> TurnRequest[T] | TurnRequest[None]:
    """Construct a request while preserving its output type relationship."""
    if output_type is None:
        return TurnRequest[None](input=input)
    return TurnRequest[T](input=input, output_type=output_type)


class TurnResult[T: BaseModel | None](BaseModel):
    """Successful terminal result; failures are represented only by errors."""

    model_config = FROZEN

    output: T
    messages: list[TurnMessage]
    blocks: list[AnyTurnBlock]
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
