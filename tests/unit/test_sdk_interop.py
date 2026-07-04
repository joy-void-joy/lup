"""SDK interop behavior: Codex config-override generation, hook-script
emission, and lup->SDK hook/option conversion for both engines."""

import tempfile
from pathlib import Path

from lup.adapters.claude import claude_effort
from lup.adapters.codex import (
    CodexHookConfig,
    build_hook_config_overrides,
    build_mcp_config_overrides,
    build_nudge_hook,
    build_permission_hooks,
    build_reflection_gate_hook,
    build_tool_allowlist_hook,
    codex_effort,
    format_codex_hook_output,
    write_nudge_script,
    write_permission_hook_script,
    write_reflection_gate_script,
    write_tool_allowlist_script,
)
from lup.adapters.common import engine_id_for_model
from lup.hooks import (
    create_nudge_hook,
    create_permission_hooks,
    create_tool_allowlist_hook,
)
from lup.reflect import ReflectionGate, create_reflection_gate
from lup.types import (
    LupHookInput,
    LupHooksConfig,
    SubagentSpec,
    allow_hook,
    deny_hook,
    merge_hooks,
)


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


class TestLupMcpServerConfig:
    def test_lup_server_to_claude_conversion(self) -> None:
        from lup.adapters.claude import lup_server_to_claude
        from lup.mcp import create_mcp_server

        lup_config = create_mcp_server("test-server")
        claude_config = lup_server_to_claude(lup_config)
        assert claude_config["name"] == "test-server"
        assert claude_config["type"] == "sdk"
        assert claude_config["instance"] is not None


class TestSubagentSpec:
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
        assert engine_id_for_model("claude-opus-4-6") == "claude"
        assert engine_id_for_model("claude-sonnet-4-6") == "claude"
        assert engine_id_for_model("haiku") == "claude"
        assert engine_id_for_model("sonnet") == "claude"

    def test_openai_models(self) -> None:
        assert engine_id_for_model("gpt-4.1") == "codex"
        assert engine_id_for_model("gpt-4.1-mini") == "codex"
        assert engine_id_for_model("o1-preview") == "codex"
        assert engine_id_for_model("o3-mini") == "codex"
        assert engine_id_for_model("o4-mini") == "codex"
        assert engine_id_for_model("o5-preview") == "codex"
        assert engine_id_for_model("codex-mini-latest") == "codex"

    def test_default_openai_compatible(self) -> None:
        assert engine_id_for_model("unknown-model") == "openai-compat"


class TestEffortNormalization:
    def test_claude_effort(self) -> None:
        assert claude_effort("low") == "low"
        assert claude_effort("high") == "high"
        assert claude_effort("xhigh") == "max"
        assert claude_effort("max") == "max"

    def test_codex_effort(self) -> None:
        assert codex_effort("low") == "low"
        assert codex_effort("high") == "high"
        assert codex_effort("xhigh") == "xhigh"
        assert codex_effort("max") == "xhigh"

    def test_none_passthrough(self) -> None:
        assert claude_effort(None) is None
        assert codex_effort(None) is None


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
        from lup.adapters.codex import CodexClient

        adapter = CodexClient(
            model="o4-mini",
            system_prompt="test",
            mcp_tools=True,
        )
        overrides = adapter.build_config_overrides()
        assert any("mcp_servers" in o for o in overrides)

    def test_adapter_builds_config_overrides_without_mcp(self) -> None:
        from lup.adapters.codex import CodexClient

        adapter = CodexClient(
            model="o4-mini",
            system_prompt="test",
            mcp_tools=False,
        )
        overrides = adapter.build_config_overrides()
        assert not any("mcp_servers" in o for o in overrides)

    def test_adapter_builds_config_overrides_with_hooks(self) -> None:
        from lup.adapters.codex import CodexClient

        adapter = CodexClient(
            model="o4-mini",
            system_prompt="test",
            mcp_tools=False,
            hook_overrides=[
                CodexHookConfig(event="PreToolUse", command="hook.py"),
            ],
        )
        overrides = adapter.build_config_overrides()
        assert any("codex_hooks" in o for o in overrides)


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
        from lup.adapters.codex import lup_hooks_to_codex

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
        from lup.adapters.codex import lup_hooks_to_codex

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
        from lup.adapters.codex import lup_hooks_to_codex

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
        from lup.adapters.codex import lup_hooks_to_codex

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
        from lup.adapters.codex import lup_hooks_to_codex

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
        from lup.adapters.codex import lup_hooks_to_codex

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
