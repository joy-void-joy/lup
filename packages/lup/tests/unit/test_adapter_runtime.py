"""Direct regression coverage for adapter-owned runtime construction."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from pydantic import BaseModel

from lup.adapters.claude.runtime import (
    SESSION_THINKING_TOKENS,
    ClaudeConversationState,
    ClaudeFork,
    ClaudeSessionConfig,
    ClaudeSessionOpener,
    ClaudeTurnToolBinder,
    SubmissionBindingSource,
    build_claude_options,
    build_submission_server,
    claude_usage,
    convert_claude_block,
)
from lup.adapters.codex.app_server import CodexAppServer, RpcMessage
from lup.adapters.codex.runtime import (
    CodexConversationState,
    CodexMcpServerConfig,
    CodexSchemaRebindingError,
    CodexSessionConfig,
    CodexSteer,
    CodexTurnToolBinder,
    decode_usage,
)
from lup.hooks import create_permission_hooks
from lup.runtime.errors import ProviderTurnError, TurnInterruptedError
from lup.types import JsonObject, JsonValue, SubagentSpec
from lup.runtime.models import (
    SubmissionDecision,
    TurnInput,
    TurnMessage,
    TurnRequest,
    TurnTextBlock,
    TurnToolBinding,
    TurnToolCallBlock,
)
from lup.runtime.output import InMemorySubmittedOutputStore
from lup.runtime.usage import per_mtok_usage_cost
from lup.types import Usage

if TYPE_CHECKING:
    import claude_agent_sdk as claude


class FirstOutput(BaseModel):
    answer: str


class SecondOutput(BaseModel):
    score: int


def test_fresh_claude_session_uses_cli_valid_uuid() -> None:
    state = ClaudeConversationState(
        ClaudeSessionOpener(ClaudeSessionConfig(model="claude")), None
    )

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
        binding=lambda: None,
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


def test_claude_isolation_knobs_reach_native_options() -> None:
    options = build_claude_options(
        ClaudeSessionConfig(
            model="claude",
            max_buffer_size=500 * 1024 * 1024,
            setting_sources=[],
            extra_args={"strict-mcp-config": None, "no-session-persistence": None},
        ),
        binding=lambda: None,
        resume=None,
        session_id="18f5debf-499a-42bb-8856-0b39dd59943d",
    )

    assert options.max_buffer_size == 500 * 1024 * 1024
    assert options.setting_sources == []
    assert options.extra_args == {
        "strict-mcp-config": None,
        "no-session-persistence": None,
    }


def test_claude_isolation_knobs_default_to_native_behavior() -> None:
    options = build_claude_options(
        ClaudeSessionConfig(model="claude"),
        binding=lambda: None,
        resume=None,
        session_id="18f5debf-499a-42bb-8856-0b39dd59943d",
    )

    assert options.max_buffer_size is None
    assert options.setting_sources is None
    assert options.extra_args == {}


def test_claude_opener_builds_options_through_an_overridable_seam() -> None:
    class IsolatedOpener(ClaudeSessionOpener):
        def build_options(
            self,
            *,
            binding: SubmissionBindingSource,
            resume: str | None,
            session_id: str | None,
        ) -> "claude.ClaudeAgentOptions":
            options = super().build_options(
                binding=binding, resume=resume, session_id=session_id
            )
            options.max_buffer_size = 4096
            return options

    opener = IsolatedOpener(ClaudeSessionConfig(model="claude"))
    state = opener.create_state(None)
    options = state.opener.build_options(
        binding=lambda: None, resume=None, session_id=state.session_id
    )

    assert state.opener is opener
    assert options.max_buffer_size == 4096


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
        binding=lambda: None,
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


async def test_thread_parameters_omit_model_for_the_native_default(
    tmp_path: Path,
) -> None:
    state = CodexConversationState(
        CodexSessionConfig(cwd=tmp_path), CodexAppServer(Path("codex")), None
    )

    assert "model" not in state.thread_parameters()


async def test_mcp_elicitation_accepts_composed_servers_declines_others(
    tmp_path: Path,
) -> None:
    config = CodexSessionConfig(
        model="gpt",
        cwd=tmp_path,
        mcp_servers={"notes": CodexMcpServerConfig(command="uv")},
    )
    state = CodexConversationState(config, CodexAppServer(Path("codex")), None)

    def elicitation(server: str) -> RpcMessage:
        return RpcMessage(
            id=7,
            method="mcpServer/elicitation/request",
            params={
                "threadId": "t1",
                "turnId": "u1",
                "serverName": server,
                "_meta": {"codex_approval_kind": "mcp_tool_call"},
            },
        )

    accepted = await state.handle_server_request(elicitation("notes"))
    declined = await state.handle_server_request(elicitation("stranger"))

    assert accepted == {"action": "accept"}
    assert declined == {"action": "decline"}


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


def test_input_tokens_are_cache_inclusive_on_both_adapters() -> None:
    claude_side = claude_usage(
        {
            "input_tokens": 10,
            "output_tokens": 3,
            "cache_read_input_tokens": 90,
            "cache_creation_input_tokens": 25,
        },
        total_cost_usd=None,
    )
    assert claude_side.input_tokens == 125
    assert claude_side.cache_read_input_tokens == 90
    assert claude_side.cache_creation_input_tokens == 25

    codex_side = decode_usage(
        {"inputTokens": 125, "cachedInputTokens": 90, "outputTokens": 3}
    )
    assert codex_side.input_tokens == claude_side.input_tokens
    assert codex_side.cache_read_input_tokens == claude_side.cache_read_input_tokens

    priced = per_mtok_usage_cost(input_usd=10.0, output_usd=0.0, cached_input_usd=1.0)
    expected = (35 * 10.0 + 90 * 1.0) / 1_000_000
    assert priced(claude_side) == pytest.approx(expected)
    assert priced(codex_side) == pytest.approx(expected)


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
    state = ClaudeConversationState(
        ClaudeSessionOpener(ClaudeSessionConfig(model="claude")), None
    )

    accepted = await state.start_turn("hello")
    assert accepted.events is not None
    observed = [event async for event in accepted.events.live()]
    completed = await accepted.complete()

    assert [event.type for event in observed] == [
        "turn_started",
        "block_delta",
        "block_completed",
        "message_completed",
        "turn_completed",
    ]
    assert completed.blocks == [TurnTextBlock(text="hello")]
    assert completed.messages == [
        TurnMessage(role="assistant", blocks=[TurnTextBlock(text="hello")])
    ]


@pytest.mark.asyncio
async def test_an_interrupted_claude_turn_is_not_a_retryable_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex reads interruption off its terminal status; Claude has none.

    Both ways of ending a turn look identical here, so the request is what
    tells them apart. Raising the provider's failure instead sent a turn the
    caller deliberately stopped back through the recovery wrapper to be run
    again.
    """
    import claude_agent_sdk as claude
    from claude_agent_sdk import types as claude_types

    class InterruptibleClient:
        def __init__(self, options: claude.ClaudeAgentOptions) -> None:
            self.options = options

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def interrupt(self) -> None:
            return None

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        async def receive_response(self) -> AsyncIterator[claude_types.ResultMessage]:
            yield claude_types.ResultMessage(
                subtype="error_during_execution",
                duration_ms=1,
                duration_api_ms=1,
                is_error=True,
                num_turns=1,
                session_id="18f5debf-499a-42bb-8856-0b39dd59943d",
                result="Turn ended early",
            )

    monkeypatch.setattr(claude, "ClaudeSDKClient", InterruptibleClient)
    state = ClaudeConversationState(
        ClaudeSessionOpener(ClaudeSessionConfig(model="claude")), None
    )

    unasked = await state.start_turn("hello")
    with pytest.raises(ProviderTurnError):
        await unasked.complete()

    asked = await state.start_turn("hello")
    assert asked.interrupt is not None
    await asked.interrupt.interrupt()
    with pytest.raises(TurnInterruptedError):
        await asked.complete()


