"""Tests for SDK interop: phases 2-7 functionality."""

import asyncio
import tempfile
from collections.abc import Awaitable
from pathlib import Path

from lup.adapters.codex import (
    CodexHookConfig,
    build_hook_config_overrides,
    build_mcp_config_overrides,
)
from lup.adapters.codex_hooks import (
    build_nudge_hook,
    build_permission_hooks,
    build_reflection_gate_hook,
    build_tool_allowlist_hook,
    format_codex_hook_output,
    write_nudge_script,
    write_permission_hook_script,
    write_reflection_gate_script,
    write_tool_allowlist_script,
)
from lup.types import (
    LupDoneEvent,
    LupEvent,
    LupTextEvent,
    LupThinkingEvent,
    LupToolResultEvent,
    LupToolUseEvent,
    model_backend,
    normalize_effort,
)
from lup.hooks import (
    create_capture_hook,
    create_nudge_hook,
    create_permission_hooks,
    create_reflection_gate,
    create_tool_allowlist_hook,
)
from lup.reflect import ReflectionGate
from lup.types import (
    LupHookInput,
    LupHooksConfig,
    SubagentSpec,
    allow_hook,
    block_hook,
    deny_hook,
    merge_hooks,
)


def run_awaitable[T](aw: Awaitable[T]) -> T:
    async def wrapper() -> T:
        return await aw

    return asyncio.run(wrapper())


class TestMcpConfigOverrides:
    def test_default_serve_tools(self) -> None:
        overrides = build_mcp_config_overrides()
        assert 'mcp_servers.notes.command="uv"' in overrides
        assert 'mcp_servers.sandbox.command="uv"' in overrides
        notes_args = next(
            o for o in overrides if o.startswith("mcp_servers.notes.args")
        )
        assert "lup-devtools" in notes_args
        assert '"--server", "notes"' in notes_args

    def test_custom_command(self) -> None:
        overrides = build_mcp_config_overrides(
            serve_tools_command="python3",
            serve_tools_args=["-m", "lup.devtools.main", "agent", "serve-tools"],
        )
        assert 'mcp_servers.notes.command="python3"' in overrides

    def test_env_relay(self) -> None:
        overrides = build_mcp_config_overrides(env={"LUP_SESSION_DIR": "/tmp/s"})
        assert 'mcp_servers.notes.env.LUP_SESSION_DIR="/tmp/s"' in overrides


class TestSandboxConfigOverrides:
    def test_workspace_write_with_roots(self) -> None:
        from lup.adapters.codex import build_sandbox_config_overrides

        overrides = build_sandbox_config_overrides([Path("/notes/a"), Path("/notes/b")])
        assert 'sandbox_mode="workspace-write"' in overrides
        assert any("writable_roots" in o and "/notes/a" in o for o in overrides)


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
        assert output.get("decision") == "allow"
        assert "reason" not in output

    def test_deny_decision_with_reason(self) -> None:
        output = format_codex_hook_output("deny", "not permitted")
        assert output.get("decision") == "deny"
        assert output.get("reason") == "not permitted"


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
            assert hooks[0].get("matcher") == "StructuredOutput"


class TestReflectionGateFileBacked:
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


class TestLupMcpServerConfig:
    def test_create_mcp_server_returns_lup_config(self) -> None:
        from lup.mcp import LupMcpServerConfig, create_mcp_server

        config = create_mcp_server("test-server", version="1.0.0")
        assert isinstance(config, LupMcpServerConfig)
        assert config.name == "test-server"
        assert config.server is not None

    def test_lup_server_to_claude_conversion(self) -> None:
        from lup.adapters.claude import lup_server_to_claude
        from lup.mcp import create_mcp_server

        lup_config = create_mcp_server("test-server")
        claude_config = lup_server_to_claude(lup_config)
        assert claude_config["name"] == "test-server"
        assert claude_config["type"] == "sdk"
        assert claude_config["instance"] is not None


