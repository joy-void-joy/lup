"""Regression tests for template application fixes.

These cover the failure modes that surface only after a downstream
project customizes the template via /lup:init:

- A customized prompt section containing literal ``{`` / ``}`` braces
  (a JSON output example) must not crash prompt composition.
- The no-output fallback must stay valid when ``AgentOutput`` gains a
  required domain field.
- The built-in tool set must not advertise tools the SDK doesn't expose.
"""

from pathlib import Path

import pytest
from pydantic import Field

from lup_template.agent import prompts
from lup_template.agent.config import aux_model, settings
from lup_template.agent.core import build_result
from lup_template.agent.models import AgentOutput
from lup_template.agent.tool_policy import CLAUDE_BUILTIN_TOOLS, ToolPolicy
from lup.types import LupResponse, LupResultMessage


def test_prompt_renders_with_literal_braces_in_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A section with a literal JSON example must not break composition.

    ``.format(date=...)`` over such a section would raise KeyError on the
    JSON keys; the regression is that customized prose with braces renders
    verbatim while ``{date}`` is still substituted.
    """
    json_section = '## Output\n```json\n{"probability": 0.5, "factors": []}\n```'
    dated_section = "Today is {date}."
    monkeypatch.setattr(prompts, "SECTIONS", [dated_section, json_section])

    rendered = prompts.get_system_prompt()

    assert '{"probability": 0.5, "factors": []}' in rendered
    assert "{date}" not in rendered
    # The literal braces survived untouched (no substitution applied).
    assert '"factors": []' in rendered


def test_prompt_substitutes_date_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """The {date} placeholder is replaced with the rendered date."""
    monkeypatch.setattr(prompts, "SECTIONS", ["date={date}"])
    from datetime import datetime

    rendered = prompts.get_system_prompt(date=datetime(2030, 1, 2))

    assert "date=2030-01-02" in rendered


def test_output_format_section_derives_from_model() -> None:
    """The output-format section lists AgentOutput's actual fields.

    Derivation (not a hand-written list) is what keeps the prompt in sync
    when models.py changes, so every model field must appear by name.
    """
    section = prompts.output_format()
    for field_name in AgentOutput.model_fields:
        assert field_name in section


def test_empty_output_is_valid() -> None:
    """The no-output fallback constructs a valid AgentOutput."""
    output = AgentOutput.empty()
    assert isinstance(output, AgentOutput)


def test_empty_fallback_survives_required_domain_field() -> None:
    """A domain that adds a required field can keep the fallback valid.

    Because the fallback lives on the model (``empty()``), a customized
    subclass supplies the new field there — constructing it must not raise
    ValidationError the way a fixed ``AgentOutput(summary=..., ...)`` in
    orchestration would.
    """

    class DomainOutput(AgentOutput):
        probability: float = Field(ge=0.0, le=1.0)

        @classmethod
        def empty(cls) -> "DomainOutput":
            return cls(summary="No output produced", probability=0.0)

    output = DomainOutput.empty()
    assert output.probability == 0.0


def test_build_result_falls_back_when_no_output_submitted(tmp_path: Path) -> None:
    """build_result tolerates a session that never submitted output.

    With no output.json on disk it must produce a valid result using the
    model-owned fallback rather than raising.
    """
    session_dir = tmp_path / "session"
    session_dir.mkdir()

    response = LupResponse(result=LupResultMessage(result="done", duration_ms=1000.0))

    result = build_result(
        session_id="s1",
        task_id="t1",
        response=response,
        session_dir=session_dir,
    )

    assert result.output == AgentOutput.empty()
    assert result.session_id == "s1"


def test_builtin_tools_excludes_todoread() -> None:
    """TodoRead is not a current Claude Code tool; only TodoWrite exists."""
    assert "TodoRead" not in CLAUDE_BUILTIN_TOOLS
    assert "TodoWrite" in CLAUDE_BUILTIN_TOOLS


def test_allowed_tools_excludes_todoread() -> None:
    """The computed allow-list also omits the stale TodoRead tool."""
    allowed = ToolPolicy(settings).get_allowed_tools({})
    assert "TodoRead" not in allowed
    assert "TodoWrite" in allowed


def test_codex_session_env_relays_backend_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The serve-tools subprocess resolves aux_model() from its own
    settings, and the Codex runtime does not inherit the shell env —
    the relay must carry the inputs that resolution needs."""
    from lup.notes import NotesConfig

    from lup_template.agent.core import build_codex_session

    monkeypatch.setattr(settings, "agent_sdk", "codex")
    monkeypatch.setattr(settings, "model", "gpt-5.5")
    monkeypatch.setattr(settings, "aux_model", None)
    notes = NotesConfig(
        session=tmp_path / "session",
        output=tmp_path / "outputs" / "t1",
        trace_log=tmp_path / "trace.md",
        rw=[tmp_path / "session"],
    )

    _prompt, mcp_env, _roots = build_codex_session(notes)

    assert mcp_env["AGENT_SDK"] == "codex"
    assert mcp_env["AGENT_MODEL"] == "gpt-5.5"
    assert "AGENT_AUX_MODEL" not in mcp_env

    monkeypatch.setattr(settings, "aux_model", "my-reviewer")
    _prompt, mcp_env, _roots = build_codex_session(notes)

    assert mcp_env["AGENT_AUX_MODEL"] == "my-reviewer"


async def test_persistent_entry_point_rejects_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relay entry point is codex/openai-only; Claude persistent mode
    is in-process and must not silently fall through to the relay."""
    from lup_template.agent.core import run_persistent_agent

    monkeypatch.setattr(settings, "agent_sdk", "claude")
    with pytest.raises(ValueError, match="AGENT_SDK=codex or openai"):
        await run_persistent_agent("hello")


def test_aux_model_explicit_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """AGENT_AUX_MODEL overrides backend resolution."""
    monkeypatch.setattr(settings, "aux_model", "my-reviewer")
    monkeypatch.setattr(settings, "agent_sdk", "codex")

    assert aux_model() == "my-reviewer"


def test_aux_model_claude_defaults_to_opus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude sessions get an opus-class auxiliary model (best results on subscription)."""
    monkeypatch.setattr(settings, "aux_model", None)
    monkeypatch.setattr(settings, "agent_sdk", "claude")

    assert aux_model() == "claude-opus-4-6"


def test_aux_model_codex_reuses_session_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex/OpenAI sessions reuse the session model, which the account
    is known to accept — no Anthropic credentials required."""
    monkeypatch.setattr(settings, "aux_model", None)
    monkeypatch.setattr(settings, "agent_sdk", "codex")
    monkeypatch.setattr(settings, "model", "gpt-5.5")

    assert aux_model() == "gpt-5.5"
