"""One live multi-turn conversation: what a ``Sessions`` opener yields."""

from abc import ABC, abstractmethod

from lup.telemetry.trace import TraceLogger
from lup.types import LupResponse


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
