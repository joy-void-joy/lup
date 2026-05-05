"""Agent adapter ABC.

Each SDK adapter implements this interface. Consumer code (core.py)
instantiates the appropriate adapter via ``build_adapter()`` and calls
``run()`` (one-shot) or ``conversation()`` (multi-turn).
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from lup.lib.trace import TraceLogger
from lup.lib.types import LupContentBlock, LupResponse


# ---------------------------------------------------------------------------
# Streaming events
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Conversation (multi-turn session)
# ---------------------------------------------------------------------------


class Conversation(ABC):
    """Multi-turn conversation session.

    Wraps a persistent SDK client or thread. ``send()`` sends a message
    and collects the full response. ``interrupt()`` signals the backend
    to stop the current response (Ctrl-C support).
    """

    @abstractmethod
    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse: ...

    async def interrupt(self) -> None:
        """Signal the backend to stop the current response. No-op by default."""
        pass


# ---------------------------------------------------------------------------
# Adapter ABC
# ---------------------------------------------------------------------------


class AgentAdapter(ABC):
    """Run prompts against an SDK backend.

    The single abstract method is ``conversation()``, which yields a
    multi-turn ``Conversation``. ``run()`` is a convenience that opens
    a conversation, sends one prompt, and closes it.
    """

    @abstractmethod
    @asynccontextmanager
    async def conversation(self) -> AsyncGenerator[Conversation, None]:
        """Create a multi-turn conversation session.

        Yields a ``Conversation`` that maintains state across turns.
        The SDK client/thread is created on entry and cleaned up on exit.
        """
        yield  # type: ignore[misc]

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """One-shot convenience: open conversation, send one prompt, close."""
        async with self.conversation() as conv:
            return await conv.send(
                prompt, trace_logger=trace_logger, prefix=prefix
            )

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
