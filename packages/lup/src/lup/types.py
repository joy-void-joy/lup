"""Internal content block, message, response, and hook types.

These types are the shared vocabulary for all consumer code (core.py,
trace.py, etc.). SDK-specific adapters convert to/from these types at
the boundary — consumer code never imports from SDK packages directly.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Literal, TypedDict

from pydantic import BaseModel, Field, SerializeAsAny, ValidationError

logger = logging.getLogger(__name__)


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
    input: dict[str, object] | None = None


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


class LupResultMessage(BaseModel):
    """Final result metadata from a completed agent run."""

    structured_output: dict[str, object] | None = None
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


# ---------------------------------------------------------------------------
# Hook abstraction (SDK-agnostic)
# ---------------------------------------------------------------------------


class LupHookInput(TypedDict, total=False):
    """SDK-agnostic hook input. Adapters populate from their native format."""

    hook_event_name: str
    tool_name: str
    tool_input: dict[str, object]  # claude: ignore
    tool_result: str
    stop_hook_active: bool


class LupHookOutput(TypedDict, total=False):
    """SDK-agnostic hook output. Adapters convert to their native format."""

    decision: str
    reason: str
    system_message: str


type LupHookFn = Callable[[LupHookInput], Awaitable[LupHookOutput]]
"""Async function that receives hook input and returns a hook decision."""


class LupHookMatcher(BaseModel):
    """A hook handler with an optional tool name matcher.

    The ``tag`` field lets adapters dispatch deterministically instead
    of guessing hook intent from ``matcher`` / caller arguments.
    """

    matcher: str | None = None
    hook: LupHookFn
    tag: str | None = None

    model_config = {"arbitrary_types_allowed": True}


type LupHookEvent = Literal["PreToolUse", "PostToolUse", "Stop"]
type LupHooksConfig = dict[LupHookEvent, list[LupHookMatcher]]
"""SDK-agnostic hook configuration. Each adapter converts to native format."""


def allow_hook() -> LupHookOutput:
    """Create a generic allow decision."""
    return LupHookOutput(decision="allow")


def deny_hook(reason: str) -> LupHookOutput:
    """Create a generic deny decision."""
    return LupHookOutput(decision="deny", reason=reason)


def block_hook(reason: str) -> LupHookOutput:
    """Create a generic block decision."""
    return LupHookOutput(decision="block", reason=reason)


def extract_token_usage(raw: Mapping[str, object] | None) -> Usage | None:
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
) -> Usage | None:
    """Run a usage normalizer, degrading to None on failure.

    Usage is diagnostic — a broken normalizer must never fail a run that
    already completed. Failures are logged loudly and dropped.
    """
    if raw is None:
        return None
    try:
        return normalizer(raw)
    except ValidationError, KeyError, TypeError, AttributeError:
        name = getattr(normalizer, "__name__", repr(normalizer))
        logger.exception("Usage normalizer %s failed; dropping usage", name)
        return None


def merge_hooks(base: LupHooksConfig, additional: LupHooksConfig) -> LupHooksConfig:
    """Merge two hook configurations. Base hooks run first."""
    merged: LupHooksConfig = dict(base)
    for event in additional:
        if event in merged:
            merged[event] = merged[event] + additional[event]
        else:
            merged[event] = additional[event]
    return merged


# ---------------------------------------------------------------------------
# Effort normalization
# ---------------------------------------------------------------------------

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


def normalize_effort(effort: str | None, backend: str) -> str | None:
    """Map a generic effort level to SDK-specific value."""
    if effort is None:
        return None
    effort_map = EFFORT_MAP_CLAUDE if backend == "anthropic" else EFFORT_MAP_CODEX
    return effort_map.get(effort, effort)


type Backend = Literal["anthropic", "openai", "openai-compatible"]
"""Backend identifier — returned by model_backend, accepted by query()."""

ANTHROPIC_MODEL_PREFIXES: tuple[str, ...] = ("claude-",)
ANTHROPIC_MODEL_ALIASES: frozenset[str] = frozenset({"haiku", "sonnet", "opus"})
OPENAI_MODEL_PREFIXES: tuple[str, ...] = ("gpt-", "o1-", "o3-", "o4-", "o5-", "codex-")


def model_backend(model: str) -> Backend:
    """Determine the backend for a model name by prefix inference.

    Returns "anthropic" for Claude models, "openai" for GPT/O-series and
    Codex models, "openai-compatible" for everything else (open-source
    models served via vLLM, Ollama, TGI, etc.). The prefix tables above
    are module-level so downstream projects can extend them; for aliased
    or gateway model ids, pass ``backend=`` to
    :func:`lup.adapters.common.query` to bypass inference entirely.
    """
    if model.startswith(ANTHROPIC_MODEL_PREFIXES) or model in ANTHROPIC_MODEL_ALIASES:
        return "anthropic"
    if model.startswith(OPENAI_MODEL_PREFIXES):
        return "openai"
    return "openai-compatible"
