"""Claude Agent SDK adapter.

Owns all Claude-specific logic: option building, MCP server setup,
type conversion, and the adapter class that runs prompts via
``ClaudeSDKClient``.

Consumer code (core.py) imports ``ClaudeAdapter`` and the setup
functions — never ``claude_agent_sdk`` directly.
"""

import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, Literal, cast  # claude: ignore

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ContentBlock,
    HookInput,
    Message,
    SdkMcpTool,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import (
    AgentDefinition,
    AssistantMessage,
    HookContext,
    HookEvent,
    HookMatcher,
    McpSdkServerConfig,
    PreToolUseHookSpecificOutput,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    SyncHookJSONOutput,
    SystemMessage,
    UserMessage,
)

from lup.adapters.common import (
    AgentAdapter,
    Conversation,
    LupDoneEvent,
    LupEvent,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
)
from lup.mcp import LupMcpServerConfig, LupMcpTool
from lup.trace import TraceLogger, print_message
from lup.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupHookInput,
    LupHookMatcher,
    LupHookOutput,
    LupHooksConfig,
    LupMessage,
    LupResponse,
    LupResultMessage,
    LupSystemMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
    SubagentSpec,
    Usage,
    extract_token_usage,
    safe_normalize_usage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LupHooksConfig → Claude SDK HooksConfig
# ---------------------------------------------------------------------------

type ClaudeHooksConfig = dict[HookEvent, list[HookMatcher]]


def build_claude_hook_handler(
    lup_matcher: LupHookMatcher,
) -> Callable[[HookInput, str | None, HookContext], Awaitable[SyncHookJSONOutput]]:
    """Build a Claude SDK hook handler from a LupHookMatcher."""
    hook_fn = lup_matcher.hook

    async def claude_hook(
        input_data: HookInput,
        _tool_use_id: str | None,
        _context: HookContext,
    ) -> SyncHookJSONOutput:
        lup_input = LupHookInput(
            hook_event_name=input_data.get("hook_event_name", ""),
            tool_name=input_data.get("tool_name", ""),
            tool_input=input_data.get("tool_input", {}),
        )
        if "stop_hook_active" in input_data:
            lup_input["stop_hook_active"] = input_data["stop_hook_active"]

        lup_output = await hook_fn(lup_input)
        return lup_hook_output_to_claude(lup_output)

    return claude_hook


def lup_hooks_to_claude(hooks: LupHooksConfig) -> ClaudeHooksConfig:
    """Convert SDK-agnostic LupHooksConfig to Claude SDK hook format."""
    result: ClaudeHooksConfig = {}

    for event_name, matchers in hooks.items():
        claude_matchers: list[HookMatcher] = []
        for lup_matcher in matchers:
            handler = build_claude_hook_handler(lup_matcher)
            if lup_matcher.matcher:
                claude_matchers.append(
                    HookMatcher(matcher=lup_matcher.matcher, hooks=[handler])
                )
            else:
                claude_matchers.append(HookMatcher(hooks=[handler]))

        result[cast(HookEvent, event_name)] = claude_matchers

    return result


def lup_hook_output_to_claude(output: LupHookOutput) -> SyncHookJSONOutput:
    """Convert a LupHookOutput to Claude SDK SyncHookJSONOutput."""
    decision = output.get("decision")
    reason = output.get("reason", "")
    system_message = output.get("system_message")

    match decision:
        case "allow":
            return SyncHookJSONOutput(
                hookSpecificOutput=PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="allow",
                )
            )
        case "deny":
            return SyncHookJSONOutput(
                hookSpecificOutput=PreToolUseHookSpecificOutput(
                    hookEventName="PreToolUse",
                    permissionDecision="deny",
                    permissionDecisionReason=reason,
                )
            )
        case "block":
            return SyncHookJSONOutput(decision="block", reason=reason)
        case _:
            if system_message:
                return SyncHookJSONOutput(systemMessage=system_message)
            return SyncHookJSONOutput()


# ---------------------------------------------------------------------------
# SubagentSpec → Claude AgentDefinition
# ---------------------------------------------------------------------------

CLAUDE_MODEL_LITERALS = {"sonnet", "opus", "haiku", "inherit"}

type ClaudeModelLiteral = Literal["sonnet", "opus", "haiku", "inherit"]


def spec_to_claude(spec: SubagentSpec) -> AgentDefinition:
    """Convert a SubagentSpec to a Claude AgentDefinition."""
    model: ClaudeModelLiteral | None = None
    if spec.model in CLAUDE_MODEL_LITERALS:
        model = cast(ClaudeModelLiteral, spec.model)

    return AgentDefinition(
        description=spec.description,
        prompt=spec.prompt,
        tools=spec.tools,
        model=model,
    )


# ---------------------------------------------------------------------------
# Type conversion: Claude SDK → lup types
# ---------------------------------------------------------------------------


def claude_block_to_lup(block: ContentBlock) -> LupContentBlock:
    """Convert a Claude SDK ContentBlock to a LupContentBlock."""
    if hasattr(block, "type") and getattr(block, "type", None) == "redacted_thinking":
        return LupThinkingBlock(thinking="", redacted=True)

    match block:
        case ThinkingBlock():
            is_redacted = not block.thinking and bool(block.signature)
            return LupThinkingBlock(thinking=block.thinking or "", redacted=is_redacted)
        case TextBlock():
            return LupTextBlock(text=block.text)
        case ToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case ToolResultBlock():
            return LupToolResultBlock(
                tool_use_id=block.tool_use_id, content=block.content
            )
        case ServerToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case ServerToolResultBlock():
            content = (
                block.content if isinstance(block.content, str) else str(block.content)
            )
            return LupToolResultBlock(tool_use_id=block.tool_use_id, content=content)
        case _:
            return LupTextBlock(text=str(block))


