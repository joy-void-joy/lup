"""Plugin readiness is measured where the session actually opens its home."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import sh

import lup.devtools.harness.launch as launch
import lup.providers.codex.install as installation
import lup.providers.codex.runtime as runtime
from lup.harness.clipboard import ClipboardBridge
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.codex.marketplace import CodexMarketplace
from lup.providers.codex.selection import codex_config
from lup.providers.selection import SessionRequest
from lup.providers.codex.harness_runtime import (
    CodexPluginInstaller,
    PluginCacheConfig,
    PluginCacheEvidence,
)


@pytest.fixture
def boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    composition = Mock()
    composition.recipe.source.image.config_home = "/cfg"
    composition.recipe.source.image.forge.sourced.return_value = ""
    composition.recipe.source.image.clipboard = ClipboardBridge()
    composition.clipboard_transport = "commands"
    monkeypatch.setattr(launch, "accessible_roots", lambda *args: [])
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "settle_boundary", Mock())
    monkeypatch.setattr(launch, "say_opening", Mock())
    monkeypatch.setattr(launch, "verify_inside", Mock(return_value=[]))
    monkeypatch.setattr(
        launch, "contained_argv", Mock(return_value=["podman", "run", "-it", "image"])
    )
    return composition


@pytest.mark.parametrize("sandbox", list(launch.LaunchSandbox))
def test_plugin_preparation_uses_the_actual_home_before_authentication(
    tmp_path: Path,
    boundary: Mock,
    sandbox: launch.LaunchSandbox,
) -> None:
    calls = Mock()
    launch.session_argv(
        "codex",
        [],
        boundary,
        Mock(hooks=None),
        tmp_path,
        CODEX_LOGIN,
        sandbox,
        {},
        prepare=calls.prepare,
        authenticate=calls.authenticate,
    )
    prefix = ["podman", "run", "image"] if sandbox.contained() else []
    home = Path("/cfg") if sandbox.contained() else tmp_path
    calls.prepare.assert_called_once_with(prefix, home)
    assert calls.mock_calls[0][0] == "prepare"
    assert calls.mock_calls[1][0] == "authenticate"


def test_failed_plugin_preparation_stops_the_launch_before_authentication(
    tmp_path: Path,
    boundary: Mock,
) -> None:
    authenticate = Mock()
    with pytest.raises(RuntimeError, match="plugin unavailable"):
        launch.session_argv(
            "codex",
            [],
            boundary,
            Mock(hooks=None),
            tmp_path,
            CODEX_LOGIN,
            launch.LaunchSandbox.OUTER,
            {},
            authenticate=authenticate,
            prepare=Mock(side_effect=RuntimeError("plugin unavailable")),
        )
    authenticate.assert_not_called()


def test_container_preparation_runs_the_owned_installer_in_the_same_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute = Mock(return_value="verified\n")
    command = Mock(return_value=execute)
    monkeypatch.setattr(sh, "Command", command)
    launch.prepare_codex_plugin(
        ["podman", "run", "image"], Path("/cfg"), tmp_path, {"FIXTURE": "yes"}, True
    )
    command.assert_called_once_with("podman")
    execute.assert_called_once_with(
        "run",
        "image",
        "uv",
        "run",
        "--locked",
        "--directory",
        str(tmp_path),
        "lup-codex-plugin",
        "--root",
        str(tmp_path),
        "--home",
        "/cfg",
        "--trust-project",
        "--force",
        _env={"FIXTURE": "yes"},
    )


def test_owned_home_preparation_verifies_discovery_and_hook_trust(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = Mock(name="marketplace")
    declared.name = "fixture"
    declared.plugin = "lup"
    declared.source = tmp_path / "plugin"
    monkeypatch.setattr(CodexMarketplace, "declared", Mock(return_value=declared))
    installer = Mock()
    monkeypatch.setattr(
        installation, "CodexPluginInstaller", Mock(return_value=installer)
    )
    trust = Mock()
    hooks = Mock()
    monkeypatch.setattr(installation, "trust_project", trust)
    monkeypatch.setattr(installation, "install_declared_policy", hooks)
    home = tmp_path / "contained-home"
    installation.install_codex_plugin(tmp_path, home, trusted=True)
    trust.assert_called_once_with(home, tmp_path)
    installer.verify.assert_called_once_with(installer.ensure.return_value, tmp_path)
    hooks.assert_called_once_with(home, tmp_path, seed=True)


def test_matching_cache_is_not_proof_of_native_plugin_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = CodexPluginInstaller(
        PluginCacheConfig(codex_home=tmp_path, marketplace="fixture")
    )
    evidence = PluginCacheEvidence(
        source_root=tmp_path,
        installed_root=tmp_path / "version",
        source_digest="same",
        installed_digest="same",
        ready=True,
    )
    monkeypatch.setattr(
        sh,
        "Command",
        Mock(return_value=Mock(return_value='{"installed":[],"available":[]}')),
    )
    with pytest.raises(RuntimeError, match="does not discover"):
        installer.verify(evidence, tmp_path)


def test_portable_requests_keep_the_executables_execution_boundary(
    tmp_path: Path,
) -> None:
    config = codex_config(
        SessionRequest(
            cwd=tmp_path, containment="outer", contained_program=tmp_path / "enter"
        )
    )
    assert config.containment == "outer"


@pytest.mark.parametrize("containment", ["outer", "none", "inner"])
async def test_custom_host_executables_still_need_host_policy_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    containment: str,
) -> None:
    policy = Mock()
    monkeypatch.setattr(runtime, "install_declared_policy", policy)
    server = Mock()
    server.start = AsyncMock(side_effect=RuntimeError("stop before any session"))
    monkeypatch.setattr(runtime, "CodexAppServer", Mock(return_value=server))
    config = runtime.CodexSessionConfig.model_validate(
        {
            "cwd": tmp_path,
            "executable": tmp_path / "custom-codex",
            "containment": containment,
            "environment": {"CODEX_HOME": str(tmp_path / "host-home")},
        }
    )
    with pytest.raises(RuntimeError, match="stop before any session"):
        async with runtime.CodexSessionOpener(config).open_session():
            pytest.fail("no native session should open")
    assert policy.call_count == (0 if containment == "outer" else 1)
    if containment != "outer":
        assert policy.call_args.args == (tmp_path / "host-home", tmp_path)


def test_outer_boundary_requires_a_container_executable(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="prepared container executable"):
        runtime.CodexSessionConfig(cwd=tmp_path, containment="outer")
