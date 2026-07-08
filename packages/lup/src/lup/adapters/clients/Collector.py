"""The response-path template: one turn's native stream into a ``LupResponse``.

Unlike the :class:`~lup.adapters.clients.Client.Client`/
:class:`~lup.adapters.clients.Client.Session` ABCs — pure interfaces —
:class:`ResponseCollector` is a template: the walk, the display, and the
message→response projection are written here once so no two engines
re-walk the stream and drift.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from lup.telemetry.display import print_message
from lup.telemetry.trace import TraceLogger
from lup.types import (
    LupAssistantMessage,
    LupMessage,
    LupResponse,
    LupTextBlock,
    LupUserMessage,
)


# lup: Reread tacocast again. Mix of concern of specific method (e.g. text) and abstract methods. More importantly, this feels like a building block that should go in its own nested folder, with the building block it's serving. It doesn't feel like Collector.py belongs top-level to client
class ResponseCollector[MessageT](ABC):
    """Drains one turn's native message stream into a ``LupResponse``.

    The shared response-path seam, a template around three engine hooks.
    :meth:`collect` drains the engine's native messages through
    :meth:`drain` — which accumulates the engine's terminal state — turns
    each into a lup message via :meth:`to_lup_message` that it both keeps
    and hands to :func:`~lup.telemetry.display.print_message` (the sole display/trace
    point on the run path), then projects the kept messages into a
    backend-neutral ``LupResponse`` that :meth:`finalize` stamps the
    engine's result and session id onto.

    Generic over the engine's native message type, so a reader sees what
    one turn yields. The Claude path (``claude`` and, through
    it, ``claude-compat``) conforms. The Codex path keeps its own
    projection (``build_lup_response``): a completed ``TurnResult`` has no
    live message stream, and its ``LupResponse.blocks`` must carry the
    tool-result blocks that :func:`~lup.adapters.clients.fallbacks.replay_stream`
    reconstructs events from
    — a shape Claude's live stream does not share — so conforming it waits
    on reworking the stream replay.
    """

    def __init__(
        self, *, trace_logger: TraceLogger | None = None, prefix: str = ""
    ) -> None:
        self.trace_logger = trace_logger
        self.prefix = prefix
        self.messages: list[LupAssistantMessage | LupUserMessage] = []

    @property
    def text(self) -> str | None:
        """Concatenated text of every accumulated assistant text block.

        Readable mid-stream and after an error raise, from whatever was
        drained before the failure."""
        texts = [
            block.text
            for message in self.messages
            if isinstance(message, LupAssistantMessage)
            for block in message.content
            if isinstance(block, LupTextBlock)
        ]
        return "\n\n".join(texts) if texts else None

    @abstractmethod
    def drain(self) -> AsyncIterator[MessageT]:
        """Yield each native message, accumulating the engine terminal state.

        Implementations raise here on an engine error result — after
        recording and tracing it — so a consumer of :meth:`collect` sees
        the failure and the trace keeps what went wrong.
        """

    @abstractmethod
    def to_lup_message(self, message: MessageT) -> LupMessage | None:
        """Project one native message to a lup message.

        Returns ``None`` for native messages with no display/projection
        equivalent (stream events, terminal results).
        """

    @abstractmethod
    def finalize(self, response: LupResponse) -> None:
        """Stamp the engine's terminal result and session id onto ``response``."""

    async def collect(self) -> LupResponse:
        """Drain every message — displaying and tracing each — then project."""
        async for message in self.drain():
            match self.to_lup_message(message):
                case LupAssistantMessage() | LupUserMessage() as lup_message:
                    self.messages.append(lup_message)
                    print_message(
                        lup_message, prefix=self.prefix, trace=self.trace_logger
                    )
                case _:
                    pass
        return self.to_lup_response()

    def to_lup_response(self) -> LupResponse:
        """Project the accumulated lup messages into a ``LupResponse``.

        Assistant-message blocks land in ``blocks``, tool-result blocks in
        ``tool_results``, and each message is kept in order in ``messages``;
        :meth:`finalize` then adds the engine's terminal result.
        """
        response = LupResponse()
        for message in self.messages:
            match message:
                case LupAssistantMessage():
                    response.messages.append(message)
                    response.blocks.extend(message.content)
                case LupUserMessage() if isinstance(message.content, list):
                    response.messages.append(message)
                    response.tool_results.extend(message.content)
        self.finalize(response)
        return response
