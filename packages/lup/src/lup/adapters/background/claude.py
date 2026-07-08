"""Claude Agent SDK background agent.

Runs an independent SDK client with its own MCP tools and system prompt,
communicating with the main agent through shared mutable state. The
Claude engine's backgrounds can act through tools and default to an
opus-class model.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.adapters.background.Background import (
    BackgroundAgentParams,
    BaseBackgroundAgent,
)
from lup.adapters.clients.claude.messages import lup_tools_to_sdk
from lup.mcp import LupMcpTool
from lup.types import JsonObject

logger = logging.getLogger(__name__)


def build_claude_background(params: BackgroundAgentParams) -> BaseBackgroundAgent:
    """Build a Claude background agent — opus-class by default, tools allowed."""
    return ClaudeBackgroundAgent(
        name=params.name,
        system_prompt=params.system_prompt,
        tools=params.tools or [],
        build_message=params.build_message,
        start_message=params.start_message,
        model=params.model or "claude-opus-4-6",
        debounce_seconds=params.debounce_seconds,
        builtin_tools=params.builtin_tools,
        allowed_tools=params.allowed_tools,
        on_response=params.on_response,
    )


class ClaudeBackgroundAgent(BaseBackgroundAgent):
    """Background agent running via the Claude Agent SDK."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        tools: list[LupMcpTool],
        build_message: Callable[[], str | None],
        start_message: str = "",
        model: str = "claude-opus-4-6",
        max_thinking_tokens: int | None = None,
        debounce_seconds: float = 3.0,
        builtin_tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        on_response: Callable[[claude_types.AssistantMessage], None] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            system_prompt=system_prompt,
            build_message=build_message,
            start_message=start_message,
            model=model,
            debounce_seconds=debounce_seconds,
        )
        self.tools = tools
        self.max_thinking_tokens = max_thinking_tokens or (128_000 - 1)
        self.builtin_tools = builtin_tools
        self.allowed_tools = allowed_tools
        self.on_response = on_response

    async def sdk_message_stream(self) -> AsyncGenerator[JsonObject, None]:
        """Adapt the shared turn stream into the SDK's streaming-input dicts.

        The one place a turn becomes the SDK's ``connect`` wire shape (a
        JSON object) — the debounced loop lives on the wake loop, and only
        this boundary speaks the SDK's dict format.
        """
        async for content in self.message_stream():
            yield {
                "type": "user",
                "message": {"role": "user", "content": content},
            }

    async def run_loop(self) -> None:
        """Create SDK client, connect with message generator, process responses."""
        sdk_tools = lup_tools_to_sdk(self.tools)
        server = claude.create_sdk_mcp_server(
            name=self.name,
            version="1.0.0",
            tools=sdk_tools,
        )

        options = claude.ClaudeAgentOptions(
            model=self.model,
            system_prompt=self.system_prompt,
            max_thinking_tokens=self.max_thinking_tokens,
            permission_mode="bypassPermissions",
            tools=self.builtin_tools,
            mcp_servers={self.name: server},
            allowed_tools=self.allowed_tools or [],
            extra_args={"no-session-persistence": None},
        )

        try:
            client = claude.ClaudeSDKClient(options=options)
            await client.connect(self.sdk_message_stream())
            try:
                async for msg in client.receive_messages():
                    self.handle_response(msg)
            finally:
                await client.disconnect()
        except asyncio.CancelledError:
            logger.debug("Background agent '%s' cancelled", self.name)
        except Exception:
            logger.exception("Background agent '%s' crashed", self.name)

    def handle_response(self, msg: object) -> None:
        """Route response messages for logging."""
        match msg:
            case claude_types.AssistantMessage():
                if self.on_response:
                    self.on_response(msg)
            case claude_types.ResultMessage():
                if msg.is_error:
                    logger.error(
                        "Background agent '%s' error: %s", self.name, msg.result
                    )