class TestSubagentSpec:
    def test_spec_to_claude(self) -> None:
        from lup.adapters.claude import spec_to_claude

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

    def test_spec_to_claude_passes_full_model_id_through(self) -> None:
        from lup.adapters.claude import spec_to_claude

        spec = SubagentSpec(
            name="test",
            description="Test",
            prompt="Test",
            model="gpt-4.1-mini",
        )
        agent_def = spec_to_claude(spec)
        assert agent_def.model == "gpt-4.1-mini"

    def test_get_subagent_specs(self) -> None:
        from lup_template.agent.subagents import get_subagent_specs

        specs = get_subagent_specs()
        assert len(specs) >= 2
        names = [s.name for s in specs]
        assert "researcher" in names
        assert "analyzer" in names


class TestModelBackend:
    def test_claude_models(self) -> None:
        assert model_backend("claude-opus-4-6") == "anthropic"
        assert model_backend("claude-sonnet-4-6") == "anthropic"
        assert model_backend("haiku") == "anthropic"
        assert model_backend("sonnet") == "anthropic"

    def test_openai_models(self) -> None:
        assert model_backend("gpt-4.1") == "openai"
        assert model_backend("gpt-4.1-mini") == "openai"
        assert model_backend("o1-preview") == "openai"
        assert model_backend("o3-mini") == "openai"
        assert model_backend("o4-mini") == "openai"
        assert model_backend("o5-preview") == "openai"
        assert model_backend("codex-mini-latest") == "openai"

    def test_default_openai_compatible(self) -> None:
        assert model_backend("unknown-model") == "openai-compatible"


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
    def test_events_dispatch_by_discriminator(self) -> None:
        events: list[LupEvent] = [
            LupTextEvent(text="hello"),
            LupThinkingEvent(thinking="hmm"),
            LupToolUseEvent(id="t1", name="Bash"),
            LupToolResultEvent(tool_use_id="t1", content="out"),
            LupDoneEvent(),
        ]
        kinds = [event.type for event in events]
        assert kinds == ["text", "thinking", "tool_use", "tool_result", "done"]


class TestToolAllowlistHookScripts:
    def test_write_allowlist_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "allowlist.py"
            write_tool_allowlist_script(script_path, ["Read", "Grep", "WebSearch"])
            assert script_path.exists()
            content = script_path.read_text()
            assert "ALLOWED_TOOLS" in content
            assert "Read" in content
            assert "Grep" in content

    def test_build_tool_allowlist_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks = build_tool_allowlist_hook(
                allowed_tools=["Read", "Bash"],
                script_dir=Path(tmpdir),
            )
            assert len(hooks) == 1
            assert hooks[0]["event"] == "PreToolUse"
            assert "codex_tool_allowlist_hook.py" in hooks[0]["command"]

    def test_allowlist_script_denies_unknown_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "allowlist.py"
            write_tool_allowlist_script(script_path, ["Read"])
            content = script_path.read_text()
            assert "not in allowed list" in content


class TestNudgeHookScripts:
    def test_write_nudge_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "nudge.py"
            write_nudge_script(
                script_path,
                {"fetch_url": "Consider using WebFetch instead."},
            )
            assert script_path.exists()
            content = script_path.read_text()
            assert "NUDGES" in content
            assert "fetch_url" in content
            assert "Consider using WebFetch instead." in content

    def test_build_nudge_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks = build_nudge_hook(
                nudges={"Bash": "Try using a specific tool instead."},
                script_dir=Path(tmpdir),
            )
            assert len(hooks) == 1
            assert hooks[0]["event"] == "PostToolUse"
            assert "codex_nudge_hook.py" in hooks[0]["command"]

    def test_nudge_script_uses_system_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "nudge.py"
            write_nudge_script(script_path, {"Bash": "Use Grep"})
            content = script_path.read_text()
            assert "systemMessage" in content


