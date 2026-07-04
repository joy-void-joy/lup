"""Internal content block, message, and response types.

These types are the shared vocabulary for all consumer code (core.py,
trace.py, etc.). SDK-specific adapters convert to/from these types at
the boundary — consumer code never imports from SDK packages directly.
The hook vocabulary lives in :mod:`lup.hooks`, not here.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field, SerializeAsAny, ValidationError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON vocabulary
# ---------------------------------------------------------------------------

type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
"""One JSON-decodable value — the shape ``json.loads`` yields.

The shared vocabulary for data whose schema is defined elsewhere (tool
arguments, JSON Schemas, vendor payloads): unlike ``object`` it stays
introspectable, and unlike ``Any`` it keeps the type checker honest.
"""

type JsonObject = dict[str, JsonValue]
"""A JSON object: tool inputs, JSON Schemas, structured outputs, session data."""

type PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]
"""How a session prompts for tool permission — a neutral intent knob;
engines without permission modes refuse it at construction."""

type Decorator[T, R] = Callable[[T], R]
"""A decorator: applied with ``@`` to a `T`, yields an `R`. Names the intent
at a signature (``-> Decorator[Handler, Tool]``) where a bare ``Callable`` of
a callable reads as noise. ``R`` need not be ``T`` — a decorator may return a
different type than it wraps (a builder, a registration object)."""


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------


class LupTextBlock(BaseModel):
    """Text content from the assistant."""

    type: Literal["text"] = "text"
    text: str


class LupThinkingBlock(BaseModel):
    """Extended thinking / reasoning content."""

    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    redacted: bool = False


class LupToolUseBlock(BaseModel):
    """A tool invocation by the agent."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: JsonObject | None = None


class LupToolResultBlock(BaseModel):
    """Result returned from a tool invocation."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str | Sequence[object] | None = None


type LupContentBlock = (
    LupTextBlock | LupThinkingBlock | LupToolUseBlock | LupToolResultBlock
)


# ---------------------------------------------------------------------------
# Subagent specification
# ---------------------------------------------------------------------------


class SubagentSpec(BaseModel):
    """SDK-agnostic subagent definition.

    Each adapter interprets this into its native subagent primitive:
    Claude converts to ``AgentDefinition``; other backends serve a
    ``run_subagent`` tool that dispatches a one-shot query per spec.
    """

    name: str
    description: str
    prompt: str
    tools: list[str] = Field(default_factory=list)
    model: str | None = Field(
        default=None,
        description="Model for this subagent; None inherits the session's "
        "main model on every backend",
    )
    max_turns: int | None = Field(
        default=None,
        description="Turn cap for delegated one-shot runs (None = backend default)",
    )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class LupAssistantMessage(BaseModel):
    """Message from the assistant containing content blocks."""

    role: Literal["assistant"] = "assistant"
    content: list[LupContentBlock]


class LupUserMessage(BaseModel):
    """Message from the user or tool results."""

    role: Literal["user"] = "user"
    content: list[LupContentBlock] | str


class LupSystemMessage(BaseModel):
    """System-level message (status updates, etc.)."""

    role: Literal["system"] = "system"
    subtype: str
    data: str


class Usage(BaseModel):
    """Portable token usage — the counts every backend can provide.

    Adapters produce this through a ``usage_normalizer`` callback supplied
    at construction, defaulting to each adapter's standard converter. A
    custom normalizer may return a *subclass* carrying vendor-specific
    fields (service tier, per-iteration costs, …); fields holding it are
    declared ``SerializeAsAny[Usage]`` so subclass data survives into
    session JSON.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


type UsageCost = Callable[[Usage], float]
"""Estimates the USD cost of accumulated token usage.

Backends that report token counts but no cost (Codex/OpenAI) take one of these
to enforce a budget; build it from per-token rates with
``lup.adapters.clients.codex.per_mtok_usage_cost``.
"""


