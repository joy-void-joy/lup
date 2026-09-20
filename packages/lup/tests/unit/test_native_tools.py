"""Explicit grants bound tool inventories and execution on both adapters."""

import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from lup import create_client
from lup.providers.claude.runtime import (
    ClaudeSessionConfig,
    ClaudeSessionOpener,
    build_claude_options,
)
from lup.providers.codex.app_server import CodexAppServer, RpcMessage
from lup.providers.codex.runtime import (
    CodexConversationState,
    CodexSessionConfig,
    CodexSessionOpener,
    CodexTurnChannel,
)
from lup.providers.claude.native_tools import claude_native_tools
from lup.providers.codex.native_tools import CodexNativeTools
from lup.providers.claude.selection import claude_config
from lup.providers.codex.selection import codex_config
from lup.providers.selection import SessionRequest
from lup.tools.native import NativeToolGroup, native_grants
from lup.tools.mcp import create_mcp_server, lup_tool
from lup.types import JsonObject


class Value(BaseModel):
    value: str


@pytest.mark.parametrize(
    "value", ["Bash(*)", "*", "", "mcp__ambient__tool", "UnknownTool"]
)
def test_invalid_and_inherited_native_grants_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        ClaudeSessionConfig(native_tools=[value])
    with pytest.raises(ValueError):
        CodexSessionConfig(cwd=Path("."), native_tools=[value])


def test_a_scalar_does_not_become_a_sequence_of_tool_letters() -> None:
    with pytest.raises(ValueError, match="sequence"):
        native_grants("Read")


def test_groups_compose_and_exact_grants_stay_exact() -> None:
    assert claude_native_tools(None) == []
    assert claude_native_tools([NativeToolGroup.READ, "Write"]) == [
        "Read",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "Write",
    ]
    assert claude_native_tools(["Read", "Read"]) == ["Read"]
    assert CodexNativeTools.compile(["Bash"]).shell
    assert not CodexNativeTools.compile(["Bash"]).write
    assert CodexNativeTools.compile([NativeToolGroup.WRITE]).write
    for grant in ("Read", "Write", "WebFetch", NativeToolGroup.READ):
        with pytest.raises(ValueError, match="exactly"):
            CodexNativeTools.compile([grant])


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_tools": ["Bash"]},
        {"extra_args": {"tools": "Bash"}},
        {"extra_args": {"settings": '{"permissions":{"allow":["Bash"]}}'}},
        {"setting_sources": ["user"]},
        {"plugin_dirs": ["plugin"]},
    ],
)
def test_claude_other_fields_cannot_inject_tools(overrides: JsonObject) -> None:
    with pytest.raises(ValidationError):
        ClaudeSessionConfig.model_validate(overrides)


def test_unsafe_model_copies_are_revalidated_at_each_provider_boundary() -> None:
    copied = ClaudeSessionConfig().model_copy(update={"allowed_tools": ["Write"]})
    with pytest.raises(ValidationError, match="outside native_tools"):
        ClaudeSessionOpener(copied)
    with pytest.raises(ValidationError, match="outside native_tools"):
        build_claude_options(copied, binding=lambda: None, resume=None, session_id=None)
    copied_codex = CodexSessionConfig(cwd=Path(".")).model_copy(
        update={"native_tools": ["Read"]}
    )
    with pytest.raises(ValidationError, match="exactly"):
        CodexSessionOpener(copied_codex)


@pytest.mark.parametrize(
    "key",
    [
        "features",
        "features.shell_tool",
        "tools",
        "mcp_servers",
        "web_search",
        "sandbox_mode",
    ],
)
def test_provider_config_cannot_override_tool_authority(key: str) -> None:
    with pytest.raises(ValueError, match="explicit session authority"):
        CodexSessionConfig(cwd=Path("."), provider_config={key: True})


async def test_claude_guard_denies_fabricated_tools_but_keeps_explicit_effectful_tools(
    tmp_path: Path,
) -> None:
    @lup_tool("Write the supplied value.")
    async def record(params: Value) -> Value:
        (tmp_path / "marker").write_text(params.value)
        return params

    options = build_claude_options(
        ClaudeSessionConfig(
            tool_servers={"app": create_mcp_server("app", tools=[record])}
        ),
        binding=lambda: None,
        resume="old-session",
        session_id=None,
    )
    assert options.tools == []
    assert options.strict_mcp_config
    assert options.setting_sources == []
    assert options.hooks is not None
    guard = options.hooks["PreToolUse"][0].hooks[0]
    for name in ("Bash", "Write", "Agent", "mcp__ambient__record"):
        result = await guard(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": name,
                "tool_input": {},
                "tool_use_id": "call",
                "session_id": "old-session",
                "transcript_path": "",
                "cwd": str(tmp_path),
            },
            None,
            {"signal": None},
        )
        match result:
            case {"hookSpecificOutput": {"permissionDecision": "deny"}}:
                pass
            case _:
                pytest.fail(f"fabricated tool was not denied: {result}")
    allowed = await guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__app__record",
            "tool_input": {"value": "authorized"},
            "tool_use_id": "call",
            "session_id": "old-session",
            "transcript_path": "",
            "cwd": str(tmp_path),
        },
        None,
        {"signal": None},
    )
    assert allowed == {}
    await record.handler({"value": "authorized"})
    assert (tmp_path / "marker").read_text() == "authorized"


