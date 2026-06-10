"""Smoke suite: every devtools sub-app must at least invoke cleanly.

A broken callback or import takes out a whole sub-app (the version
sub-app once crashed on every invocation and nothing caught it). These
run each sub-app's help plus the key read-only commands in-process.
"""

import pytest
from typer.testing import CliRunner

from lup_template.devtools.main import app

runner = CliRunner()

SMOKE_COMMANDS: list[list[str]] = [
    ["--help"],
    ["version"],
    ["version", "changelog"],
    ["trace", "list"],
    ["feedback", "status"],
    ["setup", "status"],
    ["sync", "status"],
    ["agent", "--help"],
    ["py", "--help"],
    ["dev", "--help"],
    ["usage", "--help"],
]


@pytest.mark.parametrize("args", SMOKE_COMMANDS, ids=lambda args: " ".join(args))
def test_command_exits_cleanly(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
