"""Interactive launchers carry the application environment into native hooks."""

from pathlib import Path
from unittest.mock import Mock

import pytest

import lup.devtools.harness.launch as launch
from lup.harness.clipboard import ClipboardBridge
from lup.policy.identity import POLICY_ROOT_ENV
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.login import ProviderLogin
from lup.types import EnvVars


@pytest.mark.parametrize("sandbox", list(launch.LaunchSandbox))
@pytest.mark.parametrize(
    "cli,login", [("claude", CLAUDE_LOGIN), ("codex", CODEX_LOGIN)]
)
def test_interactive_launch_replaces_inherited_policy_root_and_forwards_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sandbox: launch.LaunchSandbox,
    cli: str,
    login: ProviderLogin,
) -> None:
    project = tmp_path / "application with spaces"
    project.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(launch, "project_root", lambda: project)
    monkeypatch.setattr(launch, "accessible_roots", lambda *args: [])
    monkeypatch.setattr(launch, "settle_boundary", Mock())
    monkeypatch.setattr(launch, "say_opening", Mock())
    monkeypatch.setattr(launch, "verify_inside", Mock(return_value=[]))
    contained = Mock(return_value=["podman", "run", "-it", "image"])
    monkeypatch.setattr(launch, "contained_argv", contained)
    composition = Mock()
    composition.recipe.source.image.config_home = "/cfg"
    composition.recipe.source.image.forge.sourced.return_value = ""
    composition.recipe.source.image.clipboard = ClipboardBridge()
    composition.clipboard_transport = "commands"
    environment: EnvVars = {POLICY_ROOT_ENV: str(tmp_path / "inherited-project")}

    launch.session_argv(
        cli, [], composition, Mock(hooks=None), tmp_path, login, sandbox, environment
    )

    assert environment[POLICY_ROOT_ENV] == str(project)
    if sandbox.contained():
        assert POLICY_ROOT_ENV in contained.call_args.kwargs["inherited_environment"]
        assert contained.call_args.args[2] == project
    else:
        contained.assert_not_called()
