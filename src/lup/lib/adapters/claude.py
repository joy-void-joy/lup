"""Claude Agent SDK adapter.

Owns all Claude-specific logic: option building, MCP server setup,
type conversion, and the adapter class that runs prompts via
``ClaudeSDKClient``.

Consumer code (core.py) imports ``ClaudeAdapter`` and the setup
functions — never ``claude_agent_sdk`` directly.
"""

import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Literal, cast

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ContentBlock,
    Message,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import (
    AssistantMessage,
    HookEvent,
    HookMatcher,
    McpServerConfig,
    McpSdkServerConfig,
    ResultMessage,
    SystemMessage,
    UserMessage,
)

from lup.lib.adapters.common import (
    AgentAdapter,
    LupDoneEvent,
    LupEvent,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
)
from lup.lib.trace import TraceLogger, print_message
from lup.lib.types import (
    LupAssistantMessage,
    LupContentBlock,
    LupMessage,
    LupResponse,
    LupResultMessage,
    LupSystemMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type conversion: Claude SDK → lup types
# ---------------------------------------------------------------------------


def claude_block_to_lup(block: ContentBlock) -> LupContentBlock:
    """Convert a Claude SDK ContentBlock to a LupContentBlock."""
    match block:
        case ThinkingBlock():
            return LupThinkingBlock(thinking=block.thinking)
        case TextBlock():
            return LupTextBlock(text=block.text)
        case ToolUseBlock():
            return LupToolUseBlock(id=block.id, name=block.name, input=block.input)
        case ToolResultBlock():
            return LupToolResultBlock(
                tool_use_id=block.tool_use_id, content=block.content
            )


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
            data = json.dumps(message.data) if isinstance(message.data, dict) else str(message.data)
            return LupSystemMessage(subtype=message.subtype, data=data)
        case ResultMessage():
            return None
        case _:
            return None


# ---------------------------------------------------------------------------
# Setup functions (extracted from core.py)
# ---------------------------------------------------------------------------


def build_agent_servers(
    *,
    session_dir: Path,
    outputs_dir: Path | None = None,
    sandbox: object | None = None,
    gate: object | None = None,
) -> dict[str, McpServerConfig]:
    """Create the agent's core MCP servers, passed through ToolPolicy.

    Args:
        session_dir: Directory for reflection tool output.
        outputs_dir: Past outputs for reviewer calibration.
        sandbox: Initialized Sandbox instance.
        gate: External ReflectionGate for the reflect tools.
    """
    from lup.agent.config import settings
    from lup.agent.tool_policy import ToolPolicy
    from lup.agent.tools.example import EXAMPLE_TOOLS
    from lup.agent.tools.reflect import create_reflect_tools
    from lup.lib.mcp import create_mcp_server, extract_sdk_tools
    from lup.lib.reflect import ReflectionGate

    resolved_gate = gate if isinstance(gate, ReflectionGate) else ReflectionGate()

    example_server = create_mcp_server(
        name="example",
        version="1.0.0",
        tools=extract_sdk_tools(EXAMPLE_TOOLS),
    )

    reflect_kit = create_reflect_tools(
        session_dir=session_dir,
        outputs_dir=outputs_dir,
        gate=resolved_gate,
    )
    reflect_server = create_mcp_server(
        name="notes",
        version="1.0.0",
        tools=extract_sdk_tools(reflect_kit["tools"]),
    )

    all_servers: list[McpSdkServerConfig] = [example_server, reflect_server]
    if sandbox is not None:
        from lup.lib.sandbox import Sandbox

        if isinstance(sandbox, Sandbox):
            all_servers.append(sandbox.create_mcp_server())

    policy = ToolPolicy.from_settings(settings)
    return policy.get_mcp_servers(*all_servers)


def build_options(
    notes_config: object,
    *,
    sandbox: object | None = None,
) -> ClaudeAgentOptions:
    """Build ClaudeAgentOptions from settings and notes config."""
    from lup.agent.config import settings
    from lup.agent.models import AgentOutput
    from lup.agent.prompts import get_system_prompt
    from lup.agent.subagents import get_subagents
    from lup.agent.tool_policy import ToolPolicy
    from lup.lib.hooks import create_permission_hooks, merge_hooks
    from lup.lib.notes import NotesConfig
    from lup.lib.reflect import ReflectionGate, create_reflection_gate

    if not isinstance(notes_config, NotesConfig):
        raise TypeError(f"Expected NotesConfig, got {type(notes_config).__name__}")

    gate = ReflectionGate()
    servers = build_agent_servers(
        session_dir=notes_config.session,
        outputs_dir=notes_config.output.parent,
        sandbox=sandbox,
        gate=gate,
    )

    permission_hooks = create_permission_hooks(notes_config.rw, notes_config.ro)
    gate_hooks = create_reflection_gate(
        gate=gate,
        gated_tool="StructuredOutput",
        reflection_tool_name="mcp__notes__review",
    )
    hooks = merge_hooks(permission_hooks, gate_hooks)

    policy = ToolPolicy.from_settings(settings)

    return ClaudeAgentOptions(
        model=settings.model,
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": get_system_prompt(),
        },
        max_thinking_tokens=settings.max_thinking_tokens or (128_000 - 1),
        permission_mode="bypassPermissions",
        extra_args={"no-session-persistence": None},
        hooks=hooks,
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
        },
        mcp_servers=servers,
        agents=get_subagents(),
        add_dirs=[str(d) for d in notes_config.all_dirs],
        allowed_tools=policy.get_allowed_tools(),
        output_format={
            "type": "json_schema",
            "schema": AgentOutput.model_json_schema(),
        },
        effort=cast(
            Literal["low", "medium", "high", "max"] | None,
            settings.reasoning_effort,
        ),
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ClaudeAdapter(AgentAdapter):
    """Run prompts via the Claude Agent SDK."""

    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options

    async def run(
        self,
        prompt: str,
        *,
        trace_logger: TraceLogger | None = None,
        prefix: str = "",
    ) -> LupResponse:
        response = LupResponse()

        async with ClaudeSDKClient(options=self.options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
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
                            usage=message.usage,
                        )
                        if message.is_error:
                            raise RuntimeError(f"Agent error: {message.result}")

                    case SystemMessage():
                        logger.info(
                            "System [%s]: %s", message.subtype, message.data
                        )

                    case UserMessage():
                        if isinstance(message.content, list):
                            lup_user = LupUserMessage(
                                content=[
                                    claude_block_to_lup(b)
                                    for b in message.content
                                ]
                            )
                            response.messages.append(lup_user)
                            for block in message.content:
                                response.tool_results.append(
                                    claude_block_to_lup(block)
                                )

        if response.result is None:
            raise RuntimeError("No result received from agent")

        return response

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
                                    yield LupThinkingEvent(thinking=block.thinking)
                                case TextBlock():
                                    yield LupTextEvent(text=block.text)
                                case ToolUseBlock():
                                    yield LupToolUseEvent(
                                        id=block.id, name=block.name
                                    )
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
