"""Applications can add durable session shapes to generic feedback reports."""

import json

from typer.testing import CliRunner

from lup.devtools.feedback.app import create_feedback_app
from lup.devtools.feedback.models import AgentPrompt, LoadedSession
from lup.types import Usage


def test_cost_report_reads_application_session_loader() -> None:
    session = LoadedSession(
        source_session_id="pipeline-session",
        source_file="snapshot.json",
        session_id="pipeline-session",
        timestamp="2026-08-23T23:00:00Z",
        agent_sdk="claude",
        cost_usd=66.57,
        token_usage=Usage(input_tokens=46_000_000, output_tokens=683_000),
    )
    app = create_feedback_app(
        lambda: AgentPrompt(sections=[], rendered=""),
        lambda _versions: [session],
    )

    result = CliRunner().invoke(app, ["costs", "--all-versions", "--json"])

    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["claude"]["cost_usd"] == 66.57
    assert report["claude"]["input_tokens"] == 46_000_000
