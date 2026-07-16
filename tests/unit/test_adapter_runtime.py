"""Direct regression coverage for adapter-owned runtime construction."""

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest

from lup.adapters.claude.runtime import (
    SESSION_THINKING_TOKENS,
    ClaudeConversationState,
    ClaudeFork,
    ClaudeSessionConfig,
    build_claude_options,
    claude_usage,
    convert_claude_block,
)
from lup.adapters.codex.app_server import CodexAppServer
from lup.adapters.codex.runtime import (
    CodexConversationState,
    CodexMcpServerConfig,
    CodexSessionConfig,
)
from lup.hooks import create_permission_hooks
from lup.types import SubagentSpec
from lup.runtime.models import TurnTextBlock, TurnToolCallBlock
from lup.runtime.usage import per_mtok_usage_cost
from lup.types import Usage


def test_fresh_claude_session_uses_cli_valid_uuid() -> None:
    state = ClaudeConversationState(ClaudeSessionConfig(model="claude"), None)

    assert str(UUID(state.session_id)) == state.session_id


def test_claude_session_defaults_and_hooks_reach_native_options(
    tmp_path: Path,
) -> None:
    hooks = create_permission_hooks([tmp_path / "rw"], [tmp_path / "ro"])
    options = build_claude_options(
        ClaudeSessionConfig(
            model="claude",
            system_prompt="Project rules",
            hooks=hooks,
        ),
        binding=None,
        resume=None,
        session_id="18f5debf-499a-42bb-8856-0b39dd59943d",
    )

    assert options.permission_mode == "bypassPermissions"
    assert options.max_thinking_tokens == SESSION_THINKING_TOKENS
    assert options.system_prompt == {
        "type": "preset",
        "preset": "claude_code",
        "append": "Project rules",
    }
    assert options.hooks is not None
    assert len(options.hooks["PreToolUse"]) == 1
    assert options.include_partial_messages


def test_claude_native_subagents_and_reported_cost_are_preserved() -> None:
    options = build_claude_options(
        ClaudeSessionConfig(
            model="claude",
            subagents=[
                SubagentSpec(
                    name="researcher",
                    description="Research independently",
                    prompt="Gather evidence",
                    tools=["WebSearch"],
                    model="claude-sonnet-4-6",
                )
            ],
        ),
        binding=None,
        resume=None,
        session_id="18f5debf-499a-42bb-8856-0b39dd59943d",
    )

    assert options.agents is not None
    assert options.agents["researcher"].tools == ["WebSearch"]
    assert claude_usage({}, total_cost_usd=0.75).cost_usd == 0.75


def test_codex_thread_config_contains_project_mcp_and_writable_roots(
    tmp_path: Path,
) -> None:
    config = CodexSessionConfig(
        model="gpt",
        cwd=tmp_path,
        mcp_servers={
            "notes": CodexMcpServerConfig(
                command="uv",
                args=["run", "serve-tools", "--server", "notes"],
                env={"LUP_SESSION_DIR": str(tmp_path / "session")},
            )
        },
        writable_roots=[tmp_path / "session"],
    )
    state = CodexConversationState(config, CodexAppServer(Path("codex")), None)

    parameters = state.thread_parameters()

    assert parameters["config"] == {
        "mcp_servers": {
            "notes": {
                "command": "uv",
                "args": ["run", "serve-tools", "--server", "notes"],
                "env": {"LUP_SESSION_DIR": str(tmp_path / "session")},
            }
        },
        "sandbox_workspace_write": {"writable_roots": [str(tmp_path / "session")]},
    }


def test_claude_message_and_usage_translation_has_direct_fixtures() -> None:
    import claude_agent_sdk as claude

    assert convert_claude_block(claude.TextBlock(text="hello")) == TurnTextBlock(
        text="hello"
    )
    assert convert_claude_block(
        claude.ToolUseBlock(id="call", name="Read", input={"path": "README.md"})
    ) == TurnToolCallBlock(
        id="call",
        name="Read",
        arguments={"path": "README.md"},
    )
    usage = claude_usage({"input_tokens": 20, "output_tokens": 5}, total_cost_usd=0.12)
    assert usage == Usage(input_tokens=20, output_tokens=5, cost_usd=0.12)
    assert per_mtok_usage_cost(input_usd=2, output_usd=4)(usage) == 0.00006


@pytest.mark.asyncio
async def test_claude_partial_events_are_live_and_completed_replay_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import claude_agent_sdk as claude
    from claude_agent_sdk import types as claude_types

    class FixtureClient:
        def __init__(self, options: claude.ClaudeAgentOptions) -> None:
            self.options = options

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def interrupt(self) -> None:
            return None

        async def query(self, prompt: str, session_id: str = "default") -> None:
            assert prompt == "hello"
            assert session_id

        async def receive_response(
            self,
        ) -> AsyncIterator[
            claude_types.StreamEvent
            | claude_types.AssistantMessage
            | claude_types.ResultMessage
        ]:
            yield claude_types.StreamEvent(
                uuid="event",
                session_id="session",
                event={
                    "type": "content_block_delta",
                    "delta": {"text": "hel"},
                },
            )
            yield claude_types.AssistantMessage(
                content=[claude.TextBlock(text="hello")],
                model="claude",
            )
            yield claude_types.ResultMessage(
                subtype="success",
                duration_ms=4,
                duration_api_ms=3,
                is_error=False,
                num_turns=1,
                session_id="18f5debf-499a-42bb-8856-0b39dd59943d",
                usage={"input_tokens": 2, "output_tokens": 1},
            )

    monkeypatch.setattr(claude, "ClaudeSDKClient", FixtureClient)
    state = ClaudeConversationState(ClaudeSessionConfig(model="claude"), None)

    accepted = await state.start_turn("hello")
    assert accepted.events is not None
    observed = [event async for event in accepted.events.events()]
    completed = await accepted.complete()

    assert [event.type for event in observed] == [
        "turn_started",
        "block_delta",
        "block_completed",
        "turn_completed",
    ]
    assert completed.blocks == [TurnTextBlock(text="hello")]


@pytest.mark.asyncio
async def test_claude_latest_turn_fork_preserves_a_typed_session_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import claude_agent_sdk as claude

    state = ClaudeConversationState(
        ClaudeSessionConfig(model="claude", cwd=tmp_path), None
    )

    def fork_session(
        session_id: str,
        directory: str | None = None,
        up_to_message_id: str | None = None,
        title: str | None = None,
    ) -> claude.ForkSessionResult:
        assert session_id == state.session_id
        assert directory == str(tmp_path)
        assert up_to_message_id is None
        assert title is None
        return claude.ForkSessionResult(
            session_id="18f5debf-499a-42bb-8856-0b39dd59943d"
        )

    monkeypatch.setattr(claude, "fork_session", fork_session)

    async with ClaudeFork(state).fork() as handle:
        assert handle.fork is not None
