"""The client seam: purely abstract ``Client``/``Session``, nothing else.

The ABCs draw the contract — every member is ``@abstractmethod``, no
concrete defaults and no raising stubs. Engines do not subclass
``Client``: each contributes the component verbs it natively has — its
:class:`~lup.adapters.clients.Sessions.Sessions` always, plus a
:class:`~lup.adapters.clients.Stream.Stream` when its SDK feeds events
live — and :class:`~lup.adapters.clients.composed.ComposedClient`
composes them into this surface, filling the one-shot and stream gaps
generically. A capability an engine lacks entirely is an explicit
``raise UnsupportedOperationError(...)`` written in its own component at
the point of use (``interrupt`` where there is no interruption,
``open(resume=...)`` where threads cannot be restored), so reading one
engine's components shows exactly what it cannot do.

The machinery around the contract lives beside it, one concern per
module: :mod:`~lup.adapters.clients.usage` (usage normalization) and
:mod:`~lup.adapters.clients.refusal` (consume-tracking refusal of intent
knobs an engine's translation never reads).
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from lup.telemetry.trace import TraceLogger
from lup.types import LupEvent, LupResponse

if TYPE_CHECKING:
    from lup.realtime.relay import RealtimeMailbox


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
    ) -> LupResponse:
        """Send one message and collect the full response."""

    @abstractmethod
    async def interrupt(self) -> None:
        """Signal the backend to stop the current response.

        Engines without interruption support raise
        :class:`~lup.adapters.errors.UnsupportedOperationError` here.
        """


class Client(ABC):
    """A configured handle on one engine — cheap to build, nothing connected.

    ``query()`` runs a self-contained one-shot. ``session()`` opens the
    explicit multi-turn context; the engine's session-scoped resources
    (SDK client, container cleanup) live inside that context manager.
    """

    mailbox: "RealtimeMailbox | None" = None
    """Parent-side endpoint of the realtime file relay — not a caller knob.

    ``None`` unless the engine itself set it at construction: subprocess
    engines populate it when the options request persistent (sleep/wake)
    mode. Consumers only read it, to drive the relay loop."""

    @abstractmethod
    def session(
        self, *, resume: str | None = None
    ) -> AbstractAsyncContextManager[Session]:
        """Open a multi-turn session; ``resume`` continues a saved one.

        The SDK client/thread is created on entry and cleaned up on exit.
        ``resume`` takes a previously saved :attr:`Session.id`; engines
        that cannot restore sessions raise
        :class:`~lup.adapters.errors.UnsupportedOperationError`.
        """

    @abstractmethod
    async def query(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        """Self-contained one-shot: open a session, send one prompt, close.

        Carries run-time arguments only — construction knobs were fixed
        when the engine's factory built this client.
        """

    @abstractmethod
    def stream(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Run one prompt, yielding streaming events.

        Engines with a live event stream yield as the turn unfolds; those
        without replay the completed turn's blocks
        (:class:`~lup.adapters.clients.composed.ReplayStream`). Either
        way the terminal ``LupDoneEvent`` comes last.
        """
