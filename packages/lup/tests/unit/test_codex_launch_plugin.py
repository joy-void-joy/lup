"""Plugin readiness is measured where the session actually opens its home."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import sh

import lup.devtools.harness.launch as launch
import lup.providers.codex.install as installation
import lup.providers.codex.runtime as runtime
import lup.providers.codex.home as codex_home
import lup.providers.codex.selection as codex_selection
from lup.harness.clipboard import ClipboardBridge
from lup.policy.identity import POLICY_ROOT_ENV
from lup.providers.codex.login import CODEX_HOME, CODEX_LOGIN
from lup.providers.codex.marketplace import CodexMarketplace
from lup.providers.codex.trust import CodexHookReport
from lup.providers.codex.selection import codex_config
from lup.providers.login import NativeHomeScope
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
    prefix = ["podman", "run", "-i", "image"] if sandbox.contained() else []
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


def test_settings_scope_reaches_the_container_volume_builder(
    tmp_path: Path,
    boundary: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opening = Mock(return_value=["podman", "run", "-it", "image"])
    monkeypatch.setattr(launch, "contained_argv", opening)
    scope = NativeHomeScope(key="codex-fixture")
    launch.session_argv(
        "codex",
        [],
        boundary,
        Mock(hooks=None),
        tmp_path,
        CODEX_LOGIN,
        launch.LaunchSandbox.OUTER,
        {},
        state_scope=scope,
    )
    assert opening.call_args.kwargs["state_scope"] == scope


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
        _in=None,
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


@pytest.mark.parametrize("containment", ["none", "inner"])
@pytest.mark.parametrize(
    ("explicit", "ambient", "expected"),
    [
        ("explicit-home", "ambient-home", "explicit-home"),
        (None, "ambient-home", "ambient-home"),
        (None, None, "user-home/.codex"),
        ("", "ambient-home", "user-home/.codex"),
    ],
)
async def test_host_policy_and_process_use_the_same_resolved_native_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    containment: str,
    explicit: str | None,
    ambient: str | None,
    expected: str,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
    if ambient is None:
        monkeypatch.delenv(CODEX_HOME, raising=False)
    else:
        monkeypatch.setenv(CODEX_HOME, str(tmp_path / ambient))
    environment = (
        {CODEX_HOME: str(tmp_path / explicit) if explicit else ""}
        if explicit is not None
        else {}
    )
    calls = Mock()
    monkeypatch.setattr(runtime, "install_declared_policy", calls.policy)
    server = Mock(start=AsyncMock(), close=AsyncMock())
    calls.server.return_value = server
    monkeypatch.setattr(runtime, "CodexAppServer", calls.server)
    config = runtime.CodexSessionConfig.model_validate(
        {"cwd": tmp_path, "containment": containment, "environment": environment}
    )

    async with runtime.CodexSessionOpener(config).open_session():
        server.start.assert_awaited_once()

    home = tmp_path / expected
    calls.policy.assert_called_once_with(home, tmp_path, seed=False, workspace=tmp_path)
    assert calls.server.call_args.kwargs["environment"][CODEX_HOME] == str(home)
    assert calls.mock_calls[0][0] == "policy"
    assert calls.mock_calls[1][0] == "server"
    assert config.environment == environment
    server.close.assert_awaited_once()


async def test_host_policy_failure_stops_before_constructing_the_native_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CODEX_HOME, str(tmp_path / "codex-home"))
    policy = Mock(side_effect=RuntimeError("declared plugin unavailable"))
    native = Mock()
    monkeypatch.setattr(runtime, "install_declared_policy", policy)
    monkeypatch.setattr(runtime, "CodexAppServer", native)

    with pytest.raises(RuntimeError, match="declared plugin unavailable"):
        async with runtime.CodexSessionOpener(
            runtime.CodexSessionConfig(cwd=tmp_path)
        ).open_session():
            pytest.fail("a policy failure must prevent native startup")

    policy.assert_called_once_with(
        tmp_path / "codex-home", tmp_path, seed=False, workspace=tmp_path
    )
    native.assert_not_called()


async def test_a_project_without_declared_policy_opens_with_its_native_default_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CODEX_HOME, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
    server = Mock(start=AsyncMock(), close=AsyncMock())
    native = Mock(return_value=server)
    monkeypatch.setattr(runtime, "CodexAppServer", native)
    home = tmp_path / "user-home" / ".codex"

    async with runtime.CodexSessionOpener(
        runtime.CodexSessionConfig(cwd=tmp_path)
    ).open_session():
        server.start.assert_awaited_once()

    assert home.is_dir()
    assert list(home.iterdir()) == []
    assert native.call_args.kwargs["environment"][CODEX_HOME] == str(home)
    server.close.assert_awaited_once()


@pytest.mark.parametrize(
    "evidence", ["ready", "missing", "untrusted", "unresolved", "warning", "skill-only"]
)
@pytest.mark.parametrize("portable", [False, True])
async def test_application_policy_is_verified_in_an_external_native_workspace(
    tmp_lup_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence: str,
    portable: bool,
) -> None:
    project = tmp_lup_project
    workspace = project.parent / f"{project.name}-native"
    workspace.mkdir()
    home = project / "session-home"
    manifest = project / ".agents/plugins/marketplace.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "name": "application",
                "plugins": [{"name": "lup", "source": {"path": ".codex/plugins/lup"}}],
            }
        )
    )
    plugin_manifest = project / ".codex/plugins/lup/.codex-plugin/plugin.json"
    plugin_manifest.parent.mkdir(parents=True)
    plugin_manifest.write_text(
        json.dumps(
            {"name": "lup"}
            if evidence == "skill-only"
            else {"name": "lup", "hooks": "./hooks/hooks.json"}
        )
    )
    config = (
        codex_config(SessionRequest(cwd=workspace, environment={CODEX_HOME: str(home)}))
        if portable
        else runtime.CodexSessionConfig(
            cwd=workspace, policy_root=project, environment={CODEX_HOME: str(home)}
        )
    )
    assert config.policy_root == project
    assert config.cwd == workspace
    monkeypatch.setattr(codex_selection, "project_root", lambda: workspace)
    installer = Mock()
    monkeypatch.setattr(
        codex_home, "CodexPluginInstaller", Mock(return_value=installer)
    )
    hooks = (
        []
        if evidence in ("missing", "skill-only")
        else [
            {
                "key": "application-policy",
                "eventName": "preToolUse",
                "pluginId": "lup@application",
                "source": "plugin",
                "enabled": True,
                "isManaged": False,
                "currentHash": "digest",
                "trustStatus": "untrusted" if evidence == "untrusted" else "trusted",
            }
        ]
    )
    discovery = AsyncMock(
        return_value=CodexHookReport.model_validate(
            {
                "data": [
                    {
                        "cwd": str(workspace),
                        "hooks": hooks,
                        "warnings": ["timeout clamped"]
                        if evidence == "warning"
                        else [],
                        "errors": [{"message": "unresolved declaration"}]
                        if evidence == "unresolved"
                        else [],
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(codex_home, "read_hooks", discovery)
    server = Mock(start=AsyncMock(), close=AsyncMock())
    native = Mock(return_value=server)
    monkeypatch.setattr(runtime, "CodexAppServer", native)

    if evidence in ("ready", "warning", "skill-only"):
        async with runtime.CodexSessionOpener(config).open_session():
            server.start.assert_awaited_once()
        assert native.call_args.kwargs["environment"][CODEX_HOME] == str(home)
        assert native.call_args.kwargs["environment"][POLICY_ROOT_ENV] == str(project)
    else:
        with pytest.raises(codex_home.CodexPolicyUntrusted) as failure:
            async with runtime.CodexSessionOpener(config).open_session():
                pytest.fail("missing policy evidence must prevent native startup")
        native.assert_not_called()
        assert str(project) in str(failure.value)
        assert str(workspace) in str(failure.value)
        assert "lup@application" in str(failure.value)

    installer.ensure.assert_called_once_with(project / ".codex/plugins/lup", project)
    installer.verify.assert_called_once_with(installer.ensure.return_value, workspace)
    discovery.assert_awaited_once_with(home, workspace)