class TestCodexAdapter:
    def test_adapter_builds_config_overrides_with_mcp(self) -> None:
        from lup.adapters.codex import CodexAdapter

        adapter = CodexAdapter(
            model="o4-mini",
            system_prompt="test",
            mcp_tools=True,
        )
        overrides = adapter.build_config_overrides()
        assert any("mcp_servers" in o for o in overrides)

    def test_adapter_builds_config_overrides_without_mcp(self) -> None:
        from lup.adapters.codex import CodexAdapter

        adapter = CodexAdapter(
            model="o4-mini",
            system_prompt="test",
            mcp_tools=False,
        )
        overrides = adapter.build_config_overrides()
        assert not any("mcp_servers" in o for o in overrides)

    def test_adapter_builds_config_overrides_with_hooks(self) -> None:
        from lup.adapters.codex import CodexAdapter

        adapter = CodexAdapter(
            model="o4-mini",
            system_prompt="test",
            mcp_tools=False,
            hook_overrides=[
                CodexHookConfig(event="PreToolUse", command="hook.py"),
            ],
        )
        overrides = adapter.build_config_overrides()
        assert any("codex_hooks" in o for o in overrides)


class TestGenericHookOutputHelpers:
    def test_allow_hook(self) -> None:
        output = allow_hook()
        assert output.get("decision") == "allow"

    def test_deny_hook(self) -> None:
        output = deny_hook("not permitted")
        assert output.get("decision") == "deny"
        assert output.get("reason") == "not permitted"

    def test_block_hook(self) -> None:
        output = block_hook("blocked reason")
        assert output.get("decision") == "block"
        assert output.get("reason") == "blocked reason"


class TestMergeHooks:
    def test_merge_disjoint_events(self) -> None:
        from lup.types import LupHookMatcher, LupHookOutput

        async def hook_a(inp: LupHookInput) -> LupHookOutput:
            return allow_hook()

        async def hook_b(inp: LupHookInput) -> LupHookOutput:
            return allow_hook()

        a: LupHooksConfig = {"PreToolUse": [LupHookMatcher(hook=hook_a)]}
        b: LupHooksConfig = {"PostToolUse": [LupHookMatcher(hook=hook_b)]}
        merged = merge_hooks(a, b)
        assert "PreToolUse" in merged
        assert "PostToolUse" in merged

    def test_merge_same_event(self) -> None:
        from lup.types import LupHookMatcher, LupHookOutput

        async def hook_a(inp: LupHookInput) -> LupHookOutput:
            return allow_hook()

        async def hook_b(inp: LupHookInput) -> LupHookOutput:
            return deny_hook("no")

        a: LupHooksConfig = {"PreToolUse": [LupHookMatcher(hook=hook_a)]}
        b: LupHooksConfig = {"PreToolUse": [LupHookMatcher(hook=hook_b)]}
        merged = merge_hooks(a, b)
        assert len(merged["PreToolUse"]) == 2


class TestGenericPermissionHooks:
    def test_allows_write_in_rw_dir(self) -> None:
        hooks = create_permission_hooks(
            rw_dirs=[Path("/data/rw")], ro_dirs=[Path("/data/ro")]
        )
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="Write",
            tool_input={"file_path": "/data/rw/file.txt"},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "allow"

    def test_denies_write_outside_rw_dir(self) -> None:
        hooks = create_permission_hooks(
            rw_dirs=[Path("/data/rw")], ro_dirs=[Path("/data/ro")]
        )
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="Write",
            tool_input={"file_path": "/elsewhere/file.txt"},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "deny"

    def test_allows_read_in_ro_dir(self) -> None:
        hooks = create_permission_hooks(
            rw_dirs=[Path("/data/rw")], ro_dirs=[Path("/data/ro")]
        )
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="Read",
            tool_input={"file_path": "/data/ro/info.txt"},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "allow"

    def test_denies_read_outside_allowed(self) -> None:
        hooks = create_permission_hooks(
            rw_dirs=[Path("/data/rw")], ro_dirs=[Path("/data/ro")]
        )
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="Read",
            tool_input={"file_path": "/secret/file.txt"},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "deny"

    def test_allows_other_tools(self) -> None:
        hooks = create_permission_hooks(rw_dirs=[Path("/rw")], ro_dirs=[])
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="WebSearch",
            tool_input={"query": "test"},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "allow"