async def test_codex_validates_explicit_app_calls_and_rejects_foreign_or_stale_turns(
    tmp_path: Path,
) -> None:
    effects: list[str] = []

    @lup_tool("Record one value.")
    async def record(params: Value) -> Value:
        effects.append(params.value)
        return params

    config = codex_config(
        SessionRequest(
            cwd=tmp_path, tool_servers={"app": create_mcp_server("app", tools=[record])}
        )
    )
    state = CodexConversationState(config, CodexAppServer(Path("codex")), None)
    state.thread_id = "thread"
    state.channel = CodexTurnChannel("thread")
    state.channel.turn_id = "turn"

    async def call(thread: str, turn: str, value: str | int) -> JsonObject:
        result = await state.handle_server_request(
            RpcMessage(
                id=1,
                method="item/tool/call",
                params={
                    "threadId": thread,
                    "turnId": turn,
                    "callId": "call",
                    "tool": "lup_app_app__record",
                    "arguments": {"value": value},
                },
            )
        )
        assert isinstance(result, dict)
        return result

    assert (await call("other", "turn", "foreign"))["success"] is False
    assert (await call("thread", "old", "stale"))["success"] is False
    assert (await call("thread", "turn", 5))["success"] is False
    assert effects == []
    assert (await call("thread", "turn", "accepted"))["success"] is True
    assert effects == ["accepted"]


def test_selection_preserves_app_tools_under_none_for_both_runtimes() -> None:
    @lup_tool("Echo one value.")
    async def echo(params: Value) -> Value:
        return params

    server = create_mcp_server("app", tools=[echo])
    request = SessionRequest(cwd=Path("."), tool_servers={"app": server})
    assert claude_config(request).tool_servers["app"] is server
    assert codex_config(request).application_tools["lup_app_app__echo"] is echo
    assert codex_config(request).writable_roots == []
    assert create_client("gpt-6-astra", tools=[echo])
    assert create_client("claude-opus-5", tools=[echo])


def test_dynamic_tool_names_cannot_shadow_another_explicit_handler() -> None:
    @lup_tool("First handler.", name="c")
    async def first(params: Value) -> Value:
        return params

    @lup_tool("Second handler.", name="b__c")
    async def second(params: Value) -> Value:
        return params

    request = SessionRequest(
        cwd=Path("."),
        tool_servers={
            "a__b": create_mcp_server("a__b", tools=[first]),
            "a": create_mcp_server("a", tools=[second]),
        },
    )
    with pytest.raises(ValueError, match="collide"):
        codex_config(request)
    with pytest.raises(ValueError, match="unique"):
        create_client("gpt-6-astra", tools=[first, first])


async def test_unknown_inherited_model_is_refused_before_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = CodexAppServer(Path("codex"))

    async def request(method: str, params: JsonObject) -> JsonObject:
        assert method == "config/read"
        return {"config": {"model": "custom-unknown"}}

    monkeypatch.setattr(server, "request", request)
    state = CodexConversationState(
        CodexSessionConfig(cwd=tmp_path), server, None, models={"known": {}}
    )
    with pytest.raises(ValueError, match="inherited unknown model"):
        await state.ensure_thread()


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_failed_or_cancelled_startup_closes_server_and_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[BaseException]
) -> None:
    closed: list[bool] = []

    async def start(server: CodexAppServer) -> None:
        raise error("startup stopped")

    async def close(server: CodexAppServer) -> None:
        closed.append(True)

    monkeypatch.setattr(CodexAppServer, "start", start)
    monkeypatch.setattr(CodexAppServer, "close", close)
    monkeypatch.setattr(
        CodexNativeTools,
        "model_catalog",
        lambda self, executable, environment, model: {"models": [{"slug": "known"}]},
    )
    opener = CodexSessionOpener(
        CodexSessionConfig(cwd=tmp_path, environment={"CODEX_HOME": str(tmp_path)})
    )
    with pytest.raises(error, match="startup stopped"):
        async with opener.open_session():
            pytest.fail("failed startup yielded a session")
    assert closed == [True]
    assert list(tmp_path.glob("lup-native-*")) == []
