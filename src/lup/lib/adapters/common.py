"""Agent adapter ABC.

Each SDK adapter implements this interface. Consumer code (core.py)
instantiates the appropriate adapter and calls ``run()``.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from lup.lib.trace import TraceLogger
from lup.lib.types import LupContentBlock, LupResponse


class LupEvent:
    """Base class for normalized streaming events."""

    pass


class LupTextEvent(LupEvent):
    """Streamed text delta."""

    def __init__(self, text: str) -> None:
        self.text = text


class LupToolUseEvent(LupEvent):
    """Streamed tool invocation start."""

    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


class LupToolResultEvent(LupEvent):
    """Streamed tool result."""

    def __init__(self, tool_use_id: str, content: str) -> None:
        self.tool_use_id = tool_use_id
        self.content = content


class LupThinkingEvent(LupEvent):
    """Streamed thinking content."""

    def __init__(self, thinking: str) -> None:
        self.thinking = thinking


class LupDoneEvent(LupEvent):
    """Stream complete."""

    def __init__(self, blocks: list[LupContentBlock] | None = None) -> None:
        self.blocks = blocks or []


class AgentAdapter(ABC):
    """Run a prompt against an SDK backend and return collected results."""

    @abstractmethod
    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse: ...

    async def run_streamed(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Run with streaming events. Default falls back to non-streaming."""
        response = await self.run(prompt, trace_logger=trace_logger, prefix=prefix)
        yield LupDoneEvent(blocks=response.blocks)

    async def resume(self, _session_id: str, _prompt: str) -> LupResponse:
        """Resume an existing session/thread. Override in adapters that support it."""
        raise NotImplementedError(f"{type(self).__name__} does not support resume")

    async def fork(self, _session_id: str, _prompt: str) -> LupResponse:
        """Fork an existing session/thread. Override in adapters that support it."""
        raise NotImplementedError(f"{type(self).__name__} does not support fork")


def model_backend(model: str) -> str:
    """Determine the backend for a model name.

    Returns "anthropic" for Claude models, "openai" for GPT/O models.
    """
    if model.startswith("claude-") or model in ("haiku", "sonnet", "opus"):
        return "anthropic"
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    return "anthropic"


EFFORT_MAP_CLAUDE = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "max",
    "max": "max",
}

EFFORT_MAP_CODEX = {
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
