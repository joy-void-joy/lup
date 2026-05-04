"""Tests for Claude SDK → lup type conversion."""

from claude_agent_sdk import TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock
from claude_agent_sdk.types import AssistantMessage, ResultMessage, SystemMessage, UserMessage

from lup.lib.adapters.claude import claude_block_to_lup, claude_message_to_lup
from lup.lib.types import (
    LupAssistantMessage,
    LupSystemMessage,
    LupTextBlock,
    LupThinkingBlock,
    LupToolResultBlock,
    LupToolUseBlock,
    LupUserMessage,
)


class TestClaudeBlockToLup:
    def test_text_block(self) -> None:
        block = TextBlock(text="hello world")
        result = claude_block_to_lup(block)
        assert isinstance(result, LupTextBlock)
        assert result.text == "hello world"
        assert result.type == "text"

    def test_thinking_block(self) -> None:
        block = ThinkingBlock(thinking="let me consider...", signature="sig")
        result = claude_block_to_lup(block)
        assert isinstance(result, LupThinkingBlock)
        assert result.thinking == "let me consider..."
        assert result.type == "thinking"

    def test_tool_use_block(self) -> None:
        block = ToolUseBlock(
            id="toolu_123",
            name="WebSearch",
            input={"query": "python async"},
        )
        result = claude_block_to_lup(block)
        assert isinstance(result, LupToolUseBlock)
        assert result.id == "toolu_123"
        assert result.name == "WebSearch"
        assert result.input == {"query": "python async"}
        assert result.type == "tool_use"

    def test_tool_use_block_empty_input(self) -> None:
        block = ToolUseBlock(id="toolu_456", name="Noop", input={})
        result = claude_block_to_lup(block)
        assert isinstance(result, LupToolUseBlock)
        assert result.input == {}

    def test_tool_result_block(self) -> None:
        block = ToolResultBlock(
            tool_use_id="toolu_123",
            content="search results here",
        )
        result = claude_block_to_lup(block)
        assert isinstance(result, LupToolResultBlock)
        assert result.tool_use_id == "toolu_123"
        assert result.content == "search results here"
        assert result.type == "tool_result"

    def test_tool_result_block_none_content(self) -> None:
        block = ToolResultBlock(tool_use_id="toolu_789", content=None)
        result = claude_block_to_lup(block)
        assert isinstance(result, LupToolResultBlock)
        assert result.content is None

    def test_empty_text_block(self) -> None:
        block = TextBlock(text="")
        result = claude_block_to_lup(block)
        assert isinstance(result, LupTextBlock)
        assert result.text == ""


class TestClaudeMessageToLup:
    def test_assistant_message(self) -> None:
        msg = AssistantMessage(
            model="claude-opus-4-6",
            content=[
                ThinkingBlock(thinking="reasoning", signature="sig"),
                TextBlock(text="Here is my answer"),
            ],
        )
        result = claude_message_to_lup(msg)
        assert isinstance(result, LupAssistantMessage)
        assert result.role == "assistant"
        assert len(result.content) == 2
        assert isinstance(result.content[0], LupThinkingBlock)
        assert isinstance(result.content[1], LupTextBlock)

    def test_assistant_message_empty_content(self) -> None:
        msg = AssistantMessage(model="claude-opus-4-6", content=[])
        result = claude_message_to_lup(msg)
        assert isinstance(result, LupAssistantMessage)
        assert result.content == []

    def test_user_message_with_blocks(self) -> None:
        msg = UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="toolu_abc",
                    content="result data",
                )
            ]
        )
        result = claude_message_to_lup(msg)
        assert isinstance(result, LupUserMessage)
        assert result.role == "user"
        assert len(result.content) == 1
        assert isinstance(result.content[0], LupToolResultBlock)

    def test_user_message_with_string(self) -> None:
        msg = UserMessage(content="plain text input")
        result = claude_message_to_lup(msg)
        assert isinstance(result, LupUserMessage)
        assert result.content == "plain text input"

    def test_system_message(self) -> None:
        msg = SystemMessage(subtype="init", data={"status": "session started"})
        result = claude_message_to_lup(msg)
        assert isinstance(result, LupSystemMessage)
        assert result.role == "system"
        assert result.subtype == "init"
        assert result.data == '{"status": "session started"}'

    def test_system_message_dict_data(self) -> None:
        msg = SystemMessage(subtype="status", data={"phase": "running"})
        result = claude_message_to_lup(msg)
        assert isinstance(result, LupSystemMessage)
        assert result.data == '{"phase": "running"}'

    def test_result_message_returns_none(self) -> None:
        msg = ResultMessage(
            subtype="result",
            duration_ms=1234,
            duration_api_ms=1000,
            is_error=False,
            num_turns=3,
            session_id="sess_123",
            result="done",
            total_cost_usd=0.05,
            usage={"input_tokens": 100, "output_tokens": 50},
        )
        result = claude_message_to_lup(msg)
        assert result is None


