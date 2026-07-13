"""Behavior tests for the ``lup-devtools claude`` runner's arg forwarding.

The ``claude`` group routes any non-subcommand invocation through ``run`` so
``claude <args>`` forwards straight to the ``claude`` CLI, while real
subcommands (``usage``) still dispatch. These stub the exec and pin which args
reach the runner versus which dispatch a subcommand.
"""

import pytest
from typer.testing import CliRunner

import lup_template.devtools.claude.run as run
from lup_template.devtools.claude.app import app

runner = CliRunner()


@pytest.fixture
def forwarded(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture the ``extra_args`` of each ``run_claude`` call; stub the exec."""
    calls: list[list[str]] = []

    def fake_run_claude(
        profile: str | None,
        model: str | None,
        no_tools: bool,
        no_plugin: bool,
        with_prompt: bool,
        extra_args: list[str],
    ) -> None:
        calls.append(extra_args)

    monkeypatch.setattr(run, "run_claude", fake_run_claude)
    return calls


def test_bare_flag_forwards_to_claude(forwarded: list[list[str]]) -> None:
    result = runner.invoke(app, ["--resume"])
    assert result.exit_code == 0, result.output
    assert forwarded == [["--resume"]]


def test_subcommand_like_args_forward(forwarded: list[list[str]]) -> None:
    result = runner.invoke(app, ["mcp", "list"])
    assert result.exit_code == 0, result.output
    assert forwarded == [["mcp", "list"]]


def test_explicit_run_forwards_without_dashes(forwarded: list[list[str]]) -> None:
    result = runner.invoke(app, ["run", "--resume"])
    assert result.exit_code == 0, result.output
    assert forwarded == [["--resume"]]


def test_no_args_launches_with_defaults(forwarded: list[list[str]]) -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    assert forwarded == [[]]


def test_usage_subcommand_is_not_forwarded(forwarded: list[list[str]]) -> None:
    result = runner.invoke(app, ["usage", "--help"])
    assert result.exit_code == 0, result.output
    assert forwarded == []
