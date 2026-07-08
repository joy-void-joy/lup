"""The Claude implementation of the response-collector template.

Drains the live SDK message stream into a ``LupResponse`` through the
shared :class:`~lup.adapters.clients.Collector.ResponseCollector` walk.
"""

import logging
from collections.abc import AsyncIterator, Callable, Mapping

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.adapters.clients.claude.messages import claude_message_to_lup
from lup.adapters.clients.Collector import ResponseCollector
from lup.adapters.clients.usage import extract_token_usage, safe_normalize_usage
from lup.telemetry.trace import TraceLogger
from lup.types import (
    JsonValue,
    LupMessage,
    LupResponse,
    LupResultMessage,
    Usage,
)

logger = logging.getLogger(__name__)

type ClaudeUsageNormalizer = Callable[[Mapping[str, JsonValue]], Usage | None]
"""Transforms the raw Claude SDK usage payload into a (subclass of) Usage."""


class ClaudeResponseCollector(ResponseCollector[claude.Message]):
    """The Claude implementation of the response-collector seam.

    Drains the live SDK message stream: :meth:`drain` accumulates the
    terminal ``ResultMessage`` and, on an error result, logs and traces it
    before raising mid-stream so the failure surfaces. Each SDK message
    becomes a lup message through
    :func:`~lup.adapters.clients.claude.messages.claude_message_to_lup`
    for display and the shared projection, and :meth:`finalize` shapes the
    terminal result — ``usage_normalizer`` normalizes the raw SDK usage
    payload, a subclass of which may carry vendor-specific fields.
    """

    def __init__(
        self,
        client: claude.ClaudeSDKClient,
        *,
        usage_normalizer: "ClaudeUsageNormalizer" = extract_token_usage,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> None:
        super().__init__(trace_logger=trace_logger, prefix=prefix)
        self.client = client
        self.usage_normalizer = usage_normalizer
        self.result: claude_types.ResultMessage | None = None

    async def drain(self) -> AsyncIterator[claude.Message]:
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

    def to_lup_message(self, message: claude.Message) -> LupMessage | None:
        return claude_message_to_lup(message)

    def finalize(self, response: LupResponse) -> None:
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
