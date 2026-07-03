"""Client and Session — the run-side interface every engine implements.

An :class:`~lup.adapters.engine.Engine` constructs a :class:`Client`; the
client opens :class:`Session`\\ s. ``query()`` is the self-contained
one-shot (opens, sends, closes — nothing to leak); ``session()`` is the
explicit multi-turn context, resumable across process runs via
``session(resume=...)`` and :attr:`Session.id`.

This module defines the seam and imports no engine and no SDK. What an
engine cannot do surfaces as behavior, not declarations: construction
raises :class:`UnsupportedOptionsError` for intent knobs it cannot honor,
and operations raise :class:`UnsupportedOperationError` at the point of
use.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Literal

from lup.trace import TraceLogger
from lup.types import (
    LupDoneEvent,
    LupEvent,
    LupResponse,
    LupTextBlock,
    LupTextEvent,
    LupThinkingBlock,
    LupThinkingEvent,
    LupToolResultBlock,
    LupToolResultEvent,
    LupToolUseBlock,
    LupToolUseEvent,
)

if TYPE_CHECKING:
    from lup.realtime_relay import RealtimeMailbox

logger = logging.getLogger(__name__)

type PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]


class UnsupportedOperationError(NotImplementedError):
    """The engine behind this client cannot perform the requested operation.

    Raised at the point of use — ``interrupt()`` on a runtime with no
    interruption support, ``session(resume=...)`` on an engine that cannot
    restore threads. A ``NotImplementedError`` subclass, so generic
    ``except NotImplementedError`` handlers also catch it.
    """


class UnsupportedOptionsError(ValueError):
    """The engine cannot honor intent knobs the options carry.

    Raised at construction (``on_unsupported="raise"``, the session
    default), so a session that asked for, say, ``max_turns`` on a runtime
    without turn caps fails before it starts. ``fields`` names the
    offenders. With ``on_unsupported="drop"`` the engine clears them and
    logs instead — the one-shot ``query()`` policy.
    """

    def __init__(self, engine: str, fields: list[str]) -> None:
        self.engine = engine
        self.fields = sorted(fields)
        super().__init__(
            f"options {self.fields} are not supported on the {engine} engine; "
            "unset them or run on an engine that honors them."
        )


class TurnTimeoutError(RuntimeError):
    """A turn exceeded its wall-clock timeout and was cancelled client-side.

    Raised by engines that enforce ``turn_timeout_seconds`` when a single
    turn runs past it. The backend thread's state is undefined afterwards
    — close the session rather than sending further turns on it.
    """


class BudgetExceededError(RuntimeError):
    """A session refused to start a turn: accumulated cost reached the budget.

    Raised between turns by engines that enforce ``max_budget_usd``
    through their own usage accounting (the Codex runtime reports token
    counts, not cost). The turn that crossed the budget has already
    completed — this error stops the *next* one.
    """


class Session(ABC):
    """Multi-turn conversation session.

    Wraps a live SDK client or thread. ``send()`` sends a message and
    collects the full response. :attr:`id` is the engine-native session
    identifier once known — save it and pass it to
    ``Client.session(resume=...)`` to continue the conversation in a
    different process.
    """

    id: str | None = None
    """Engine-native session identifier (Claude session id, Codex thread
    id). ``None`` until the engine reports it — populated on open for
    resumed sessions, after the first turn otherwise."""

    @abstractmethod
    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse: ...

    async def interrupt(self) -> None: #lup: Why is this an UnsupportedOperationError, and not an abstractmethod? That seems inconsistent?
        """Signal the backend to stop the current response.

        Engines without interruption support inherit this default, which
        raises — catch :class:`UnsupportedOperationError` (or plain
        ``NotImplementedError``) where a no-op interrupt is acceptable.
        """
        raise UnsupportedOperationError(
            f"interrupt() is not supported on {type(self).__name__}"
        )


class Client(ABC):
    """A configured handle on one engine — cheap to build, nothing connected.

    ``query()`` runs a self-contained one-shot. ``session()`` opens the
    explicit multi-turn context; the engine's session-scoped resources
    (SDK client, container cleanup) live inside that context manager.
    """

    mailbox: "RealtimeMailbox | None" = None #lup: This is not clear to me what this is. When would I set it?
    """Parent-side endpoint of the realtime file relay — set by subprocess
    engines when the options ask for persistent (sleep/wake) mode."""

    @abstractmethod
    def session(
        self, *, resume: str | None = None
    ) -> AbstractAsyncContextManager[Session]:
        """Open a multi-turn session; ``resume`` continues a saved one.

        Implementations are ``@asynccontextmanager`` async generators
        yielding a :class:`Session`. The SDK client/thread is created on
        entry and cleaned up on exit. ``resume`` takes a previously saved
        :attr:`Session.id`; engines that cannot restore sessions raise
        :class:`UnsupportedOperationError`.
        """

    async def query( #lup: Isn't this lacking a lot of kwargs compared to engine.py's query?
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """Self-contained one-shot: open a session, send one prompt, close."""
        async with self.session() as session:
            return await session.send(prompt, trace_logger=trace_logger, prefix=prefix)

    async def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Run one prompt, yielding streaming events.

        The default runs the turn to completion and replays its blocks as
        events; engines with a live event stream override this.
        """
        response = await self.query(prompt, trace_logger=trace_logger, prefix=prefix)
        for block in response.blocks:
            match block:
                case LupThinkingBlock():
                    yield LupThinkingEvent(thinking=block.thinking)
                case LupTextBlock():
                    yield LupTextEvent(text=block.text)
                case LupToolUseBlock():
                    yield LupToolUseEvent(id=block.id, name=block.name)
                case LupToolResultBlock():
                    yield LupToolResultEvent(
                        tool_use_id=block.tool_use_id,
                        content=str(block.content),
                    )
        yield LupDoneEvent(blocks=response.blocks)
