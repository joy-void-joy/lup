"""Tests for SDK interop: phases 2-7 functionality."""

import tempfile
from pathlib import Path

from lup.lib.adapters.codex import (
    CodexHookConfig,
    build_hook_config_overrides,
    build_mcp_config_overrides,
)
from lup.lib.adapters.codex_hooks import (
    build_permission_hooks,
    build_reflection_gate_hook,
    format_codex_hook_output,
    write_permission_hook_script,
    write_reflection_gate_script,
)
from lup.lib.adapters.common import (
    LupDoneEvent,
    LupEvent,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
    model_backend,
    normalize_effort,
)
from lup.lib.reflect import ReflectionGate
from lup.lib.types import SubagentSpec


class TestMcpConfigOverrides:
    def test_default_serve_tools(self) -> None:
        overrides = build_mcp_config_overrides()
        assert len(overrides) == 2
        assert 'mcp_servers.lup-tools.command="uv"' in overrides
        assert "mcp_servers.lup-tools.args=" in overrides[1]
        assert "lup-devtools" in overrides[1]

    def test_custom_command(self) -> None:
        overrides = build_mcp_config_overrides(
            serve_tools_command="python3",
            serve_tools_args=["-m", "lup.devtools.main", "agent", "serve-tools"],
        )
        assert 'mcp_servers.lup-tools.command="python3"' in overrides


class TestHookConfigOverrides:
    def test_single_hook(self) -> None:
        hooks: list[CodexHookConfig] = [
            CodexHookConfig(event="PreToolUse", command="python3 hook.py"),
        ]
        overrides = build_hook_config_overrides(hooks)
        assert "features.codex_hooks=true" in overrides
        assert 'hooks.PreToolUse[0].hooks[0].type="command"' in overrides
        assert 'hooks.PreToolUse[0].hooks[0].command="python3 hook.py"' in overrides

    def test_hook_with_matcher(self) -> None:
        hooks: list[CodexHookConfig] = [
            CodexHookConfig(
                event="PreToolUse",
                matcher="^Bash$",
                command="python3 bash_hook.py",
            ),
        ]
        overrides = build_hook_config_overrides(hooks)
        assert 'hooks.PreToolUse[0].matcher="^Bash$"' in overrides

    def test_multiple_hooks_same_event(self) -> None:
        hooks: list[CodexHookConfig] = [
            CodexHookConfig(event="PreToolUse", command="hook1.py"),
            CodexHookConfig(event="PreToolUse", command="hook2.py"),
        ]
        overrides = build_hook_config_overrides(hooks)
        assert 'hooks.PreToolUse[0].hooks[0].command="hook1.py"' in overrides
        assert 'hooks.PreToolUse[1].hooks[0].command="hook2.py"' in overrides


class TestCodexHookOutput:
    def test_allow_decision(self) -> None:
        output = format_codex_hook_output("allow")
        assert output["decision"] == "allow"
        assert "reason" not in output

    def test_deny_decision_with_reason(self) -> None:
        output = format_codex_hook_output("deny", "not permitted")
        assert output["decision"] == "deny"
        assert output["reason"] == "not permitted"


class TestPermissionHookScripts:
    def test_write_permission_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "hook.py"
            write_permission_hook_script(
                script_path,
                rw_dirs=[Path("/data/rw")],
                ro_dirs=[Path("/data/ro")],
            )
            assert script_path.exists()
            content = script_path.read_text()
            assert "/data/rw" in content
            assert "/data/ro" in content
            assert "def check_permission" in content

    def test_build_permission_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks = build_permission_hooks(
                rw_dirs=[Path("/rw")],
                ro_dirs=[Path("/ro")],
                script_dir=Path(tmpdir),
            )
            assert len(hooks) == 1
            assert hooks[0]["event"] == "PreToolUse"
            assert "codex_permission_hook.py" in hooks[0]["command"]


class TestReflectionGateHookScripts:
    def test_write_gate_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "gate.py"
            gate_flag = Path(tmpdir) / "flag"
            write_reflection_gate_script(
                script_path, gate_flag, "StructuredOutput", "review"
            )
            assert script_path.exists()
            content = script_path.read_text()
            assert "StructuredOutput" in content
            assert "review" in content

    def test_build_gate_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks = build_reflection_gate_hook(
                gate_flag_path=Path(tmpdir) / "flag",
                gated_tool="StructuredOutput",
                reflection_tool_name="review",
                script_dir=Path(tmpdir),
            )
            assert len(hooks) == 1
            assert hooks[0]["event"] == "PreToolUse"
            assert hooks[0]["matcher"] == "StructuredOutput"