class LupResultMessage(BaseModel):
    """Final result metadata from a completed agent run."""

    structured_output: JsonObject | None = None
    is_error: bool = False
    result: str | None = None
    duration_ms: float | None = None
    total_cost_usd: float | None = None
    usage: SerializeAsAny[Usage] | None = None


type LupMessage = (
    LupAssistantMessage | LupUserMessage | LupSystemMessage | LupResultMessage
)


# ---------------------------------------------------------------------------
# Response wrapper
# ---------------------------------------------------------------------------


class LupResponse(BaseModel):
    """Collected results from a completed agent run.

    The public return type from adapters: ``.text`` for concatenated
    assistant text, ``.output(Model)`` for validated structured output.
    """

    blocks: list[LupContentBlock] = Field(default_factory=list)
    tool_results: list[LupContentBlock] = Field(default_factory=list)
    messages: list[LupAssistantMessage | LupUserMessage] = Field(default_factory=list)
    result: LupResultMessage | None = None
    session_id: str | None = None

    @property
    def text(self) -> str | None:
        """Concatenated text from all assistant text blocks."""
        texts = [b.text for b in self.blocks if isinstance(b, LupTextBlock)]
        return "\n\n".join(texts) if texts else None

    def output[T: BaseModel](self, output_type: type[T]) -> T | None:
        """Extract structured output as a validated Pydantic model."""
        if self.result is not None and self.result.structured_output:
            return output_type.model_validate(self.result.structured_output)
        return None


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------


class LupTextEvent(BaseModel):
    """Streamed text delta."""

    type: Literal["text"] = "text"
    text: str


class LupThinkingEvent(BaseModel):
    """Streamed thinking content."""

    type: Literal["thinking"] = "thinking"
    thinking: str


class LupToolUseEvent(BaseModel):
    """Streamed tool invocation start."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str


class LupToolResultEvent(BaseModel):
    """Streamed tool result."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str


class LupDoneEvent(BaseModel):
    """Stream complete; carries all collected content blocks."""

    type: Literal["done"] = "done"
    blocks: list[LupContentBlock] = Field(default_factory=list)


type LupEvent = (
    LupTextEvent
    | LupThinkingEvent
    | LupToolUseEvent
    | LupToolResultEvent
    | LupDoneEvent
)


def extract_token_usage(raw: Mapping[str, JsonValue] | None) -> Usage | None:
    """Extract portable token counts from a raw vendor usage mapping.

    Reads only the known count fields and ignores vendor extras, so
    payload growth in any SDK can never fail a completed run. Default
    normalizer for adapters whose raw payload is a mapping.
    """
    if not raw:
        return None

    def count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) else 0

    return Usage(
        input_tokens=count("input_tokens"),
        output_tokens=count("output_tokens"),
        cache_read_input_tokens=count("cache_read_input_tokens"),
        cache_creation_input_tokens=count("cache_creation_input_tokens"),
    )


def safe_normalize_usage[T](
    normalizer: Callable[[T], Usage | None],
    raw: T | None,
) -> Usage | None:  # lup: Why is this here?
    """Run a usage normalizer, degrading to None on failure.

    Usage is diagnostic — a broken normalizer must never fail a run that
    already completed. Failures are logged loudly and dropped.
    """
    if raw is None:
        return None
    try:
        return normalizer(raw)
    except (ValidationError, KeyError, TypeError, AttributeError):
        name = getattr(normalizer, "__name__", repr(normalizer))
        logger.exception("Usage normalizer %s failed; dropping usage", name)
        return None


# ---------------------------------------------------------------------------
# Effort normalization
# ---------------------------------------------------------------------------

# lup: This shouldn't live here. This should live in the adapters folders instead
EFFORT_MAP_CLAUDE: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
    "max": "max",
}

EFFORT_MAP_CODEX: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}


def normalize_effort(effort: str | None, engine: str) -> str | None:
    """Map a generic effort level to SDK-specific value."""
    if effort is None:
        return None
    effort_map = EFFORT_MAP_CLAUDE if engine == "claude" else EFFORT_MAP_CODEX
    return effort_map.get(effort, effort)
