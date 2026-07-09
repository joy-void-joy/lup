"""SDK interop behavior: Codex config-override generation, hook-script
emission, and lup->SDK hook/option conversion for both engines."""

import tempfile
from pathlib import Path

from lup.adapters.clients.codex.config import build_mcp_config_overrides
from tests.unit.codex_hooks_reference import (
    CodexHookConfig,
    build_hook_config_overrides,
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
from lup.adapters.clients.codex.translate import codex_effort
from lup.adapters.wiring import engine_for_model
from lup.hooks import (
    LupHookInput,
    LupHooksConfig,
    allow_hook,
    create_nudge_hook,
    create_permission_hooks,
    create_tool_allowlist_hook,
    deny_hook,
    merge_hooks,
)
from lup.reflect import ReflectionGate, create_reflection_gate
from lup.types import SubagentSpec


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
        from lup.adapters.clients.codex.config import build_sandbox_config_overrides

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
    def test_in_process_server_becomes_sdk_config(self) -> None:
        from lup.adapters.clients.claude.translate import build_claude_options
        from lup.adapters.options import LupAgentOptions
        from lup.mcp import create_mcp_server

        opts = LupAgentOptions(
            model="claude-opus-4-6",
            tool_servers={"test-server": create_mcp_server("test-server")},
        )
        servers = build_claude_options(opts).mcp_servers
        assert isinstance(servers, dict)
        # The in-process server became an SDK ``sdk`` server, not passed raw.
        assert servers["test-server"].get("type") == "sdk"


class TestSubagentSpec:
    def test_spec_to_claude_passes_full_model_id_through(self) -> None:
        from lup.adapters.clients.claude.translate import spec_to_claude

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
    def engine_for(self, model: str) -> str:
        return engine_for_model(model).id

    def test_claude_models(self) -> None:
        assert self.engine_for("claude-opus-4-6") == "claude"
        assert self.engine_for("claude-sonnet-4-6") == "claude"
        assert self.engine_for("haiku") == "claude"
        assert self.engine_for("sonnet") == "claude"

    def test_openai_models(self) -> None:
        assert self.engine_for("gpt-4.1") == "codex"
        assert self.engine_for("gpt-4.1-mini") == "codex"
        assert self.engine_for("o1-preview") == "codex"
        assert self.engine_for("o3-mini") == "codex"
        assert self.engine_for("o4-mini") == "codex"
        assert self.engine_for("o5-preview") == "codex"
        assert self.engine_for("codex-mini-latest") == "codex"

    def test_default_openai_compatible(self) -> None:
        assert self.engine_for("unknown-model") == "openai-compat"


class TestEffortNormalization:
    def test_codex_effort(self) -> None:
        assert codex_effort("low") == "low"
        assert codex_effort("high") == "high"
        assert codex_effort("xhigh") == "xhigh"
        assert codex_effort("max") == "xhigh"

    def test_none_passthrough(self) -> None:
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


class TestCodexNativeTranslation:
    def test_served_groups_render_mcp_overrides(self) -> None:
        from lup.adapters.clients.codex.translate import build_codex_native
        from lup.adapters.options import LupAgentOptions

        native = build_codex_native(
            LupAgentOptions(
                model="o4-mini",
                system_prompt="test",
                served_tool_groups=["notes"],
            )
        )
        assert any("mcp_servers" in o for o in native.config_overrides)

    def test_no_served_groups_render_no_mcp_overrides(self) -> None:
        from lup.adapters.clients.codex.translate import build_codex_native
        from lup.adapters.options import LupAgentOptions

        native = build_codex_native(
            LupAgentOptions(model="o4-mini", system_prompt="test")
        )
        assert not any("mcp_servers" in o for o in native.config_overrides)


class TestMergeHooks:
    def test_merge_disjoint_events(self) -> None:
        from lup.hooks import LupHookMatcher, LupHookOutput

        async def hook_a(inp: LupHookInput) -> LupHookOutput:
            return allow_hook()

        async def hook_b(inp: LupHookInput) -> LupHookOutput:
            return allow_hook()

        a = LupHooksConfig(pre_tool_use=[LupHookMatcher(hook=hook_a)])
        b = LupHooksConfig(post_tool_use=[LupHookMatcher(hook=hook_b)])
        merged = merge_hooks(a, b)
        assert merged.pre_tool_use
        assert merged.post_tool_use

    def test_merge_same_event(self) -> None:
        from lup.hooks import LupHookMatcher, LupHookOutput

        async def hook_a(inp: LupHookInput) -> LupHookOutput:
            return allow_hook()

        async def hook_b(inp: LupHookInput) -> LupHookOutput:
            return deny_hook("no")

        a = LupHooksConfig(pre_tool_use=[LupHookMatcher(hook=hook_a)])
        b = LupHooksConfig(pre_tool_use=[LupHookMatcher(hook=hook_b)])
        merged = merge_hooks(a, b)
        assert len(merged.pre_tool_use) == 2


class TestLupHooksToClaudeConversion:
    def test_converts_allow_decision(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hook_output_to_claude
        from lup.hooks import LupHookOutput

        output = LupHookOutput(decision="allow")
        result = lup_hook_output_to_claude(output)
        specific = result.get("hookSpecificOutput")
        assert specific is not None and specific["hookEventName"] == "PreToolUse"
        assert specific.get("permissionDecision") == "allow"

    def test_converts_deny_decision(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hook_output_to_claude
        from lup.hooks import LupHookOutput

        output = LupHookOutput(decision="deny", reason="test reason")
        result = lup_hook_output_to_claude(output)
        specific = result.get("hookSpecificOutput")
        assert specific is not None and specific["hookEventName"] == "PreToolUse"
        assert specific.get("permissionDecision") == "deny"
        assert specific.get("permissionDecisionReason") == "test reason"

    def test_converts_block_decision(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hook_output_to_claude
        from lup.hooks import LupHookOutput

        output = LupHookOutput(decision="block", reason="blocked")
        result = lup_hook_output_to_claude(output)
        assert result.get("decision") == "block"
        assert result.get("reason") == "blocked"

    def test_deny_outside_pre_tool_use_converts_to_block(self) -> None:
        """Permission decisions exist only on PreToolUse — a denial from a
        Stop/PostToolUse hook must become the generic block decision, not a
        misrouted PreToolUse hookSpecificOutput."""
        from lup.adapters.clients.claude.hooks import lup_hook_output_to_claude
        from lup.hooks import LupHookOutput

        output = LupHookOutput(decision="deny", reason="not done yet")
        result = lup_hook_output_to_claude(output, event="Stop")
        assert result.get("hookSpecificOutput") is None
        assert result.get("decision") == "block"
        assert result.get("reason") == "not done yet"

    def test_allow_outside_pre_tool_use_is_noop(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hook_output_to_claude
        from lup.hooks import LupHookOutput

        output = LupHookOutput(decision="allow")
        result = lup_hook_output_to_claude(output, event="PostToolUse")
        assert result.get("hookSpecificOutput") is None
        assert result.get("decision") is None

    def test_converts_system_message(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hook_output_to_claude
        from lup.hooks import LupHookOutput

        output = LupHookOutput(system_message="try another way")
        result = lup_hook_output_to_claude(output)
        assert result.get("systemMessage") == "try another way"

    def test_converts_empty_output(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hook_output_to_claude
        from lup.hooks import LupHookOutput

        output = LupHookOutput()
        result = lup_hook_output_to_claude(output)
        assert result.get("decision") is None
        assert result.get("hookSpecificOutput") is None

    def test_full_hook_conversion_roundtrip(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hooks_to_claude

        hooks = create_permission_hooks(rw_dirs=[Path("/data")], ro_dirs=[Path("/ref")])
        claude_hooks = lup_hooks_to_claude(hooks)
        assert "PreToolUse" in claude_hooks
        assert len(claude_hooks["PreToolUse"]) == 1

    def test_matcher_preserved_in_conversion(self) -> None:
        from lup.adapters.clients.claude.hooks import lup_hooks_to_claude

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
        from tests.unit.codex_hooks_reference import lup_hooks_to_codex

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
        from tests.unit.codex_hooks_reference import lup_hooks_to_codex

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
        from tests.unit.codex_hooks_reference import lup_hooks_to_codex

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
        from tests.unit.codex_hooks_reference import lup_hooks_to_codex

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
        from tests.unit.codex_hooks_reference import lup_hooks_to_codex

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
        from tests.unit.codex_hooks_reference import lup_hooks_to_codex

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
