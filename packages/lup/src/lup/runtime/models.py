"""Immutable semantic values shared by all runtime implementations."""

import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated, Literal, TypeIs, overload

from pydantic import BaseModel, Discriminator, Field

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


# The tool names a runtime spells native delegation with. Kept beside the
# block that answers about a delegation so no reader has to know them.
DELEGATION_TOOLS = ("Agent", "Task")

# What a delegation is called when its call named no role.
UNNAMED_SUBAGENT = "subagent"


class SessionId(BaseModel, frozen=True):
    """Opaque native conversation identity."""

    value: str


class TurnId(BaseModel, frozen=True):
    """Opaque native turn identity."""

    value: str


class TurnIdentifiers(BaseModel, frozen=True):
    """Identities attached to one accepted turn."""

    session: SessionId
    turn: TurnId


class TurnInput(BaseModel, frozen=True):
    """Portable user input for one turn."""

    text: str


class TextBlockRecord(BaseModel, frozen=True):
    """One assistant text block as a turn document writes it."""

    kind: Literal["text"] = "text"
    text: str


class ThinkingBlockRecord(BaseModel, frozen=True):
    """One reasoning block as a turn document writes it."""

    kind: Literal["thinking"] = "thinking"
    thinking: str
    redacted: bool = False


class ToolCallBlockRecord(BaseModel, frozen=True):
    """One tool invocation as a turn document writes it."""

    kind: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: JsonObject = {}


class ToolResultBlockRecord(BaseModel, frozen=True):
    """One tool result as a turn document writes it."""

    kind: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    content: str
    is_error: bool = False


type BlockRecord = Annotated[
    TextBlockRecord | ThinkingBlockRecord | ToolCallBlockRecord | ToolResultBlockRecord,
    Discriminator("kind"),
]
"""One block as it is written to, and read back from, a turn document.

Discriminated because this one genuinely is a wire format: pydantic has to
rebuild the right variant from JSON, which is the case a discriminator exists
for. The blocks themselves need none — nothing validates a block into being,
so in memory they are objects that answer for themselves.
"""


class ToolRefusal(BaseModel, frozen=True):
    """One tool call that returned an error instead of a result."""

    call_id: str
    detail: str


class BlockPayload(BaseModel, frozen=True):
    """What a block carries, as every walk across blocks asks for it.

    One shape rather than a field per kind, because these are the questions
    asked of a block whose kind the caller does not know: a walk joining prose
    reaches every kind that carries any, including kinds written long after it
    was. A kind that carries none of something leaves the default, which is
    what makes omission safe.
    """

    text: str | None = None
    """Prose this block carries verbatim, if it carries any."""

    tool_call_name: str | None = None
    """The tool this block invokes, if it invokes one."""

    tool_arguments: JsonObject | None = None
    """The arguments this block invokes its tool with, if it invokes one."""

    invoked_call_id: str | None = None
    """The id of the call this block makes, if it makes one."""

    refusal: ToolRefusal | None = None
    """The refused call this block reports, if it reports one."""


class TurnBlock(ABC):
    """One completed block of a turn, answering every question about itself.

    Three projections, and no state: what the block carries, how the telemetry
    vocabulary spells it, and how a turn document writes it. A kind holds its
    own fields and answers with one of these, so a new kind is one class rather
    than an edit to every walk that would have to notice it.

    Nothing here carries a discriminator, because nothing validates a block
    into existence — the alias that used to sit beside these existed so a
    pydantic field would not flatten every block to its base, not because a
    wire format needed one. Where a wire format does, :data:`BlockRecord` says
    so in its own right.
    """

    @abstractmethod
    def payload(self) -> BlockPayload:
        """What this block carries, for a caller that does not know its kind."""

    @abstractmethod
    def telemetry_block(self) -> LupContentBlock:
        """This block as the telemetry vocabulary spells it."""

    @abstractmethod
    def record(self) -> BlockRecord:
        """This block as a turn document writes it."""

    def delegated_role(
        self,
        tools: tuple[str, ...] = DELEGATION_TOOLS,
        unnamed: str = UNNAMED_SUBAGENT,
    ) -> str | None:
        """The subagent role this block delegates to, if it delegates.

        A member rather than an attribute because it is computed from what
        the block carries rather than carried: the tool name and arguments
        are the data, and which of them names a role is the question.

        Asked of the block so a reader correlating a transcript never has to
        know which tool a runtime spells delegation with, nor which argument
        carries the role. Both are parameters because a runtime this library
        has not met spells them its own way, and a caller should not have to
        fork a block to say so.
        """
        return None


