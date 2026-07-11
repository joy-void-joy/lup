"""Claude Agent SDK background driver.

Runs an independent SDK client with its own MCP tools and system prompt,
communicating with the main agent through shared mutable state. The
Claude engine's backgrounds can act through tools and default to an
opus-class model.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any  # lup: ignore[any-type] — confined to SdkDict below

import claude_agent_sdk as claude
from claude_agent_sdk import types as claude_types

from lup.adapters.background.agent import BackgroundAgent
from lup.adapters.background.BackgroundDriver import BackgroundDriver
from lup.adapters.background.params import BackgroundAgentParams
from lup.mcp import LupMcpTool, LupToolHandler
from lup.types import JsonObject

logger = logging.getLogger(__name__)

type SdkDict = dict[str, Any]  # lup: ignore[any-type] — SDK tool-handler payload


def lup_tools_to_sdk(
    tools: list[LupMcpTool],
) -> list[claude.SdkMcpTool[JsonObject]]:
    """Convert LupMcpTool list to Claude SDK SdkMcpTool list.

    ``SdkMcpTool.handler`` must return the SDK's untyped dict. A
    ``ToolResponse`` is a dict at runtime, so each handler is adapted
    with a shallow copy instead of widening ``LupToolHandler`` itself.
    """

    def as_sdk(handler: LupToolHandler) -> Callable[[JsonObject], Awaitable[SdkDict]]:
        async def call(args: JsonObject) -> SdkDict:
            return dict(await handler(args))

        return call

    return [
        claude.SdkMcpTool(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            handler=as_sdk(t.handler),
        )
        for t in tools
    ]


def build_claude_background(params: BackgroundAgentParams) -> BackgroundAgent:
    """Build a Claude background agent — opus-class by default, tools allowed."""
    driver = ClaudeBackgroundDriver(
        name=params.name,
        system_prompt=params.system_prompt,
        tools=params.tools or [],
        model=params.model or "claude-opus-4-6",
        builtin_tools=params.builtin_tools,
        allowed_tools=params.allowed_tools,
        on_response=params.on_response,
    )
    return BackgroundAgent(
        driver,
        name=params.name,
        build_message=params.build_message,
        start_message=params.start_message,
        debounce_seconds=params.debounce_seconds,
    )


class ClaudeBackgroundDriver(BackgroundDriver):
    """Drives background turns through the Claude Agent SDK."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        tools: list[LupMcpTool],
        model: str = "claude-opus-4-6",
        max_thinking_tokens: int | None = None,
        builtin_tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        on_response: Callable[[claude_types.AssistantMessage], None] | None = None,
    ) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.tools = tools
        self.max_thinking_tokens = max_thinking_tokens or (128_000 - 1)
        self.builtin_tools = builtin_tools
        self.allowed_tools = allowed_tools
        self.on_response = on_response

    async def sdk_message_stream(
        self, messages: AsyncIterator[str]
    ) -> AsyncGenerator[JsonObject, None]:
        """Adapt the turn stream into the SDK's streaming-input dicts.

        The one place a turn becomes the SDK's ``connect`` wire shape (a
        JSON object) — the debounced loop lives on the composing
        :class:`~lup.adapters.background.agent.BackgroundAgent`,
        and only this boundary speaks the SDK's dict format.
        """
        async for content in messages:
            yield {
                "type": "user",
                "message": {"role": "user", "content": content},
            }

    async def run(self, messages: AsyncIterator[str]) -> None:
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
            await client.connect(self.sdk_message_stream(messages))
            try:
                async for msg in client.receive_messages():
                    self.handle_response(msg)
            finally:
                await client.disconnect()
        except asyncio.CancelledError:
            logger.debug("Background agent '%s' cancelled", self.name)
        except Exception:
            logger.exception("Background agent '%s' crashed", self.name)

    def handle_response(self, msg: claude_types.Message) -> None:
        """Route SDK stream messages for logging."""
        match msg:
            case claude_types.AssistantMessage():
                if self.on_response:
                    self.on_response(msg)
            case claude_types.ResultMessage():
                if msg.is_error:
                    logger.error(
                        "Background agent '%s' error: %s", self.name, msg.result
                    )
