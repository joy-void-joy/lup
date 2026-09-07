"""Invoke served delegated roles through each real application composition."""

from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import TypeAdapter

from lup.providers.claude.runtime import ClaudeSessionConfig, build_claude_options
from lup.providers.codex.runtime import CodexSessionConfig
from lup.orchestration.reflection import ReviewResult, ReviewVerdict
from lup.sessions.client import Client
from lup.sessions.events import TurnTextBlock
from lup.types import SubagentSpec
from lup.workspace.context import SessionContext
from lup_template.agent import core
from lup_template.agent.config import Settings, settings
from lup_template.agent.subagents import get_subagent_specs
from lup_template.agent.tools import reflect
from lup_template.devtools.agent.inspect_agent import InspectPayload, run_inspect
from lup_template.devtools.agent.serve import collect_tools_by_server
from tests.unit.test_template_fixes import static_session_factory


@pytest.fixture
def configured(
    monkeypatch: pytest.MonkeyPatch,
) -> list[ClaudeSessionConfig | CodexSessionConfig]:
    captured: list[ClaudeSessionConfig | CodexSessionConfig] = []

    def capture(config: ClaudeSessionConfig | CodexSessionConfig) -> Client:
        captured.append(config)
        return static_session_factory([TurnTextBlock(text="verified findings")])

    monkeypatch.setattr(core, "create_claude", capture)
    monkeypatch.setattr(core, "create_codex", capture)
    for name in (
        "model",
        "aux_model",
        "openai_base_url",
        "openrouter_api_key",
        "max_turns",
        "max_thinking_tokens",
        "permission_mode",
        "max_budget_usd",
        "codex_sandbox",
        "codex_approval_policy",
        "turn_timeout_seconds",
    ):
        monkeypatch.setattr(settings, name, None)
    monkeypatch.setattr(settings, "sandbox_enabled", False)
    return captured


@pytest.mark.parametrize("engine", ["claude", "codex"])
@pytest.mark.parametrize("name", ["researcher", "analyzer"])
async def test_served_roles_execute_on_the_selected_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured: list[ClaudeSessionConfig | CodexSessionConfig],
    engine: Literal["claude", "codex"],
    name: str,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", engine)
    groups = collect_tools_by_server(
        SessionContext(session_dir=tmp_path, outputs_dir=tmp_path)
    )
    delegate = next(tool for tool in groups["notes"] if tool.name == "run_subagent")
    result = await delegate.handler({"name": name, "task": "Gather evidence"})
    assert not result.get("is_error", False)
    assert "verified findings" in str(result)
    assert len(configured) == 1
    config = configured[0]
    if engine == "claude":
        assert isinstance(config, ClaudeSessionConfig)
        assert config.model == "opus"
        assert config.tools == [
            "Read",
            "Glob",
            "Grep",
            *(["WebSearch", "WebFetch"] if name == "researcher" else []),
        ]
        assert config.allowed_tools == config.tools
        assert config.setting_sources == []
    else:
        assert isinstance(config, CodexSessionConfig)
        assert config.model == "gpt-6-astra"
        assert config.sandbox == "read-only"
        assert config.approval_policy == "never"
        assert config.delegated_tools is not None
        assert config.delegated_tools.workspace_read
        assert config.delegated_tools.web_search == (name == "researcher")


def test_native_and_served_claude_roles_share_the_compiler() -> None:
    options = build_claude_options(
        ClaudeSessionConfig(subagents=get_subagent_specs()),
        binding=lambda: None,
        resume=None,
        session_id=None,
    )
    assert options.agents is not None
    assert options.agents["analyzer"].tools == ["Read", "Glob", "Grep"]
    assert options.agents["researcher"].tools == [
        "Read",
        "Glob",
        "Grep",
        "WebSearch",
        "WebFetch",
    ]
    assert all(agent.model == "opus" for agent in options.agents.values())


def test_inspect_exposes_capabilities_separately_from_exact_grants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_inspect(as_json=True, full=True)
    payload = TypeAdapter(InspectPayload).validate_json(capsys.readouterr().out)
    assert payload["subagents"]["researcher"]["capabilities"] == [
        "workspace-read",
        "web-search",
    ]
    assert payload["subagents"]["analyzer"]["capabilities"] == ["workspace-read"]
    assert all(not spec["tools"] for spec in payload["subagents"].values())