class TurnTextBlock(TurnBlock):
    """One completed assistant text block."""

    def __init__(self, text: str) -> None:
        self.text = text

    def payload(self) -> BlockPayload:
        return BlockPayload(text=self.text)

    def telemetry_block(self) -> LupContentBlock:
        return LupTextBlock(text=self.text)

    def record(self) -> BlockRecord:
        return TextBlockRecord(text=self.text)


class TurnThinkingBlock(TurnBlock):
    """One completed reasoning block."""

    def __init__(self, thinking: str, redacted: bool = False) -> None:
        self.thinking = thinking
        self.redacted = redacted

    def payload(self) -> BlockPayload:
        return BlockPayload()

    def telemetry_block(self) -> LupContentBlock:
        return LupThinkingBlock(thinking=self.thinking, redacted=self.redacted)

    def record(self) -> BlockRecord:
        return ThinkingBlockRecord(thinking=self.thinking, redacted=self.redacted)


class TurnToolCallBlock(TurnBlock):
    """One completed tool invocation."""

    def __init__(self, id: str, name: str, arguments: JsonObject | None = None) -> None:
        self.id = id
        self.name = name
        self.arguments: JsonObject = arguments or {}

    def payload(self) -> BlockPayload:
        return BlockPayload(
            tool_call_name=self.name,
            tool_arguments=self.arguments,
            invoked_call_id=self.id,
        )

    def telemetry_block(self) -> LupContentBlock:
        return LupToolUseBlock(id=self.id, name=self.name, input=self.arguments)

    def record(self) -> BlockRecord:
        return ToolCallBlockRecord(id=self.id, name=self.name, arguments=self.arguments)

    def delegated_role(
        self,
        tools: tuple[str, ...] = DELEGATION_TOOLS,
        unnamed: str = UNNAMED_SUBAGENT,
    ) -> str | None:
        if self.name not in tools:
            return None
        requested = self.arguments.get("subagent_type")  # lup: ignore[dict-get]
        if not isinstance(requested, str):
            requested = self.arguments.get("name")  # lup: ignore[dict-get]
        return requested if isinstance(requested, str) else unnamed


class TurnToolResultBlock(TurnBlock):
    """One completed tool result."""

    def __init__(self, tool_call_id: str, content: str, is_error: bool = False) -> None:
        self.tool_call_id = tool_call_id
        self.content = content
        self.is_error = is_error

    def payload(self) -> BlockPayload:
        return BlockPayload(
            refusal=ToolRefusal(call_id=self.tool_call_id, detail=self.content)
            if self.is_error
            else None
        )

    def telemetry_block(self) -> LupContentBlock:
        rendered = (
            json.dumps({"is_error": True, "content": self.content})
            if self.is_error
            else self.content
        )
        return LupToolResultBlock(tool_use_id=self.tool_call_id, content=rendered)

    def record(self) -> BlockRecord:
        return ToolResultBlockRecord(
            tool_call_id=self.tool_call_id,
            content=self.content,
            is_error=self.is_error,
        )


type TurnRole = Literal["user", "assistant", "tool", "system"]
"""Who a transcript message is from."""


