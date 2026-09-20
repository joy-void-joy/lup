"""Policy readiness and the native session execute under one selected boundary."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from lup.policy.identity import POLICY_ROOT_ENV
from lup.providers.codex.app_server import AppServerError
from lup.providers.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheEvidence,
)
from lup.providers.codex.runtime import CodexSessionConfig, CodexSessionOpener


class Invocation(BaseModel):
    arguments: list[str]
    home: str
    marker: str
    policy: str


FAKE_CODEX = """
import json
import os
import sys

with open(os.environ["LUP_NATIVE_PROBE_RECORD"], "a") as record:
    record.write(json.dumps({
        "arguments": sys.argv[1:],
        "home": os.environ["CODEX_HOME"],
        "marker": os.environ["LUP_NATIVE_PROBE_MARKER"],
        "policy": os.environ["LUP_POLICY_ROOT"],
    }) + "\\n")
if sys.argv[1] == "plugin":
    print(json.dumps({"installed": [{
        "pluginId": "lup@application", "version": "revision",
        "installed": True, "enabled": True,
    }]}), flush=True)
else:
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        result = {}
        if request["method"] == "hooks/list":
            if os.environ["LUP_NATIVE_PROBE_HOOK_FAILURE"] == "yes":
                print(json.dumps({"id": request["id"], "error": {
                    "code": -32601, "message": "hook discovery unavailable",
                }}), flush=True)
                continue
            result = {"data": [{
                "cwd": request["params"]["cwds"][0],
                "hooks": [{"key": "policy", "eventName": "preToolUse",
                    "pluginId": "lup@application", "source": "plugin",
                    "enabled": True, "isManaged": False,
                    "currentHash": "digest", "trustStatus": "trusted"}],
            }]}
        print(json.dumps({"id": request["id"], "result": result}), flush=True)
"""


@pytest.mark.parametrize("use_path", [False, True])
@pytest.mark.parametrize("hook_failure", [False, True])
async def test_readiness_and_session_use_the_selected_executable_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_path: bool, hook_failure: bool
) -> None:
    project = tmp_path / "project"
    manifest = project / ".agents/plugins/marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "name": "application",
                "plugins": [
                    {"name": "lup", "source": {"path": ".codex/plugins/lup"}},
                ],
            }
        )
    )
    source = project / ".codex/plugins/lup"
    plugin = source / ".codex-plugin/plugin.json"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(json.dumps({"name": "lup", "hooks": "./hooks/hooks.json"}))
    executable = tmp_path / "bin/codex"
    executable.parent.mkdir()
    executable.write_text(f"#!{sys.executable}\n{FAKE_CODEX}")
    executable.chmod(0o755)
    home = tmp_path / "session-home"
    evidence = PluginCacheEvidence(
        source_root=source,
        installed_root=home / "revision",
        ready=True,
        source_digest="same",
        installed_digest="same",
    )
    ensure = Mock(return_value=evidence)
    monkeypatch.setattr(CodexPluginInstaller, "ensure", ensure)
    monkeypatch.setenv("LUP_NATIVE_PROBE_MARKER", "ambient-must-not-win")
    record = tmp_path / "invocations.jsonl"
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    config = CodexSessionConfig(
        cwd=workspace,
        policy_root=project,
        executable=Path("codex") if use_path else executable,
        environment={
            "CODEX_HOME": str(home),
            "PATH": str(executable.parent),
            "LUP_NATIVE_PROBE_RECORD": str(record),
            "LUP_NATIVE_PROBE_MARKER": "selected",
            "LUP_NATIVE_PROBE_HOOK_FAILURE": "yes" if hook_failure else "no",
            POLICY_ROOT_ENV: "ambient-project-must-not-win",
        },
    )

    if hook_failure:
        with pytest.raises(AppServerError, match="hook discovery unavailable"):
            async with CodexSessionOpener(config).open_session():
                pytest.fail("no session may open without hook discovery")
    else:
        async with CodexSessionOpener(config).open_session():
            pass

    calls = [
        Invocation.model_validate_json(line) for line in record.read_text().splitlines()
    ]
    assert [call.arguments for call in calls] == [
        ["plugin", "list", "--json", "--marketplace", "application"],
        ["app-server"],
        *([] if hook_failure else [["app-server"]]),
    ]
    assert all(call.home == str(home) for call in calls)
    assert all(call.marker == "selected" for call in calls)
    assert all(call.policy == str(project) for call in calls)
    ensure.assert_called_once_with(source, project)
