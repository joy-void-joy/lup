"""The background driver verb: drive turns against one SDK from a message stream."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class BackgroundDriver(ABC):
    """The per-engine verb: drive turns against the SDK from a message stream.

    Implementations carry their own SDK state and identity (name, model,
    tools); :class:`~lup.adapters.background.agent.BackgroundAgent`
    composes one over its debounced stream. A driver supervises itself:
    it logs a crash rather than letting it propagate into (or kill) the
    main session.
    """

    @abstractmethod
    async def run(self, messages: AsyncIterator[str]) -> None:
        """Consume turn messages, driving the SDK until cancelled."""
