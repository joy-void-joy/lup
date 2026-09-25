"""The native project declaration carries its launch identity to stdio groups."""

import tomllib
import os
import sys
from pathlib import Path

import pytest
from lup.harness.environment import tool_server_env
from lup.devtools.dev.pyright_oracle import pyright_settings
from lup.devtools.launcher import ENVIRONMENT_VARIABLE

from lup.coordination.identity import MEMBER_ENV, NAME_ENV
from lup.coordination.peer_tools import RosterPulse
from lup.coordination.relay import InboxRelay
from lup.providers.codex.harness import CodexSpellings, codex_project_config
from lup_template.devtools.agent.serve import (
    collect_session_toolset,
    harness_session_context,
)
from lup_template.harness.catalog import HARNESS_SESSION, portable_harness


def test_rendered_forwarding_keeps_launcher_identity_in_the_stdio_assembly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = tomllib.loads(codex_project_config(portable_harness(), CodexSpellings()))
    parent = {
        MEMBER_ENV: "launched-recipient",
        NAME_ENV: "review-recipient",
        ENVIRONMENT_VARIABLE: ".venv-contained",
    }
    interpreter = (
        tmp_path
        / parent[ENVIRONMENT_VARIABLE]
        / Path(sys.executable).parent.name
        / ("python.exe" if os.name == "nt" else "python")
    )
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    for name in parent:
        monkeypatch.delenv(name, raising=False)
    assert all(
        server.get("env_vars") == tool_server_env()
        for server in config["mcp_servers"].values()
    )
    assert MEMBER_ENV in tool_server_env() and NAME_ENV in tool_server_env()
    assert ENVIRONMENT_VARIABLE in tool_server_env()
    for name in config["mcp_servers"]["coordination"]["env_vars"]:
        if name in parent:
            monkeypatch.setenv(name, parent[name])
        else:
            monkeypatch.delenv(name, raising=False)
    context = harness_session_context(HARNESS_SESSION)
    toolset = collect_session_toolset(context, identity="")
    assert toolset is not None
    pulse, relay = toolset.companions["coordination"]
    assert isinstance(pulse, RosterPulse) and isinstance(relay, InboxRelay)
    assert pulse.member_id == relay.member_id == parent[MEMBER_ENV]
    assert "coordination" in toolset.groups
    assert pyright_settings(tmp_path) == {"python": {"pythonPath": str(interpreter)}}
