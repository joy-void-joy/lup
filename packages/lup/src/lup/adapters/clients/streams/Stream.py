"""The stream verb: one turn as a feed of events.

An engine whose SDK feeds events as the turn unfolds implements
:class:`Stream` itself
(:class:`~lup.adapters.clients.claude.stream.ClaudeLiveStream`); an
engine whose SDK reports a turn only once complete contributes nothing,
and :class:`~lup.adapters.clients.composed.ComposedClient` fills the slot
with :class:`~lup.adapters.clients.streams.replay.ReplayStream`.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from lup.telemetry.trace import TraceLogger
from lup.types import LupEvent


class Stream(ABC):
    """Runs one prompt as a stream of ``LupEvent``\\ s."""

    @abstractmethod
    def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Yield the turn's events, the terminal ``LupDoneEvent`` last."""