class TurnMessage(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """A portable transcript message derived from canonical blocks.

    Still a model, because ``role`` is data worth validating and the message
    carries no behaviour. Its blocks are objects that answer for themselves
    rather than records pydantic rebuilds, so they arrive as arbitrary types —
    which is also what retires the discriminated alias that used to sit here:
    it existed only so a pydantic field would not flatten every block to its
    base, and a field that validates nothing cannot flatten anything.
    """

    role: TurnRole
    blocks: list[TurnBlock]
    parent_tool_call_id: str | None = Field(
        default=None,
        description=(
            "The delegation tool call this message was produced under, when "
            "the provider attributes it to one — the only evidence that "
            "separates a native subagent's messages from its parent's"
        ),
    )
    model: str | None = Field(
        default=None,
        description="Model the provider reports for this message, when it does",
    )
    message_id: str | None = Field(
        default=None,
        description="Provider's own message identifier, for correlating replays",
    )


class MessageRecord(BaseModel, frozen=True):
    """One transcript message as a turn document writes it."""

    role: TurnRole
    blocks: list[BlockRecord]


class TurnEventBase(BaseModel, frozen=True):
    """One thing that happened during a turn, answering about itself.

    The same arrangement :class:`TurnBlock` uses, for the same reason: a walk
    over events asks the event, so a new kind of event is one class rather
    than an edit to every filter that would have to notice it. What an event
    *carries* is an attribute a kind overrides by assigning it — a caller
    folding ``completed_message`` reaches every kind that carries one,
    including kinds written later.

    ``durable`` is one of them too. It used to answer with the event itself so
    a caller could keep the narrower type; a ``Literal`` flag narrows a union
    exactly as well, and being data it needs no member at all — which is what
    leaves these kinds as records with no behaviour between them.

    Each kind names itself in a ``type`` of its own. The strings were never
    only pydantic's: a run's status line records its last event by that name,
    across a union spanning resolver events and these alike.
    """

    completed_message: "TurnMessage | None" = None
    """The whole transcript message this event completed, if it completed one."""


class TurnStartedEvent(TurnEventBase, frozen=True):
    """A native turn was accepted."""

    type: Literal["turn_started"] = "turn_started"
    durable: Literal[True] = True
    identifiers: TurnIdentifiers


class BlockStartedEvent(TurnEventBase, frozen=True):
    """A native content block started.

    The block arrives as its record rather than as the live object: nothing
    reads a block off an event, and this is what a journal entry has to write
    down.
    """

    type: Literal["block_started"] = "block_started"
    durable: Literal[True] = True
    identifiers: TurnIdentifiers
    block: BlockRecord


class BlockDeltaEvent(TurnEventBase, frozen=True):
    """One text or thinking delta from an active native block."""

    type: Literal["block_delta"] = "block_delta"
    durable: Literal[False] = False
    """A fragment of a block still being written survives nothing."""

    identifiers: TurnIdentifiers
    delta: str


class BlockCompletedEvent(TurnEventBase, frozen=True):
    """One native content block completed."""

    type: Literal["block_completed"] = "block_completed"
    durable: Literal[True] = True
    identifiers: TurnIdentifiers
    block: BlockRecord


class MessageCompletedEvent(TurnEventBase, frozen=True):
    """One whole transcript message completed.

    The message is carried rather than reconstructed. Folding loose blocks
    back into messages would need contiguous-role grouping, which silently
    merges two consecutive assistant messages into one; carrying the whole
    message makes the fold exact.
    """

    type: Literal["message_completed"] = "message_completed"
    durable: Literal[True] = True
    identifiers: TurnIdentifiers


class TurnCompletedEvent(TurnEventBase, frozen=True):
    """A native turn reached a terminal state."""

    type: Literal["turn_completed"] = "turn_completed"
    durable: Literal[True] = True
    identifiers: TurnIdentifiers


type TurnEvent = (
    TurnStartedEvent
    | BlockStartedEvent
    | BlockCompletedEvent
    | MessageCompletedEvent
    | TurnCompletedEvent
)
"""Everything durable. A transcript folds from exactly these.

Deltas are deliberately absent: :func:`lup.runtime.transcript.fold_transcript`
takes this union, so a partial fragment cannot reach the fold at all rather
than being filtered out inside it.
"""


def survives(event: "LiveTurnEvent") -> TypeIs["TurnEvent"]:
    """Whether this event reaches the transcript, as the type system sees it.

    The judgement is the kind's own ``durable`` field and is read here rather
    than restated: a filter that names the kinds it drops goes stale the moment
    one is added, and the new kind would reach the transcript with its own
    declaration saying it should not. What this adds is the narrowing, which a
    plain field cannot give a caller — pyright narrows on a comparison, not on
    the truth of a ``bool``.
    """
    return event.durable


type LiveTurnEvent = TurnEvent | BlockDeltaEvent
"""Everything durable, plus in-flight deltas, in order.

A strict superset of :data:`TurnEvent`, so a consumer picks one accessor and
gets consistent behaviour either way instead of two views that disagree
about what happened.
"""


class SubmissionDecision(BaseModel, frozen=True):
    """A reflection gate's decision about validated output."""

    accepted: bool
    message: str = ""


type SubmissionGate[T] = Callable[[T], Awaitable[SubmissionDecision]]
type SubmissionGateResolver = Callable[
    [type[BaseModel]], SubmissionGate[BaseModel] | None
]


class TurnRequest[T: BaseModel | None](
    BaseModel, frozen=True, arbitrary_types_allowed=True
):
    """Per-turn input and optional validated output type."""

    input: TurnInput
    output_type: type[T] | None = None


# The overload pair and the implementation are one constructor, so each `def`
# answers for itself: `input` is the value being packaged, in either of the two
# spellings a caller may hand it, and the operation is building the request
# around it rather than anything a TurnInput does to itself.
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
    # Narrowed on `str` rather than on `TurnInput`: the foreign alternative is
    # the one that cannot answer for itself, and asking about it leaves ours
    # to arrive by exclusion instead of by name.
    match input:
        case str():
            prompt = TurnInput(text=input)
        case _:
            prompt = input
    if output_type is None:
        return TurnRequest[None](input=prompt)
    return TurnRequest[T](input=prompt, output_type=output_type)


class TurnResult[T: BaseModel | None](
    BaseModel, frozen=True, arbitrary_types_allowed=True
):
    """Successful terminal result; failures are represented only by errors."""

    output: T
    messages: list[TurnMessage]
    blocks: list[TurnBlock]
    usage: Usage
    duration: timedelta
    identifiers: TurnIdentifiers


class TurnRecord[T: BaseModel | None](BaseModel, frozen=True):
    """One successful turn as its document on disk."""

    output: T
    messages: list[MessageRecord]
    blocks: list[BlockRecord]
    usage: Usage
    duration: timedelta
    identifiers: TurnIdentifiers


def turn_record[T: BaseModel | None](result: TurnResult[T]) -> TurnRecord[T]:
    """One result as its document on disk.

    A free function rather than a member: the result is data, and writing it
    down is what the persistence wrapper does to it rather than something the
    value does to itself.
    """
    return TurnRecord[T](
        output=result.output,
        messages=[
            MessageRecord(
                role=message.role, blocks=[block.record() for block in message.blocks]
            )
            for message in result.messages
        ],
        blocks=[block.record() for block in result.blocks],
        usage=result.usage,
        duration=result.duration,
        identifiers=result.identifiers,
    )


class SessionHandle(BaseModel, frozen=True, arbitrary_types_allowed=True):
    """Transparent composition of a session and optional fork capability.

    Reaching a capability through this handle is not a consumer holding an
    ABC: the handle carries capabilities and no behaviour of its own, so
    there is nothing for a composing surface to home. ``SessionFactory`` is
    the behavioural surface over these seams.
    """

    session: Session
    fork: ForkSession | None = None


class TurnHandle[T: BaseModel | None](
    BaseModel, frozen=True, arbitrary_types_allowed=True
):
    """Transparent composition of an accepted turn's capabilities.

    A carrier on the same terms as :class:`SessionHandle`: it holds seams and
    no behaviour, so ``turn.result()`` reaches an engine rather than calling a
    surface that should have owned shared behaviour.
    """

    turn: Turn[T]
    events: EventStream | None = None
    interrupt: Interrupt | None = None
    steer: Steer | None = None


class TurnToolBinding[T: BaseModel](
    BaseModel, frozen=True, arbitrary_types_allowed=True
):
    """Turn-local schema, store, and optional reflection gate."""

    output_type: type[T]
    store: SubmittedOutputStore
    gate: SubmissionGate[T] | None = None