def claude_message_to_lup(message: Message) -> LupMessage | None:
    """Convert a Claude SDK Message to a LupMessage.

    Returns None for message types that have no lup equivalent
    (e.g. stream events).
    """
    match message:
        case AssistantMessage():
            blocks = [claude_block_to_lup(b) for b in message.content]
            return LupAssistantMessage(content=blocks)
        case UserMessage():
            if isinstance(message.content, list):
                blocks = [claude_block_to_lup(b) for b in message.content]
                return LupUserMessage(content=blocks)
            return LupUserMessage(content=message.content)
        case SystemMessage():
            data = (
                json.dumps(message.data)
                if isinstance(message.data, dict)
                else str(message.data)
            )
            return LupSystemMessage(subtype=message.subtype, data=data)
        case ResultMessage():
            return None
        case _:
            return None


# ---------------------------------------------------------------------------
# MCP server conversion
# ---------------------------------------------------------------------------


def lup_server_to_claude(config: LupMcpServerConfig) -> McpSdkServerConfig:
    """Convert a LupMcpServerConfig to a Claude SDK McpSdkServerConfig."""
    return McpSdkServerConfig(type="sdk", name=config.name, instance=config.server)


def lup_tools_to_sdk(
    tools: list[LupMcpTool],
) -> list[SdkMcpTool[dict[str, Any]]]:  # claude: ignore
    """Convert LupMcpTool list to Claude SDK SdkMcpTool list."""
    return [
        SdkMcpTool(
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            handler=t.handler,
        )
        for t in tools
    ]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


type ClaudeUsageNormalizer = Callable[[Mapping[str, object]], Usage | None]
"""Transforms the raw Claude SDK usage payload into a (subclass of) Usage."""


class ClaudeConversation(Conversation):
    """Multi-turn conversation via the Claude Agent SDK."""

    def __init__(
        self,
        client: ClaudeSDKClient,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
    ) -> None:
        self.client = client
        self.usage_normalizer = usage_normalizer

    async def send(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        response = LupResponse()

        await self.client.query(prompt)
        async for message in self.client.receive_response():
            lup_msg = claude_message_to_lup(message)
            if lup_msg is not None:
                print_message(lup_msg, prefix=prefix, trace=trace_logger)

            match message:
                case AssistantMessage():
                    lup_assistant = LupAssistantMessage(
                        content=[claude_block_to_lup(b) for b in message.content]
                    )
                    response.messages.append(lup_assistant)
                    for block in message.content:
                        response.blocks.append(claude_block_to_lup(block))

                case ResultMessage():
                    response.result = LupResultMessage(
                        structured_output=message.structured_output,
                        is_error=message.is_error,
                        result=message.result,
                        duration_ms=message.duration_ms,
                        total_cost_usd=message.total_cost_usd,
                        usage=safe_normalize_usage(
                            self.usage_normalizer, message.usage
                        ),
                    )
                    if message.is_error:
                        raise RuntimeError(f"Agent error: {message.result}")

                case SystemMessage():
                    logger.info("System [%s]: %s", message.subtype, message.data)

                case UserMessage():
                    if isinstance(message.content, list):
                        lup_user = LupUserMessage(
                            content=[claude_block_to_lup(b) for b in message.content]
                        )
                        response.messages.append(lup_user)
                        for block in message.content:
                            response.tool_results.append(claude_block_to_lup(block))

        if response.result is None:
            raise RuntimeError("No result received from agent")

        return response

    async def interrupt(self) -> None:
        await self.client.interrupt()


class ClaudeAdapter(AgentAdapter):
    """Run prompts via the Claude Agent SDK.

    Args:
        options: Native SDK options built by the consumer.
        usage_normalizer: Transforms the raw SDK usage payload into a
            ``Usage`` (or subclass, for vendor-specific fields).
    """

    def __init__(
        self,
        options: ClaudeAgentOptions,
        *,
        usage_normalizer: ClaudeUsageNormalizer = extract_token_usage,
    ) -> None:
        self.options = options
        self.usage_normalizer = usage_normalizer

    @asynccontextmanager
    async def conversation(self) -> AsyncGenerator[Conversation, None]:
        async with ClaudeSDKClient(options=self.options) as client:
            yield ClaudeConversation(client, usage_normalizer=self.usage_normalizer)

    async def run_streamed(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> AsyncGenerator[LupEvent, None]:
        """Stream events from the Claude SDK."""
        async with ClaudeSDKClient(options=self.options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                lup_msg = claude_message_to_lup(message)
                if lup_msg is not None and trace_logger:
                    print_message(lup_msg, prefix=prefix, trace=trace_logger)

                match message:
                    case AssistantMessage():
                        for block in message.content:
                            match block:
                                case ThinkingBlock():
                                    if block.thinking:
                                        yield LupThinkingEvent(thinking=block.thinking)
                                case TextBlock():
                                    yield LupTextEvent(text=block.text)
                                case ToolUseBlock():
                                    yield LupToolUseEvent(id=block.id, name=block.name)
                    case UserMessage():
                        if isinstance(message.content, list):
                            for block in message.content:
                                if isinstance(block, ToolResultBlock):
                                    yield LupToolResultEvent(
                                        tool_use_id=block.tool_use_id,
                                        content=str(block.content),
                                    )
                    case ResultMessage():
                        collected: list[LupContentBlock] = []
                        yield LupDoneEvent(blocks=collected)
                        if message.is_error:
                            raise RuntimeError(f"Agent error: {message.result}")


# ---------------------------------------------------------------------------
# Convenience: query() for internal use (reflect tool, etc.)
# ---------------------------------------------------------------------------

type HooksConfig = dict[HookEvent, list[HookMatcher]]