@pytest.mark.parametrize(
    "engine,expected", [("claude", "opus"), ("codex", "gpt-6-astra")]
)
def test_explicit_engine_without_model_selects_native_strongest(
    configured: list[ClaudeSessionConfig | CodexSessionConfig],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    engine: str,
    expected: str,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", engine)
    core.provider_factory(model=None, system_prompt="", cwd=tmp_path)
    assert configured[0].model == expected


@pytest.mark.parametrize(
    "engine,expected", [("claude", "opus"), ("codex", "gpt-6-astra")]
)
def test_unconfigured_model_default_cannot_pin_another_provider(
    configured: list[ClaudeSessionConfig | CodexSessionConfig],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    engine: str,
    expected: str,
) -> None:
    class DefaultSettings(Settings, env_file=None):
        """The shipped defaults without repository-local environment files."""

    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.setattr(settings, "model", DefaultSettings().model)
    monkeypatch.setattr(settings, "agent_sdk", engine)
    core.provider_factory(model=settings.model, system_prompt="", cwd=tmp_path)
    assert configured[0].model == expected


def test_codex_does_not_widen_role_to_session_sandbox(
    configured: list[ClaudeSessionConfig | CodexSessionConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    monkeypatch.setattr(settings, "codex_sandbox", "danger_full_access")
    core.build_subagent_factory(get_subagent_specs()[0])
    assert isinstance(configured[0], CodexSessionConfig)
    assert configured[0].sandbox == "read-only"


def test_model_override_routes_when_no_engine_is_explicit(
    configured: list[ClaudeSessionConfig | CodexSessionConfig],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", None)
    monkeypatch.setattr(settings, "model", "claude-opus-5")
    core.provider_factory(model="gpt-6-astra", system_prompt="", cwd=tmp_path)
    assert isinstance(configured[0], CodexSessionConfig)


def test_codex_explicit_role_turn_cap_is_not_ignored(
    configured: list[ClaudeSessionConfig | CodexSessionConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    spec = SubagentSpec(
        name="bounded", description="Bounded role", prompt="Read", max_turns=2
    )
    with pytest.raises(ValueError, match="max_turns"):
        core.build_subagent_factory(spec)
    assert configured == []


@pytest.mark.parametrize("engine", ["claude", "codex"])
async def test_reviewer_compiles_on_both_engines(
    configured: list[ClaudeSessionConfig | CodexSessionConfig],
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", engine)

    async def answered(
        _self: Client, prompt: str, output_type: type[ReviewResult]
    ) -> SimpleNamespace:
        assert output_type is ReviewResult
        return SimpleNamespace(
            output=ReviewResult(verdict=ReviewVerdict.approve, assessment=prompt)
        )

    monkeypatch.setattr(Client, "query", answered)
    result = await reflect.run_reviewer(
        reflect.ReflectInput(
            assessment="Evidence checked",
            confidence=0.8,
            tool_audit="OK",
            process_reflection="OK",
        ),
        None,
    )
    assert result is not None
    assert result.verdict == ReviewVerdict.approve
    assert len(configured) == 1
    config = configured[0]
    if engine == "codex":
        assert isinstance(config, CodexSessionConfig)
        assert config.delegated_tools is not None
        assert (
            config.delegated_tools.workspace_read and config.delegated_tools.web_search
        )
    else:
        assert isinstance(config, ClaudeSessionConfig)
        assert config.tools == ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]


@pytest.mark.parametrize("failure", ["error", "missing"])
async def test_reviewer_failure_does_not_grant_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    async def failed(
        _validated: reflect.ReflectInput,
        _outputs_dir: Path | None,
        *,
        model: str | None = None,
    ) -> ReviewResult | None:
        if failure == "error":
            raise ValueError("provider could not start")
        return None

    monkeypatch.setattr(reflect, "run_reviewer", failed)
    kit = reflect.create_reflect_tools(session_dir=tmp_path)
    response = await kit["tools"][0].handler(
        {
            "assessment": "Evidence checked",
            "confidence": 0.8,
            "tool_audit": "OK",
            "process_reflection": "OK",
        }
    )
    assert response.get("is_error") is True
    assert not kit["gate"].reflected