class TestCodexItemsToLup:
    """Test Codex SDK ThreadItem → lup type conversion using real SDK types."""

    def test_agent_message_final_answer(self) -> None:
        from codex_app_server import ThreadItem
        from codex_app_server.generated.v2_all import (
            AgentMessageThreadItem,
            MessagePhase,
        )
        from lup.lib.adapters.codex import codex_items_to_lup

        item = ThreadItem(
            root=AgentMessageThreadItem(
                id="msg_1",
                text="The answer is 42.",
                phase=MessagePhase.final_answer,
                type="agentMessage",
            )
        )
        blocks = codex_items_to_lup([item])
        assert len(blocks) == 1
        assert isinstance(blocks[0], LupTextBlock)
        assert blocks[0].text == "The answer is 42."

    def test_agent_message_commentary(self) -> None:
        from codex_app_server import ThreadItem
        from codex_app_server.generated.v2_all import (
            AgentMessageThreadItem,
            MessagePhase,
        )
        from lup.lib.adapters.codex import codex_items_to_lup

        item = ThreadItem(
            root=AgentMessageThreadItem(
                id="msg_2",
                text="Let me think about this...",
                phase=MessagePhase.commentary,
                type="agentMessage",
            )
        )
        blocks = codex_items_to_lup([item])
        assert len(blocks) == 1
        assert isinstance(blocks[0], LupThinkingBlock)
        assert blocks[0].thinking == "Let me think about this..."

    def test_command_execution(self) -> None:
        from codex_app_server import ThreadItem
        from codex_app_server.generated.v2_all import (
            AbsolutePathBuf,
            CommandExecutionStatus,
            CommandExecutionThreadItem,
        )
        from lup.lib.adapters.codex import codex_items_to_lup

        item = ThreadItem(
            root=CommandExecutionThreadItem(
                id="cmd_1",
                command="ls -la",
                command_actions=[],
                cwd=AbsolutePathBuf(root="/home/user"),
                exit_code=0,
                aggregated_output="total 8\ndrwxr-xr-x ...",
                status=CommandExecutionStatus.completed,
                type="commandExecution",
            )
        )
        blocks = codex_items_to_lup([item])
        assert len(blocks) == 2
        assert isinstance(blocks[0], LupToolUseBlock)
        assert blocks[0].name == "command_execution"
        assert blocks[0].input == {"command": "ls -la", "cwd": "/home/user"}
        assert isinstance(blocks[1], LupToolResultBlock)
        assert "total 8" in (blocks[1].content or "")

    def test_mcp_tool_call(self) -> None:
        from codex_app_server import ThreadItem
        from codex_app_server.generated.v2_all import (
            McpToolCallResult,
            McpToolCallStatus,
            McpToolCallThreadItem,
        )
        from lup.lib.adapters.codex import codex_items_to_lup

        item = ThreadItem(
            root=McpToolCallThreadItem(
                id="mcp_1",
                server="lup-tools",
                tool="reflect",
                arguments={"content": "my reflection"},
                status=McpToolCallStatus.completed,
                result=McpToolCallResult(
                    content=[{"type": "text", "text": "reflected"}],
                ),
                type="mcpToolCall",
            )
        )
        blocks = codex_items_to_lup([item])
        assert len(blocks) == 2
        assert isinstance(blocks[0], LupToolUseBlock)
        assert blocks[0].name == "mcp__lup-tools__reflect"
        assert blocks[0].input == {"content": "my reflection"}
        assert isinstance(blocks[1], LupToolResultBlock)

    def test_reasoning_item(self) -> None:
        from codex_app_server import ThreadItem
        from codex_app_server.generated.v2_all import ReasoningThreadItem
        from lup.lib.adapters.codex import codex_items_to_lup

        item = ThreadItem(
            root=ReasoningThreadItem(
                id="reason_1",
                content=["Step 1: analyze", "Step 2: decide"],
                summary=["Analyzed and decided"],
                type="reasoning",
            )
        )
        blocks = codex_items_to_lup([item])
        assert len(blocks) == 1
        assert isinstance(blocks[0], LupThinkingBlock)
        assert "Step 1: analyze" in blocks[0].thinking
        assert "Step 2: decide" in blocks[0].thinking