@pytest.mark.asyncio
async def test_the_durable_view_is_the_live_one_without_its_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subset and superset of one ordering, never two disagreeing records."""
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
            return None

        async def receive_response(
            self,
        ) -> AsyncIterator[
            claude_types.StreamEvent
            | claude_types.AssistantMessage
            | claude_types.UserMessage
            | claude_types.ResultMessage
        ]:
            yield claude_types.StreamEvent(
                uuid="event",
                session_id="session",
                event={
                    "type": "content_block_delta",
                    "delta": {"text": "partial"},
                },
            )
            yield claude_types.AssistantMessage(
                content=[
                    claude_types.ToolUseBlock(id="t1", name="Read", input={"p": "x"})
                ],
                model="claude",
            )
            yield claude_types.UserMessage(
                content=[
                    claude_types.ToolResultBlock(
                        tool_use_id="t1", content="file body", is_error=False
                    )
                ]
            )
            yield claude_types.ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="session",
                total_cost_usd=0.0,
                usage={},
                result="done",
            )

    monkeypatch.setattr(claude, "ClaudeSDKClient", FixtureClient)
    state = ClaudeConversationState(
        ClaudeSessionOpener(ClaudeSessionConfig(model="claude")), None
    )

    accepted = await state.start_turn("hello")
    assert accepted.events is not None
    durable = [event async for event in accepted.events.events()]
    completed = await accepted.complete()

    # A tool call and its result both reach the durable record. The old
    # stream carried the call and never the result, which is what made it
    # unusable as a trace.
    assert [event.type for event in durable] == [
        "turn_started",
        "block_completed",
        "message_completed",
        "block_completed",
        "message_completed",
        "turn_completed",
    ]
    assert [message.role for message in completed.messages] == ["assistant", "tool"]


@pytest.mark.asyncio
async def test_claude_latest_turn_fork_preserves_a_typed_session_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import claude_agent_sdk as claude

    state = ClaudeConversationState(
        ClaudeSessionOpener(ClaudeSessionConfig(model="claude", cwd=tmp_path)), None
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


@pytest.mark.asyncio
async def test_claude_binder_refreshes_same_schema_turns_without_reconnecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import claude_agent_sdk as claude

    disconnects = 0

    class RecordingClient:
        def __init__(self, options: claude.ClaudeAgentOptions) -> None:
            self.options = options

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            nonlocal disconnects
            disconnects += 1

    monkeypatch.setattr(claude, "ClaudeSDKClient", RecordingClient)
    state = ClaudeConversationState(
        ClaudeSessionOpener(ClaudeSessionConfig(model="claude")), None
    )
    binder = ClaudeTurnToolBinder(state)

    def submission_tool_is_bound() -> bool:
        options = build_claude_options(
            state.config,
            binding=state.current_binding,
            resume=None,
            session_id=state.session_id,
        )
        servers = options.mcp_servers
        assert isinstance(servers, dict)
        return (
            "lup-output" in servers
            and "mcp__lup-output__submit_output" in options.allowed_tools
        )

    def current_binding() -> TurnToolBinding[BaseModel] | None:
        return state.binding

    await binder.bind(None)
    assert current_binding() is None
    assert disconnects == 0
    assert not submission_tool_is_bound()

    first_gated: list[FirstOutput] = []

    async def first_gate(value: FirstOutput) -> SubmissionDecision:
        first_gated.append(value)
        return SubmissionDecision(accepted=True)

    first_store = InMemorySubmittedOutputStore()
    await binder.bind(
        TurnToolBinding(output_type=FirstOutput, store=first_store, gate=first_gate)
    )
    await state.connect()
    first_binding = current_binding()
    assert first_binding is not None
    assert first_binding.output_type is FirstOutput
    assert first_binding.store is first_store
    assert submission_tool_is_bound()
    first_erased = first_binding.gate
    assert first_erased is not None
    first_decision = await first_erased(FirstOutput(answer="first"))
    assert first_decision.accepted
    assert first_gated == [FirstOutput(answer="first")]

    gated: list[FirstOutput] = []

    async def gate(value: FirstOutput) -> SubmissionDecision:
        gated.append(value)
        return SubmissionDecision(accepted=True)

    refreshed_store = InMemorySubmittedOutputStore()
    connected = state.client
    await binder.bind(
        TurnToolBinding(output_type=FirstOutput, store=refreshed_store, gate=gate)
    )
    # The schema is unchanged, so the conversation the provider is holding
    # survives the turn boundary instead of being spent reinstalling it.
    assert disconnects == 0
    assert state.client is connected
    refreshed_binding = current_binding()
    assert refreshed_binding is not None
    assert refreshed_binding.store is refreshed_store
    assert refreshed_binding.gate is not first_binding.gate
    erased_gate = refreshed_binding.gate
    assert erased_gate is not None
    decision = await erased_gate(FirstOutput(answer="checked"))
    assert decision.accepted
    assert gated == [FirstOutput(answer="checked")]

    await state.connect()
    await binder.bind(
        TurnToolBinding(output_type=SecondOutput, store=InMemorySubmittedOutputStore())
    )
    # A different schema can only be advertised by reconnecting.
    assert disconnects == 1
    second_binding = current_binding()
    assert second_binding is not None
    assert second_binding.output_type is SecondOutput

    await state.connect()
    await binder.bind(None)
    assert disconnects == 2
    assert current_binding() is None
    assert not submission_tool_is_bound()


@pytest.mark.asyncio
async def test_claude_submission_server_serves_the_binding_installed_now() -> None:
    """A connection outlives the turn that opened it, so its tool must too."""
    from mcp import types as mcp_types

    state = ClaudeConversationState(
        ClaudeSessionOpener(ClaudeSessionConfig(model="claude")), None
    )
    binder = ClaudeTurnToolBinder(state)

    opening_store = InMemorySubmittedOutputStore()
    await binder.bind(
        TurnToolBinding(output_type=FirstOutput, store=opening_store, gate=None)
    )
    # Built once, as a connection builds it, and never rebuilt afterwards.
    server = build_submission_server(state.current_binding).server

    later_store = InMemorySubmittedOutputStore()
    await binder.bind(
        TurnToolBinding(output_type=FirstOutput, store=later_store, gate=None)
    )

    handler = server.request_handlers[mcp_types.CallToolRequest]
    await handler(
        mcp_types.CallToolRequest(
            method="tools/call",
            params=mcp_types.CallToolRequestParams(
                name="submit_output", arguments={"answer": "later"}
            ),
        )
    )

    assert later_store.read(FirstOutput) == FirstOutput(answer="later")
    assert opening_store.read(FirstOutput) is None


@pytest.mark.asyncio
async def test_codex_binder_refreshes_same_schema_turns_and_fails_before_input(
    tmp_path: Path,
) -> None:
    state = CodexConversationState(
        CodexSessionConfig(model="gpt", cwd=tmp_path),
        CodexAppServer(Path("codex")),
        None,
    )
    binder = CodexTurnToolBinder(state)

    first_store = InMemorySubmittedOutputStore()
    await binder.bind(TurnToolBinding(output_type=FirstOutput, store=first_store))
    assert state.schema_digest is not None
    state.thread_id = "thread-1"

    refreshed_store = InMemorySubmittedOutputStore()
    await binder.bind(TurnToolBinding(output_type=FirstOutput, store=refreshed_store))
    assert state.binding is not None
    assert state.binding.store is refreshed_store

    digest = state.schema_digest
    with pytest.raises(CodexSchemaRebindingError, match="thread/start"):
        await binder.bind(
            TurnToolBinding(
                output_type=SecondOutput, store=InMemorySubmittedOutputStore()
            )
        )
    with pytest.raises(CodexSchemaRebindingError, match="thread/start"):
        await binder.bind(None)
    assert state.binding.store is refreshed_store
    assert state.schema_digest == digest


@pytest.mark.asyncio
async def test_codex_steer_targets_the_active_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = CodexConversationState(
        CodexSessionConfig(model="gpt", cwd=tmp_path),
        CodexAppServer(Path("codex")),
        None,
    )
    state.thread_id = "thread-1"
    requests: list[JsonObject] = []

    async def request(method: str, params: JsonObject) -> JsonValue:
        requests.append({"method": method, "params": params})
        return {}

    monkeypatch.setattr(state.server, "request", request)

    await CodexSteer(state, "turn-9").steer(TurnInput(text="focus on the tests"))

    assert requests == [
        {
            "method": "turn/steer",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-9",
                "input": [{"type": "text", "text": "focus on the tests"}],
            },
        }
    ]


@pytest.mark.asyncio
async def test_closing_a_session_settles_the_reader_before_the_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session exit interrupts an unfinished turn and does not await its read.

    The reader is still suspended inside `receive_response()` when the
    transport is torn down, so closing that generator raises `aclose():
    asynchronous generator is already running`. Persistence has completed by
    then, which makes a finished run read as a failed one.
    """
    import claude_agent_sdk as claude

    class SuspendingClient:
        def __init__(self, options: claude.ClaudeAgentOptions) -> None:
            self.options = options
            self.response: AsyncGenerator[object] | None = None
            self.reading = asyncio.Event()

        async def connect(self) -> None:
            return None

        async def interrupt(self) -> None:
            return None

        async def query(self, prompt: str, session_id: str = "default") -> None:
            return None

        def receive_response(self) -> AsyncGenerator[object]:
            async def stream() -> AsyncGenerator[object]:
                self.reading.set()
                await asyncio.Event().wait()
                yield object()

            self.response = stream()
            return self.response

        async def disconnect(self) -> None:
            # A transport closes the generator it handed out, and doing so
            # while the reader still owns it is what raises.
            if self.response is not None:
                await self.response.aclose()

    clients: list[SuspendingClient] = []

    def track(options: claude.ClaudeAgentOptions) -> SuspendingClient:
        clients.append(SuspendingClient(options))
        return clients[-1]

    monkeypatch.setattr(claude, "ClaudeSDKClient", track)
    opener = ClaudeSessionOpener(ClaudeSessionConfig(model="claude"))

    async with opener.open_session() as handle:
        await handle.session.start(TurnRequest(input=TurnInput(text="hello")))
        # An unfinished turn is torn down with its reader suspended inside the
        # response generator, so wait until it is actually there.
        await clients[-1].reading.wait()
