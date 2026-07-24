"""Regression tests for the provider-neutral application template."""

from datetime import datetime
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import pytest

from lup_template.agent import prompts
from lup.reflect import ReviewGate
from lup_template.agent.config import aux_model, engine_for_settings, settings
from lup_template.agent.core import reflection_submission_gate
from lup.runtime.contracts import SessionFactory
from lup.runtime.models import SessionHandle, SessionId
from lup.runtime.wrappers import DecoratingSessionFactory
from lup.telemetry.trace import TraceLogger
from lup.workspace.notes import NotesConfig
from lup_template.agent.core import decorate_factory, provider_factory
from lup_template.agent.models import AgentOutput
from lup_template.agent.tool_policy import ToolPolicy


def test_prompt_renders_with_literal_braces_in_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_section = '## Output\n```json\n{"probability": 0.5, "factors": []}\n```'
    monkeypatch.setattr(prompts, "SECTIONS", ["Today is {date}.", json_section])

    rendered = prompts.get_system_prompt()

    assert '{"probability": 0.5, "factors": []}' in rendered
    assert "{date}" not in rendered


def test_prompt_substitutes_date_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "SECTIONS", ["date={date}"])
    assert "date=2030-01-02" in prompts.get_system_prompt(date=datetime(2030, 1, 2))


def test_output_format_section_derives_from_model() -> None:
    section = prompts.output_format()
    for field_name in AgentOutput.model_fields:
        assert field_name in section


def test_allowed_tools_are_supplied_by_the_concrete_composition() -> None:
    builtins = frozenset(  # lup: ignore[frozenset-shape] — immutable policy fixture
        {"Read", "TodoWrite"}
    )
    allowed = ToolPolicy(settings).get_allowed_tools({}, builtin_tools=builtins)
    assert allowed == ["Read", "TodoWrite"]


def test_aux_model_explicit_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "aux_model", "my-reviewer")
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    assert aux_model() == "my-reviewer"


def test_aux_model_claude_defaults_to_opus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "aux_model", None)
    monkeypatch.setattr(settings, "agent_sdk", "claude")
    monkeypatch.setattr(settings, "openai_base_url", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    assert aux_model() == "claude-opus-4-6"


def test_aux_model_compat_endpoint_reuses_session_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "aux_model", None)
    monkeypatch.setattr(settings, "agent_sdk", "claude")
    monkeypatch.setattr(settings, "model", "anthropic/claude-opus-4.6")
    monkeypatch.setattr(settings, "openai_base_url", None)
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    assert aux_model() == "anthropic/claude-opus-4.6"


def test_engine_router_explicit_agent_sdk_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", "claude")
    monkeypatch.setattr(settings, "model", "gpt-5.6-sol")
    assert engine_for_settings() == "claude"


def test_engine_router_claude_prefix_runs_native_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", None)
    monkeypatch.setattr(settings, "model", "claude-fable-5")
    assert engine_for_settings() == "claude"


def test_engine_router_openai_prefixes_run_codex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", None)
    for model in ("gpt-5.6-sol", "o4-mini", "codex-mini-latest"):
        monkeypatch.setattr(settings, "model", model)
        assert engine_for_settings() == "codex"


def test_engine_router_openrouter_fallback_runs_claude_compat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", None)
    monkeypatch.setattr(settings, "model", "anthropic/claude-opus-4.6")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    assert engine_for_settings() == "claude-compat"


def test_engine_router_unknown_model_runs_openai_compat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", None)
    monkeypatch.setattr(settings, "model", "llama-4-scout")
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    assert engine_for_settings() == "openai-compat"


def test_aux_model_follows_the_routed_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "aux_model", None)
    monkeypatch.setattr(settings, "agent_sdk", None)
    monkeypatch.setattr(settings, "model", "gpt-5.6-sol")
    assert aux_model() == "gpt-5.6-sol"


def test_aux_model_codex_reuses_session_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "aux_model", None)
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    monkeypatch.setattr(settings, "model", "gpt-5.5")
    assert aux_model() == "gpt-5.5"


@pytest.mark.asyncio
async def test_reflection_gate_is_the_typed_submission_gate() -> None:
    review = ReviewGate()
    gate = reflection_submission_gate(review)
    output = AgentOutput(summary="complete")

    assert not (await gate(output)).accepted
    review.mark_reflected()
    assert (await gate(output)).accepted


class UnopenedFactory(SessionFactory):
    def open(
        self, resume: SessionId | None = None
    ) -> AbstractAsyncContextManager[SessionHandle]:
        raise RuntimeError(f"fixture factory is not opened: {resume}")


def test_main_factory_decoration_wires_persistence_display_and_trace(
    tmp_path: Path,
) -> None:
    notes = NotesConfig(
        session=tmp_path / "session",
        output=tmp_path / "output",
        trace_log=tmp_path / "logs" / "trace.md",
    )
    trace = TraceLogger(trace_path=notes.trace_log, title="test")

    decorated = decorate_factory(UnopenedFactory(), notes=notes, trace_logger=trace)

    assert isinstance(decorated, DecoratingSessionFactory)
    assert decorated.persistence is not None
    assert decorated.display is not None
    assert decorated.tracing is not None


def test_codex_rejects_explicit_claude_only_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    monkeypatch.setattr(settings, "permission_mode", "plan")

    with pytest.raises(ValueError, match="AGENT_PERMISSION_MODE"):
        provider_factory(model="gpt", system_prompt="", cwd=tmp_path)