class TestReflectionGateFileBacked:
    def test_in_memory_mode(self) -> None:
        gate = ReflectionGate()
        assert not gate.reflected
        gate.mark_reflected()
        assert gate.reflected
        gate.reset()
        assert not gate.reflected

    def test_file_backed_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_path = Path(tmpdir) / "gate_flag"
            gate = ReflectionGate(flag_path=flag_path)

            assert not gate.reflected
            assert not flag_path.exists()

            gate.mark_reflected()
            assert gate.reflected
            assert flag_path.exists()

            gate.reset()
            assert not gate.reflected
            assert not flag_path.exists()

    def test_file_backed_external_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_path = Path(tmpdir) / "gate_flag"
            gate = ReflectionGate(flag_path=flag_path)

            flag_path.touch()
            assert gate.reflected


class TestSubagentSpec:
    def test_spec_creation(self) -> None:
        spec = SubagentSpec(
            name="test",
            description="A test agent",
            prompt="Do the thing",
            tools=["Read", "Grep"],
            model="haiku",
        )
        assert spec.name == "test"
        assert spec.tools == ["Read", "Grep"]

    def test_spec_to_claude(self) -> None:
        from lup.agent.subagents import spec_to_claude

        spec = SubagentSpec(
            name="researcher",
            description="Research things",
            prompt="Research the topic",
            tools=["WebSearch"],
            model="haiku",
        )
        agent_def = spec_to_claude(spec)
        assert agent_def.description == "Research things"
        assert agent_def.prompt == "Research the topic"
        assert agent_def.tools == ["WebSearch"]
        assert agent_def.model == "haiku"

    def test_spec_to_claude_unknown_model(self) -> None:
        from lup.agent.subagents import spec_to_claude

        spec = SubagentSpec(
            name="test",
            description="Test",
            prompt="Test",
            model="gpt-4.1-mini",
        )
        agent_def = spec_to_claude(spec)
        assert agent_def.model is None

    def test_get_subagent_specs(self) -> None:
        from lup.agent.subagents import get_subagent_specs

        specs = get_subagent_specs()
        assert len(specs) >= 2
        names = [s.name for s in specs]
        assert "researcher" in names
        assert "analyzer" in names


class TestModelBackend:
    def test_claude_models(self) -> None:
        assert model_backend("claude-opus-4-6") == "anthropic"
        assert model_backend("claude-sonnet-4-20250514") == "anthropic"
        assert model_backend("haiku") == "anthropic"
        assert model_backend("sonnet") == "anthropic"

    def test_openai_models(self) -> None:
        assert model_backend("gpt-4.1") == "openai"
        assert model_backend("gpt-4.1-mini") == "openai"
        assert model_backend("o1-preview") == "openai"
        assert model_backend("o3-mini") == "openai"
        assert model_backend("o4-mini") == "openai"

    def test_default_anthropic(self) -> None:
        assert model_backend("unknown-model") == "anthropic"


class TestEffortNormalization:
    def test_claude_effort(self) -> None:
        assert normalize_effort("low", "anthropic") == "low"
        assert normalize_effort("high", "anthropic") == "high"
        assert normalize_effort("xhigh", "anthropic") == "max"
        assert normalize_effort("max", "anthropic") == "max"

    def test_codex_effort(self) -> None:
        assert normalize_effort("low", "openai") == "low"
        assert normalize_effort("high", "openai") == "high"
        assert normalize_effort("xhigh", "openai") == "xhigh"
        assert normalize_effort("max", "openai") == "xhigh"

    def test_none_passthrough(self) -> None:
        assert normalize_effort(None, "anthropic") is None
        assert normalize_effort(None, "openai") is None


class TestLupEventTypes:
    def test_text_event(self) -> None:
        event = LupTextEvent("hello")
        assert isinstance(event, LupEvent)
        assert event.text == "hello"

    def test_thinking_event(self) -> None:
        event = LupThinkingEvent("reasoning...")
        assert isinstance(event, LupEvent)
        assert event.thinking == "reasoning..."

    def test_tool_use_event(self) -> None:
        event = LupToolUseEvent(id="t1", name="Bash")
        assert isinstance(event, LupEvent)
        assert event.id == "t1"
        assert event.name == "Bash"

    def test_tool_result_event(self) -> None:
        event = LupToolResultEvent(tool_use_id="t1", content="output")
        assert isinstance(event, LupEvent)
        assert event.tool_use_id == "t1"

    def test_done_event(self) -> None:
        event = LupDoneEvent()
        assert isinstance(event, LupEvent)
        assert event.blocks == []


class TestLupResponseSessionId:
    def test_session_id_field(self) -> None:
        from lup.lib.types import LupResponse

        response = LupResponse()
        assert response.session_id is None

        response.session_id = "thread_abc123"
        assert response.session_id == "thread_abc123"
