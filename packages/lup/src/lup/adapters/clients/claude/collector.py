"""The Claude response path: one turn's SDK message stream into a ``LupResponse``.

The walk, the display, and the message→response projection for the
Claude engine (and, through it, ``claude-compat``). The Codex path keeps
its own projection
(:func:`~lup.adapters.clients.codex.messages.build_lup_response`): a
completed ``TurnResult`` has no live message stream to drain, and its
``LupResponse.blocks`` carries tool-result blocks inline — a shape this
walk deliberately does not produce.
"""

import logging
from collections.abc import AsyncIterator, Callable, Mapping

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.adapters.clients.claude.messages import claude_message_to_lup
from lup.adapters.clients.usage import extract_token_usage, safe_normalize_usage
from lup.telemetry.display import print_message
from lup.telemetry.trace import TraceLogger
from lup.types import (
    JsonValue,
    LupAssistantMessage,
    LupResponse,
    LupResultMessage,
    LupTextBlock,
    LupUserMessage,
    Usage,
)

logger = logging.getLogger(__name__)

type ClaudeUsageNormalizer = Callable[[Mapping[str, JsonValue]], Usage | None]
"""Transforms the raw Claude SDK usage payload into a (subclass of) Usage."""


class ClaudeResponseCollector:
    """Drains one turn's live SDK message stream into a ``LupResponse``.

    :meth:`collect` drains the stream through :meth:`drain` — which
    accumulates the terminal ``ResultMessage`` and, on an error result,
    logs and traces it before raising mid-stream so the failure surfaces —
    projects each SDK message through
    :func:`~lup.adapters.clients.claude.messages.claude_message_to_lup`,
    keeps it, and hands it to :func:`~lup.telemetry.display.print_message`
    (the sole display/trace point on the run path), then folds the kept
    messages into a backend-neutral ``LupResponse`` stamped with the
    terminal result — ``usage_normalizer`` normalizes the raw SDK usage
    payload, a subclass of which may carry vendor-specific fields.
    """

    def __init__(
        self,
        client: claude.ClaudeSDKClient,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> None:
        self.client = client
        self.usage_normalizer = usage_normalizer
        self.trace_logger = trace_logger
        self.prefix = prefix
        self.messages: list[LupAssistantMessage | LupUserMessage] = []
        self.result: claude_types.ResultMessage | None = None

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

    async def drain(self) -> AsyncIterator[claude.Message]:
        """Yield each SDK message, accumulating the terminal ``ResultMessage``.

        Raises on an error result — after recording and tracing it — so a
        consumer sees the failure and the trace keeps what went wrong.
        """
        async for message in self.client.receive_response():
            match message:
                case claude_types.ResultMessage():
                    self.result = message
                    if message.is_error:
                        logger.error("Agent error result: %s", message.result)
                        if self.trace_logger:
                            self.trace_logger.log_text(
                                str(message.result), heading="Agent error result"
                            )
                case claude_types.SystemMessage():
                    logger.info("System [%s]: %s", message.subtype, message.data)

            yield message

            if isinstance(message, claude_types.ResultMessage) and message.is_error:
                raise RuntimeError(f"Agent error: {message.result}")

    async def collect(self) -> LupResponse:
        """Drain every message — displaying and tracing each — then project."""
        async for message in self.drain():
            match claude_message_to_lup(message):
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
        ``tool_results``, and each message is kept in order in
        ``messages``; the terminal result and session id are stamped on
        from the drained ``ResultMessage``.
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
        if self.result is None:
            raise RuntimeError("No result received from agent")
        response.session_id = self.result.session_id
        response.result = LupResultMessage(
            structured_output=self.result.structured_output,
            is_error=self.result.is_error,
            result=self.result.result,
            duration_ms=self.result.duration_ms,
            total_cost_usd=self.result.total_cost_usd,
            usage=safe_normalize_usage(self.usage_normalizer, self.result.usage),
        )
        return response
