"""Internal content block, message, response, and hook types.

These types are the shared vocabulary for all consumer code (core.py,
trace.py, etc.). SDK-specific adapters convert to/from these types at
the boundary — consumer code never imports from SDK packages directly.
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, TypedDict

from pydantic import BaseModel, Field


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
    thinking: str


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

    Each adapter interprets this into its native subagent primitive.
    """

    name: str
    description: str
    prompt: str
    tools: list[str] = Field(default_factory=list)
    model: str = "haiku"


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


class LupResultMessage(BaseModel):
    """Final result metadata from a completed agent run."""

    structured_output: dict[str, object] | None = None
    is_error: bool = False
    result: str | None = None
    duration_ms: float | None = None
    total_cost_usd: float | None = None
    usage: dict[str, int] | None = None


type LupMessage = (
    LupAssistantMessage | LupUserMessage | LupSystemMessage | LupResultMessage
)


# ---------------------------------------------------------------------------
# Response wrapper
# ---------------------------------------------------------------------------


class LupResponse(BaseModel):
    """Collected results from a completed agent run.

    Replaces ``ResponseCollector`` as the public return type from adapters.
    Provides the same accessors (``.text``, ``.output(T)``) that consumer
    code depends on.
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


class TokenUsage(TypedDict, total=False):
    """Token usage from API responses."""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int


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


def model_backend(model: str) -> str:
    """Determine the backend for a model name.

    Returns "anthropic" for Claude models, "openai" for GPT/O-series
    models, "openai-compatible" for everything else (open-source models
    served via vLLM, Ollama, TGI, etc.).
    """
    if model.startswith("claude-") or model in ("haiku", "sonnet", "opus"):
        return "anthropic"
    if model.startswith(("gpt-", "o1-", "o3-", "o4-")):
        return "openai"
    return "openai-compatible"
