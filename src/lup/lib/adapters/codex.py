"""OpenAI Codex SDK adapter.

Wraps the Codex Python SDK (``codex_app_server``) behind the
``AgentAdapter`` interface. On the Codex path, lup features that
require in-process hooks or MCP servers (reflection gate, custom
tools, subagents) are not available — the agent runs with built-in
Codex tools only.

Install the Codex SDK to use this adapter::

    uv add --optional codex openai-codex-app-server-sdk
"""

import json
import logging

from lup.lib.adapters.common import AgentAdapter
from lup.lib.trace import TraceLogger
from lup.lib.types import (
    LupResponse,
    LupResultMessage,
    LupTextBlock,
)

logger = logging.getLogger(__name__)


def require_codex_sdk() -> None:
    """Raise a clear error if the Codex SDK is not installed."""
    try:
        import codex_app_server as _  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Codex SDK not installed. Install with: "
            "uv add --optional codex openai-codex-app-server-sdk"
        ) from exc


class CodexAdapter(AgentAdapter):
    """Run prompts via the OpenAI Codex SDK."""

    def __init__(
        self,
        *,
        model: str,
        system_prompt: str,
        output_schema: dict[str, object] | None = None,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.output_schema = output_schema

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        require_codex_sdk()

        from codex_app_server import AsyncCodex

        async with AsyncCodex() as codex:
            thread = await codex.thread_start(
                model=self.model,
                developer_instructions=self.system_prompt,
            )

            result = await thread.run(prompt)

            structured_output: dict[str, object] | None = None
            if result.final_response and self.output_schema:
                try:
                    structured_output = json.loads(result.final_response)
                except (json.JSONDecodeError, TypeError):
                    pass

            text_block = LupTextBlock(text=result.final_response or "")
            if trace_logger and result.final_response:
                trace_logger.log_text(result.final_response, heading="Response")

            result_usage: dict[str, int] | None = None
            if result.usage is not None:
                result_usage = {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                }

            return LupResponse(
                blocks=[text_block] if result.final_response else [],
                result=LupResultMessage(
                    structured_output=structured_output,
                    result=result.final_response,
                    usage=result_usage,
                ),
            )
