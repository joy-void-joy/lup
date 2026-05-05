"""Claude SDK background agent implementation."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
)

from lup.lib.adapters.claude import lup_tools_to_sdk
from lup.lib.background import BaseBackgroundAgent
from lup.lib.mcp import LupMcpTool

logger = logging.getLogger(__name__)


class ClaudeBackgroundAgent(BaseBackgroundAgent):
    """Background agent running via the Claude Agent SDK.

    Runs an independent SDK client with its own MCP tools and system
    prompt. Communicates with the main agent through shared mutable
    state — the background agent's tools write to objects (lists, dicts)
    that the main agent's tools read.
    """

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        tools: list[LupMcpTool],
        build_message: Callable[[], str | None],
        start_message: str = "",
        model: str = "claude-sonnet-4-20250514",
        max_thinking_tokens: int | None = None,
        debounce_seconds: float = 3.0,
        builtin_tools: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        on_response: Callable[[AssistantMessage], None] | None = None,
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

    async def message_generator(self) -> AsyncGenerator[dict[str, object], None]:
        """Yield user turns: start message, then build_message on each wake."""
        yield {
            "type": "user",
            "message": {"role": "user", "content": self.start_message},
        }

        while self._running:
            await self._wake.wait()
            self._wake.clear()

            while True:
                try:
                    await asyncio.wait_for(
                        self._wake.wait(), timeout=self.debounce_seconds
                    )
                    self._wake.clear()
                except TimeoutError:
                    break

            content = self.build_message()
            if content is None:
                continue

            yield {
                "type": "user",
                "message": {"role": "user", "content": content},
            }

    async def run_loop(self) -> None:
        """Create SDK client, connect with message generator, process responses."""
        sdk_tools = lup_tools_to_sdk(self.tools)
        server = create_sdk_mcp_server(
            name=self.name,
            version="1.0.0",
            tools=sdk_tools,
        )

        options = ClaudeAgentOptions(
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
            client = ClaudeSDKClient(options=options)
            await client.connect(self.message_generator())
            try:
                async for msg in client.receive_messages():
                    self.handle_response(msg)
            finally:
                await client.disconnect()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Background agent '%s' crashed", self.name)

    def handle_response(self, msg: object) -> None:
        """Route response messages for logging."""
        match msg:
            case AssistantMessage():
                if self.on_response:
                    self.on_response(msg)
            case ResultMessage():
                if msg.is_error:
                    logger.error(
                        "Background agent '%s' error: %s", self.name, msg.result
                    )