class TestGenericToolAllowlistHook:
    def test_allows_listed_tool(self) -> None:
        hooks = create_tool_allowlist_hook(["Read", "Grep"])
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="Read",
            tool_input={},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "allow"

    def test_denies_unlisted_tool(self) -> None:
        hooks = create_tool_allowlist_hook(["Read", "Grep"])
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="Write",
            tool_input={},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "deny"
        assert "not in allowed list" in result.get("reason", "")


class TestGenericReflectionGate:
    def test_denies_before_reflection(self) -> None:
        gate = ReflectionGate()
        hooks = create_reflection_gate(
            gate=gate,
            gated_tool="StructuredOutput",
            reflection_tool_name="review",
        )
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="StructuredOutput",
            tool_input={},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "deny"
        assert "review" in result.get("reason", "")

    def test_allows_after_reflection(self) -> None:
        gate = ReflectionGate()
        gate.mark_reflected()
        hooks = create_reflection_gate(
            gate=gate,
            gated_tool="StructuredOutput",
            reflection_tool_name="review",
        )
        hook_fn = hooks["PreToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PreToolUse",
            tool_name="StructuredOutput",
            tool_input={},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("decision") == "allow"

    def test_matcher_set_correctly(self) -> None:
        gate = ReflectionGate()
        hooks = create_reflection_gate(
            gate=gate,
            gated_tool="StructuredOutput",
            reflection_tool_name="review",
        )
        assert hooks["PreToolUse"][0].matcher == "StructuredOutput"


class TestGenericNudgeHook:
    def test_nudge_triggered(self) -> None:
        hooks = create_nudge_hook({"Bash": lambda inp: "Use Grep instead"})
        hook_fn = hooks["PostToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PostToolUse",
            tool_name="Bash",
            tool_input={},
        )
        result = run_awaitable(hook_fn(inp))
        assert result.get("system_message") == "Use Grep instead"

    def test_nudge_not_triggered_for_other_tools(self) -> None:
        hooks = create_nudge_hook({"Bash": lambda inp: "Use Grep instead"})
        hook_fn = hooks["PostToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PostToolUse",
            tool_name="Read",
            tool_input={},
        )
        result = run_awaitable(hook_fn(inp))
        assert "system_message" not in result

    def test_nudge_skipped_when_check_returns_none(self) -> None:
        hooks = create_nudge_hook({"Bash": lambda inp: None})
        hook_fn = hooks["PostToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PostToolUse",
            tool_name="Bash",
            tool_input={},
        )
        result = run_awaitable(hook_fn(inp))
        assert "system_message" not in result


class TestGenericCaptureHook:
    def test_captures_matching_tool(self) -> None:
        hooks, captured = create_capture_hook(
            "WebSearch",
            lambda inp: [inp.get("tool_input", {}).get("query", "")],
        )
        hook_fn = hooks["PostToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PostToolUse",
            tool_name="WebSearch",
            tool_input={"query": "python async"},
        )
        run_awaitable(hook_fn(inp))
        assert captured == ["python async"]

    def test_ignores_non_matching_tool(self) -> None:
        hooks, captured = create_capture_hook(
            "WebSearch",
            lambda inp: ["should not appear"],
        )
        hook_fn = hooks["PostToolUse"][0].hook
        inp = LupHookInput(
            hook_event_name="PostToolUse",
            tool_name="Read",
            tool_input={},
        )
        run_awaitable(hook_fn(inp))
        assert captured == []


class TestLupHooksToClaudeConversion:
    def test_converts_allow_decision(self) -> None:
        from lup.adapters.claude import lup_hook_output_to_claude
        from lup.types import LupHookOutput

        output = LupHookOutput(decision="allow")
        result = lup_hook_output_to_claude(output)
        specific = result.get("hookSpecificOutput")
        assert specific is not None and specific["hookEventName"] == "PreToolUse"
        assert specific.get("permissionDecision") == "allow"

    def test_converts_deny_decision(self) -> None:
        from lup.adapters.claude import lup_hook_output_to_claude
        from lup.types import LupHookOutput

        output = LupHookOutput(decision="deny", reason="test reason")
        result = lup_hook_output_to_claude(output)
        specific = result.get("hookSpecificOutput")
        assert specific is not None and specific["hookEventName"] == "PreToolUse"
        assert specific.get("permissionDecision") == "deny"
        assert specific.get("permissionDecisionReason") == "test reason"

    def test_converts_block_decision(self) -> None:
        from lup.adapters.claude import lup_hook_output_to_claude
        from lup.types import LupHookOutput

        output = LupHookOutput(decision="block", reason="blocked")
        result = lup_hook_output_to_claude(output)
        assert result.get("decision") == "block"
        assert result.get("reason") == "blocked"

    def test_deny_outside_pre_tool_use_converts_to_block(self) -> None:
        """Permission decisions exist only on PreToolUse — a denial from a
        Stop/PostToolUse hook must become the generic block decision, not a
        misrouted PreToolUse hookSpecificOutput."""
        from lup.adapters.claude import lup_hook_output_to_claude
        from lup.types import LupHookOutput

        output = LupHookOutput(decision="deny", reason="not done yet")
        result = lup_hook_output_to_claude(output, event="Stop")
        assert result.get("hookSpecificOutput") is None
        assert result.get("decision") == "block"
        assert result.get("reason") == "not done yet"

    def test_allow_outside_pre_tool_use_is_noop(self) -> None:
        from lup.adapters.claude import lup_hook_output_to_claude
        from lup.types import LupHookOutput

        output = LupHookOutput(decision="allow")
        result = lup_hook_output_to_claude(output, event="PostToolUse")
        assert result.get("hookSpecificOutput") is None
        assert result.get("decision") is None

    def test_converts_system_message(self) -> None:
        from lup.adapters.claude import lup_hook_output_to_claude
        from lup.types import LupHookOutput

        output = LupHookOutput(system_message="try another way")
        result = lup_hook_output_to_claude(output)
        assert result.get("systemMessage") == "try another way"

    def test_converts_empty_output(self) -> None:
        from lup.adapters.claude import lup_hook_output_to_claude
        from lup.types import LupHookOutput

        output = LupHookOutput()
        result = lup_hook_output_to_claude(output)
        assert result.get("decision") is None
        assert result.get("hookSpecificOutput") is None

    def test_full_hook_conversion_roundtrip(self) -> None:
        from lup.adapters.claude import lup_hooks_to_claude

        hooks = create_permission_hooks(rw_dirs=[Path("/data")], ro_dirs=[Path("/ref")])
        claude_hooks = lup_hooks_to_claude(hooks)
        assert "PreToolUse" in claude_hooks
        assert len(claude_hooks["PreToolUse"]) == 1

    def test_matcher_preserved_in_conversion(self) -> None:
        from lup.adapters.claude import lup_hooks_to_claude

        gate = ReflectionGate()
        hooks = create_reflection_gate(
            gate=gate,
            gated_tool="StructuredOutput",
            reflection_tool_name="review",
        )
        claude_hooks = lup_hooks_to_claude(hooks)
        assert claude_hooks["PreToolUse"][0].matcher == "StructuredOutput"


class TestLupHooksToCodexConversion:
    def test_converts_permission_hooks(self) -> None:
        from lup.adapters.codex_hooks import lup_hooks_to_codex

        hooks = create_permission_hooks(rw_dirs=[Path("/data")], ro_dirs=[Path("/ref")])
        with tempfile.TemporaryDirectory() as tmpdir:
            configs = lup_hooks_to_codex(
                hooks,
                script_dir=Path(tmpdir),
                rw_dirs=[Path("/data")],
                ro_dirs=[Path("/ref")],
            )
            assert len(configs) >= 1
            assert configs[0]["event"] == "PreToolUse"
            script_path = Path(tmpdir) / "codex_permission_hook.py"
            assert script_path.exists()

    def test_converts_gate_hooks(self) -> None:
        from lup.adapters.codex_hooks import lup_hooks_to_codex

        gate = ReflectionGate()
        hooks = create_reflection_gate(
            gate=gate,
            gated_tool="StructuredOutput",
            reflection_tool_name="review",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            gate_flag = Path(tmpdir) / "flag"
            configs = lup_hooks_to_codex(
                hooks,
                script_dir=Path(tmpdir),
                gate_flag_path=gate_flag,
            )
            assert len(configs) == 1
            assert configs[0]["event"] == "PreToolUse"
            assert configs[0].get("matcher") == "StructuredOutput"

    def test_converts_merged_hooks(self) -> None:
        from lup.adapters.codex_hooks import lup_hooks_to_codex

        gate = ReflectionGate()
        perm_hooks = create_permission_hooks(rw_dirs=[Path("/data")], ro_dirs=[])
        gate_hooks = create_reflection_gate(
            gate=gate,
            gated_tool="StructuredOutput",
            reflection_tool_name="review",
        )
        combined = merge_hooks(perm_hooks, gate_hooks)
        with tempfile.TemporaryDirectory() as tmpdir:
            gate_flag = Path(tmpdir) / "flag"
            configs = lup_hooks_to_codex(
                combined,
                script_dir=Path(tmpdir),
                rw_dirs=[Path("/data")],
                gate_flag_path=gate_flag,
            )
            assert len(configs) == 2

    def test_converts_nudge_hooks(self) -> None:
        from lup.adapters.codex_hooks import lup_hooks_to_codex

        hooks = create_nudge_hook({"Bash": lambda inp: "Use Grep instead"})
        with tempfile.TemporaryDirectory() as tmpdir:
            configs = lup_hooks_to_codex(
                hooks,
                script_dir=Path(tmpdir),
                nudges={"Bash": "Use Grep instead"},
            )
            assert len(configs) == 1
            assert configs[0]["event"] == "PostToolUse"
            script_path = Path(tmpdir) / "codex_nudge_hook.py"
            assert script_path.exists()
            content = script_path.read_text()
            assert "Bash" in content
            assert "Use Grep instead" in content

    def test_converts_allowlist_hooks(self) -> None:
        from lup.adapters.codex_hooks import lup_hooks_to_codex

        hooks = create_tool_allowlist_hook(["Read", "Grep"])
        with tempfile.TemporaryDirectory() as tmpdir:
            configs = lup_hooks_to_codex(
                hooks,
                script_dir=Path(tmpdir),
                allowed_tools=["Read", "Grep"],
            )
            assert len(configs) == 1
            assert configs[0]["event"] == "PreToolUse"
            script_path = Path(tmpdir) / "codex_tool_allowlist_hook.py"
            assert script_path.exists()
            content = script_path.read_text()
            assert "Read" in content
            assert "Grep" in content

    def test_converts_full_hook_set(self) -> None:
        from lup.adapters.codex_hooks import lup_hooks_to_codex

        gate = ReflectionGate()
        perm_hooks = create_permission_hooks(
            rw_dirs=[Path("/data")], ro_dirs=[Path("/ref")]
        )
        gate_hooks = create_reflection_gate(
            gate=gate,
            gated_tool="StructuredOutput",
            reflection_tool_name="review",
        )
        nudge_hooks = create_nudge_hook({"Bash": lambda inp: "Use Grep instead"})
        combined = merge_hooks(merge_hooks(perm_hooks, gate_hooks), nudge_hooks)
        with tempfile.TemporaryDirectory() as tmpdir:
            gate_flag = Path(tmpdir) / "flag"
            configs = lup_hooks_to_codex(
                combined,
                script_dir=Path(tmpdir),
                rw_dirs=[Path("/data")],
                ro_dirs=[Path("/ref")],
                gate_flag_path=gate_flag,
                nudges={"Bash": "Use Grep instead"},
            )
            assert len(configs) == 3
            events = [c["event"] for c in configs]
            assert "PreToolUse" in events
            assert "PostToolUse" in events


class TestOpenAICompatibleAdapter:
    """Tests for the OpenAI-compatible adapter configuration."""

    def test_config_overrides_include_base_url(self) -> None:
        from lup.adapters.openai_compat import (
            OPENAI_COMPAT_API_KEY_ENV,
            OpenAICompatibleAdapter,
        )

        adapter = OpenAICompatibleAdapter(
            model="glm-4-7b",
            system_prompt="test",
            base_url="http://localhost:8000/v1",
            api_key="test-key",
            model_provider="openai_compat",
            mcp_tools=False,
        )
        overrides = adapter.build_config_overrides()

        # The provider is defined under the plural model_providers.<id> table,
        # selected by a top-level model_provider string.
        assert 'model_provider="openai_compat"' in overrides
        assert (
            'model_providers.openai_compat.base_url="http://localhost:8000/v1"'
            in overrides
        )
        # The key is referenced by env-var NAME (env_key), never inline.
        assert (
            f'model_providers.openai_compat.env_key="{OPENAI_COMPAT_API_KEY_ENV}"'
            in overrides
        )
        # No literal `api_key=` override and no secret value leaks into overrides;
        # the secret is injected via the subprocess env (provider_env()).
        assert not any("api_key=" in o for o in overrides)
        assert not any("test-key" in o for o in overrides)
        assert adapter.provider_env() == {OPENAI_COMPAT_API_KEY_ENV: "test-key"}

    def test_config_overrides_without_credentials(self) -> None:
        from lup.adapters.openai_compat import OpenAICompatibleAdapter

        adapter = OpenAICompatibleAdapter(
            model="llama-3.1-8b",
            system_prompt="test",
            mcp_tools=False,
        )
        overrides = adapter.build_config_overrides()
        assert not any("base_url" in o for o in overrides)
        assert not any("api_key" in o for o in overrides)

    def test_inherits_mcp_config(self) -> None:
        from lup.adapters.openai_compat import OpenAICompatibleAdapter

        adapter = OpenAICompatibleAdapter(
            model="glm-4-7b",
            system_prompt="test",
            base_url="http://localhost:8000/v1",
            mcp_tools=True,
        )
        overrides = adapter.build_config_overrides()
        assert any("mcp_servers.notes" in o for o in overrides)

    def test_inherits_hook_config(self) -> None:
        from lup.adapters.codex import CodexHookConfig
        from lup.adapters.openai_compat import OpenAICompatibleAdapter

        hooks: list[CodexHookConfig] = [
            CodexHookConfig(event="PreToolUse", command="check.py"),
        ]
        adapter = OpenAICompatibleAdapter(
            model="glm-4-7b",
            system_prompt="test",
            mcp_tools=False,
            hook_overrides=hooks,
        )
        overrides = adapter.build_config_overrides()
        assert any("PreToolUse" in o for o in overrides)


class TestModelBackendExtended:
    """Extended tests for model_backend covering open-source models."""

    def test_glm_model(self) -> None:
        assert model_backend("glm-4-7b") == "openai-compatible"

    def test_llama_model(self) -> None:
        assert model_backend("llama-3.1-8b") == "openai-compatible"

    def test_deepseek_model(self) -> None:
        assert model_backend("deepseek-v3") == "openai-compatible"

    def test_qwen_model(self) -> None:
        assert model_backend("qwen-72b") == "openai-compatible"

    def test_gpt_model(self) -> None:
        assert model_backend("gpt-4.1") == "openai"

    def test_o_series_model(self) -> None:
        assert model_backend("o3-mini") == "openai"

    def test_claude_full_name(self) -> None:
        assert model_backend("claude-opus-4-8") == "anthropic"

    def test_claude_short_name(self) -> None:
        assert model_backend("opus") == "anthropic"
