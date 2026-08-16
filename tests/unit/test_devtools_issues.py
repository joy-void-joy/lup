"""Behavior tests for structured workflow-friction reports."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from lup.devtools.dev import issues
from lup_template.devtools.main import app


def friction_report() -> issues.FrictionReport:
    return issues.FrictionReport(
        summary="Detached resolver lost its run",
        component="Codex resolver launcher",
        command="uv run lup-devtools harness resolve start --detach",
        error="run `resolve-123` does not exist",
        state="a watcher path was printed but no run directory exists",
        recovery_cost="inspect state, abort stale runs, and restart in foreground",
    )


def friction_arguments() -> list[str]:
    report = friction_report()
    return [
        "dev",
        "report-friction",
        "--summary",
        report.summary,
        "--component",
        report.component,
        "--command",
        report.command,
        "--error",
        report.error,
        "--state",
        report.state,
        "--recovery-cost",
        report.recovery_cost,
    ]


def test_report_body_labels_every_observation() -> None:
    body = friction_report().body()
    assert "## Owning component" in body
    assert "## Exact command" in body
    assert "## Exact error" in body
    assert "## State left behind" in body
    assert "## Recovery cost" in body
    assert "uv run lup-devtools harness resolve start --detach" in body


def test_report_body_escapes_evidence_as_literal_text() -> None:
    report = friction_report().model_copy(update={"error": "</code>`boom` &"})
    body = report.body()
    assert "&lt;/code&gt;`boom` &amp;" in body
    assert "</code>`boom` &" not in body


def test_filing_targets_the_checkout_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    fake_gh = SimpleNamespace(
        out=lambda *arguments: (
            calls.append(arguments) or "https://github.test/o/r/issues/9\n"
        )
    )
    monkeypatch.setattr(issues, "gh", fake_gh)
    monkeypatch.setattr(issues, "repository_slug", lambda: "owner/repository")
    url = issues.file_friction_report(friction_report())
    assert url == "https://github.test/o/r/issues/9"
    assert calls == [
        (
            "issue",
            "create",
            "--repo",
            "owner/repository",
            "--title",
            friction_report().summary,
            "--body",
            friction_report().body(),
        )
    ]


def test_filing_requires_an_explicit_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(issues, "repository_slug", lambda: "")
    with pytest.raises(RuntimeError, match="origin names no GitHub repository"):
        issues.file_friction_report(friction_report())


def test_cli_reports_tracker_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = Mock(side_effect=RuntimeError("tracker unavailable"))
    monkeypatch.setattr(issues, "file_friction_report", failure)
    result = CliRunner().invoke(app, friction_arguments())
    assert result.exit_code == 1
    assert "tracker unavailable" in result.output
