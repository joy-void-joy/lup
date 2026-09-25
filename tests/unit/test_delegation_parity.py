"""Invoke served delegated roles through each real application composition."""

from pathlib import Path
from datetime import timedelta
from typing import Literal

import pytest
from pydantic import BaseModel, TypeAdapter

from lup.providers.claude import Claude, ClaudeTools
from lup.providers.claude.runtime import build_claude_options
from lup.providers.codex import Codex
from lup.orchestration.reflection import ReviewResult, ReviewVerdict
from lup.sessions.events import (
    SessionId,
    TurnId,
    TurnIdentifiers,
    TurnInput,
    TurnResult,
    TurnTextBlock,
)
from lup.types import SubagentSpec, Usage
from lup.workspace.context import SessionContext
from lup_template.agent import core
from lup_template.agent.config import Settings, settings
from lup_template.agent.subagents import get_subagent_specs
from lup_template.agent.tools import reflect
from lup_template.devtools.agent.inspect_agent import InspectPayload, run_inspect
from lup_template.devtools.agent.serve import collect_tools_by_server


@pytest.fixture
def configured(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Claude | Codex]:
    captured: list[Claude | Codex] = []

    async def answer(
        agent: Claude | Codex,
        prompt: str | TurnInput,
        output: type[BaseModel] | None = None,
    ) -> TurnResult[None]:
        """Answer a one-shot ask without a session, keeping who was asked."""
        captured.append(agent)
        return TurnResult[None](
            output=None,
            messages=[],
            blocks=[TurnTextBlock(text="verified findings")],
            usage=Usage(),
            duration=timedelta(),
            identifiers=TurnIdentifiers(
                session=SessionId(value="delegated"), turn=TurnId(value="once")
            ),
        )

    monkeypatch.setattr(Claude, "ask", answer)
    monkeypatch.setattr(Codex, "ask", answer)
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
    configured: list[Claude | Codex],
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
        assert isinstance(config, Claude)
        assert config.model_id() == "opus"
        assert config.tools.builtin == [
            "Read",
            "Glob",
            "Grep",
            *(["WebSearch", "WebFetch"] if name == "researcher" else []),
        ]
        assert config.allowed_tools == config.tools.builtin
        assert config.setting_sources == []
    else:
        assert isinstance(config, Codex)
        assert config.model_id() == "gpt-5.6-sol"
        assert config.sandbox == "read-only"
        assert config.approval_policy == "never"
        assert config.delegated_tools is not None
        assert config.delegated_tools.workspace_read
        assert config.delegated_tools.web_search == (name == "researcher")


def test_native_and_served_claude_roles_share_the_compiler() -> None:
    options = build_claude_options(
        Claude(subagents=get_subagent_specs(), tools=ClaudeTools(builtin="stock")),
        servers={},
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
    "engine,expected", [("claude", "opus"), ("codex", "gpt-5.6-sol")]
)
def test_explicit_engine_without_model_selects_native_strongest(
    configured: list[Claude | Codex],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    engine: str,
    expected: str,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", engine)
    agent = core.provider_factory(model=None, system_prompt="", cwd=tmp_path)
    assert isinstance(agent, Claude | Codex)
    assert agent.model == "strongest"
    assert agent.model_id() == expected


@pytest.mark.parametrize(
    "engine,expected", [("claude", "opus"), ("codex", "gpt-5.6-sol")]
)
def test_unconfigured_model_default_cannot_pin_another_provider(
    configured: list[Claude | Codex],
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
    agent = core.provider_factory(model=settings.model, system_prompt="", cwd=tmp_path)
    assert isinstance(agent, Claude | Codex)
    assert agent.model_id() == expected


def test_codex_does_not_widen_role_to_session_sandbox(
    configured: list[Claude | Codex],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    monkeypatch.setattr(settings, "codex_sandbox", "danger_full_access")
    agent = core.build_subagent_factory(get_subagent_specs()[0])
    assert isinstance(agent, Codex)
    assert agent.sandbox == "read-only"


def test_model_override_routes_when_no_engine_is_explicit(
    configured: list[Claude | Codex],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", None)
    monkeypatch.setattr(settings, "model", "claude-opus-5")
    agent = core.provider_factory(model="gpt-6-astra", system_prompt="", cwd=tmp_path)
    assert isinstance(agent, Codex)


def test_codex_explicit_role_turn_cap_is_not_ignored(
    configured: list[Claude | Codex],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    spec = SubagentSpec(
        name="bounded", description="Bounded role", prompt="Read", max_turns=2
    )
    with pytest.raises(ValueError, match="max_turns"):
        core.build_subagent_factory(spec)


@pytest.mark.parametrize("engine", ["claude", "codex"])
async def test_reviewer_compiles_on_both_engines(
    configured: list[Claude | Codex],
    monkeypatch: pytest.MonkeyPatch,
    engine: str,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", engine)

    async def reviewed(
        agent: Claude | Codex,
        prompt: str | TurnInput,
        output: type[BaseModel] | None = None,
    ) -> TurnResult[ReviewResult]:
        """Review without a session, keeping which agent was asked."""
        assert output is ReviewResult
        configured.append(agent)
        return TurnResult[ReviewResult](
            output=ReviewResult(
                verdict=ReviewVerdict.approve,
                assessment=prompt if isinstance(prompt, str) else prompt.text,
            ),
            messages=[],
            blocks=[],
            usage=Usage(),
            duration=timedelta(),
            identifiers=TurnIdentifiers(
                session=SessionId(value="reviewed"), turn=TurnId(value="once")
            ),
        )

    monkeypatch.setattr(Claude, "ask", reviewed)
    monkeypatch.setattr(Codex, "ask", reviewed)
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
        assert isinstance(config, Codex)
        assert config.delegated_tools is not None
        assert (
            config.delegated_tools.workspace_read and config.delegated_tools.web_search
        )
    else:
        assert isinstance(config, Claude)
        assert config.tools.builtin == [
            "Read",
            "Glob",
            "Grep",
            "WebSearch",
            "WebFetch",
        ]


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
