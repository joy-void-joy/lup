"""A session's model and effort, compiled for each CLI and refused where wrong.

The catalog is only worth its types where it is consulted: a tier resolves to
the lineup's model, ``ultra`` becomes each CLI's own spelling of it, and an
effort a model does not take is refused where the session is declared — never
dropped by the CLI, never narrowed to a rung the model has.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lup.devtools.harness.launch import LaunchSandbox, claude_sandbox_arguments
from lup.harness.models import HookSandbox, HookSet, Plugin
from lup.providers.claude.confinement import CLAUDE_CONFINEMENT
from lup.providers.claude.model_choice import (
    claude_effort,
    claude_effort_named,
    claude_model_id,
    claude_model_name,
    listed_claude_model,
)
from lup.providers.claude.runtime import (
    ClaudeSandboxConfig,
    ClaudeSessionConfig,
    build_claude_options,
)
from lup.providers.claude.selection import CLAUDE_RUNTIME, claude_config
from lup.providers.codex.model_choice import (
    codex_effort_arguments,
    codex_effort_named,
    codex_model_id,
)
from lup.providers.codex.runtime import CodexSessionConfig
from lup.providers.codex.selection import CODEX_RUNTIME, codex_config
from lup.providers.codex.subagents import CodexModelTiers
from lup.providers.selection import SessionRequest
from lup.types import CustomModel

SESSION = "18f5debf-499a-42bb-8856-0b39dd59943d"


def test_a_tier_compiles_to_each_lineups_model() -> None:
    assert claude_model_id("frontier") == "fable"
    assert claude_model_id("strongest") == "opus"
    assert claude_model_id("inherit") is None
    assert claude_model_name("fast") == "haiku"

    tiers = CodexModelTiers()
    assert codex_model_id("frontier", tiers) == "gpt-6-astra"
    assert codex_model_id("strongest", tiers) == "gpt-5.6-sol"
    assert codex_model_id("balanced", tiers) == "gpt-5.6-terra"
    assert codex_model_id("fast", tiers) == "gpt-6-luna"
    assert codex_model_id("inherit", tiers) is None


def test_a_replaced_tier_table_is_the_one_a_session_resolves() -> None:
    endpoint = CodexModelTiers(strongest=CustomModel(id="served-large"))
    config = CodexSessionConfig(model="strongest", model_tiers=endpoint, cwd=Path("."))

    assert config.model_id() == "served-large"
    assert config.model_selection() == {"model": "served-large", "effort": "medium"}


def test_a_custom_id_reaches_the_cli_unchanged() -> None:
    assert claude_model_id(CustomModel(id="local-model")) == "local-model"
    assert codex_model_id(CustomModel(id="local"), CodexModelTiers()) == "local"
    assert ClaudeSessionConfig(model=CustomModel(id="x")).model_id() == "x"


def test_a_misspelt_model_is_refused_where_it_is_written() -> None:
    with pytest.raises(ValidationError):
        ClaudeSessionConfig.model_validate({"model": "claude-opsu"})
    with pytest.raises(ValidationError):
        CodexSessionConfig.model_validate({"model": "gpt-6-astr", "cwd": "."})


def test_ultra_compiles_to_xhigh_with_ultracode_for_the_sdk() -> None:
    options = build_claude_options(
        ClaudeSessionConfig(model="opus", effort="ultra"),
        binding=lambda: None,
        resume=None,
        session_id=SESSION,
    )

    assert options.effort == "xhigh"
    assert options.settings is not None
    assert json.loads(options.settings) == {"ultracode": True}


def test_every_other_effort_reaches_the_sdk_unchanged_and_alone() -> None:
    for effort in ("low", "medium", "high", "xhigh", "max"):
        options = build_claude_options(
            ClaudeSessionConfig(model="opus", effort=effort),
            binding=lambda: None,
            resume=None,
            session_id=SESSION,
        )
        assert options.effort == effort
        assert options.settings is None


def test_an_ultra_session_keeps_its_sandbox_in_the_same_settings() -> None:
    """The SDK merges its sandbox into the settings document it is given."""
    options = build_claude_options(
        ClaudeSessionConfig(
            model="opus", effort="ultra", sandbox=ClaudeSandboxConfig()
        ),
        binding=lambda: None,
        resume=None,
        session_id=SESSION,
    )

    assert options.settings is not None
    assert json.loads(options.settings) == {"ultracode": True}
    assert options.sandbox is not None


def test_ultra_on_the_command_line_is_one_settings_document() -> None:
    """The CLI reads one ``--settings``; a second would replace the first."""
    compiled = claude_effort("ultra")
    plugin = Plugin(
        id="plugin.probe",
        name="probe",
        description="a plugin declaring a boundary",
        version="0.0.0",
        marketplace="probe",
        skills=[],
        agents=[],
        hooks=HookSet(id="hooks.probe", policy_ids=[], sandbox=HookSandbox()),
    )

    assert compiled.arguments() == ["--effort", "xhigh"]
    arguments = claude_sandbox_arguments(
        plugin, sandbox=LaunchSandbox.OUTER, settings=compiled.settings
    )
    assert arguments[0] == "--settings"
    assert arguments.count("--settings") == 1
    assert json.loads(arguments[1]) == {
        "sandbox": {"enabled": False},
        "ultracode": True,
    }
    assert (
        claude_sandbox_arguments(plugin, sandbox=LaunchSandbox.OUTER)
        == CLAUDE_CONFINEMENT.off
    )


def test_codex_takes_ultra_under_its_own_name() -> None:
    assert codex_effort_arguments("ultra") == [
        "--config",
        'model_reasoning_effort="ultra"',
    ]
    config = CodexSessionConfig(model="gpt-6-astra", effort="ultra", cwd=Path("."))
    assert config.model_selection() == {"model": "gpt-6-astra", "effort": "ultra"}


def test_an_effort_the_model_lacks_is_refused_at_declaration() -> None:
    with pytest.raises(ValidationError, match="does not take effort 'ultra'"):
        CodexSessionConfig(model="gpt-6-luna", effort="ultra", cwd=Path("."))
    with pytest.raises(ValidationError, match="does not take effort 'max'"):
        CodexSessionConfig(model="gpt-5.5", effort="max", cwd=Path("."))
    with pytest.raises(ValidationError, match="does not take effort 'high'"):
        ClaudeSessionConfig(model="haiku", effort="high")
    with pytest.raises(ValidationError, match="does not take effort 'xhigh'"):
        ClaudeSessionConfig(model="claude-opus-4-6", effort="xhigh")


def test_a_tier_is_refused_what_its_model_lacks() -> None:
    """``fast`` is luna on Codex, whose catalog row stops below ultra."""
    with pytest.raises(ValidationError, match="gpt-6-luna"):
        CodexSessionConfig(model="fast", effort="ultra", cwd=Path("."))


def test_the_paired_effort_is_checked_like_a_named_one() -> None:
    """A model is never sent alone, so its paired rung has to be one it takes."""
    with pytest.raises(ValidationError, match="does not take effort 'max'"):
        CodexSessionConfig(model="gpt-5.5", paired_effort="max", cwd=Path("."))


def test_what_the_catalog_cannot_see_is_left_to_the_cli() -> None:
    ClaudeSessionConfig(model=CustomModel(id="served"), effort="ultra")
    ClaudeSessionConfig(effort="max")
    CodexSessionConfig(model=CustomModel(id="local"), effort="ultra", cwd=Path("."))
    CodexSessionConfig(model="inherit", effort="ultra", cwd=Path("."))


def test_a_model_the_other_runtime_lists_is_refused_by_this_one() -> None:
    with pytest.raises(ValueError, match="not a model Claude Code lists"):
        CLAUDE_RUNTIME.session_factory(SessionRequest(model="gpt-6-astra"))
    with pytest.raises(ValueError, match="not a model Codex lists"):
        CODEX_RUNTIME.session_factory(SessionRequest(model="opus", cwd=Path(".")))


def test_a_portable_tier_reaches_both_runtimes() -> None:
    request = SessionRequest(model="frontier", cwd=Path("."))

    assert claude_config(request).model_id() == "fable"
    assert codex_config(request).model_id() == "gpt-6-astra"


def test_text_from_a_launcher_flag_is_read_against_the_catalog() -> None:
    assert listed_claude_model("opus[1m]") == "opus[1m]"
    assert listed_claude_model("claude-next") is None
    assert claude_effort_named("ultra") == "ultra"
    assert codex_effort_named("max") == "max"
    with pytest.raises(ValueError, match="not an effort Claude Code takes"):
        claude_effort_named("minimal")
    with pytest.raises(ValueError, match="not an effort Codex takes"):
        codex_effort_named("none")
