"""The launcher asks the credential owner rather than trusting local timestamps."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
import sh
import typer

import lup.devtools.harness.launch as launch
from lup.harness.clipboard import ClipboardBridge, ClipboardTransport
from lup.providers.codex.account import CodexAccountState
from lup.providers.codex.app_server import AppServerError, RpcError
from lup.providers.codex.login import CODEX_LOGIN


def account(present: bool, required: bool = True) -> CodexAccountState:
    return CodexAccountState.model_validate(
        {
            "account": {"type": "chatgpt"} if present else None,
            "requiresOpenaiAuth": required,
        }
    )


@pytest.mark.parametrize("state", [account(True), account(False, required=False)])
def test_native_account_readiness_does_not_need_a_local_auth_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: CodexAccountState
) -> None:
    read = AsyncMock(return_value=state)
    confirm = Mock(side_effect=AssertionError("ready accounts need no sign-in"))
    monkeypatch.setattr(launch, "read_account", read, raising=False)
    monkeypatch.setattr(typer, "confirm", confirm)

    launch.codex_login_preflight(tmp_path, {"PATH": "/fixture/bin"})

    read.assert_awaited_once_with(
        Path("codex"),
        {"PATH": "/fixture/bin", "CODEX_HOME": str(tmp_path)},
        refresh_token=True,
        arguments=[],
    )


def test_login_is_followed_by_native_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read = AsyncMock(side_effect=[account(False), account(True)])
    login = Mock()
    monkeypatch.setattr(launch, "read_account", read, raising=False)
    monkeypatch.setattr(typer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(sh, "Command", lambda _name: login)

    launch.codex_login_preflight(tmp_path, {})

    assert read.await_count == 2
    login.assert_called_once_with("login", _fg=True, _env={"CODEX_HOME": str(tmp_path)})


def test_failed_native_verification_after_login_does_not_open_a_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        launch, "read_account", AsyncMock(return_value=account(False)), raising=False
    )
    monkeypatch.setattr(typer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(sh, "Command", lambda _name: Mock())

    with pytest.raises(typer.BadParameter, match="authentication"):
        launch.codex_login_preflight(tmp_path, {})


@pytest.mark.parametrize(
    "failure",
    [
        AppServerError(RpcError(code=-32603, message="secret-token-value")),
        TimeoutError("secret-token-value"),
        RuntimeError("secret-token-value"),
    ],
)
def test_failed_account_check_is_not_reported_as_ready_or_leaked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
) -> None:
    monkeypatch.setattr(
        launch, "read_account", AsyncMock(side_effect=failure), raising=False
    )
    monkeypatch.setattr(typer, "confirm", lambda *args, **kwargs: False)

    launch.codex_login_preflight(tmp_path, {})

    output = capsys.readouterr().out
    assert "not verified" in output
    assert str(tmp_path) in output
    assert "secret-token-value" not in output


def test_contained_authentication_uses_the_container_and_device_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = AsyncMock(side_effect=[account(False), account(True)])
    login = Mock()
    command = Mock(return_value=login)
    monkeypatch.setattr(launch, "read_account", read)
    monkeypatch.setattr(typer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(sh, "Command", command)

    launch.codex_login_preflight(
        Path("/cfg"), {}, ["podman", "run", "-i", "image", "codex"], headless=True
    )

    read.assert_awaited_with(
        Path("podman"),
        {"CODEX_HOME": "/cfg"},
        refresh_token=True,
        arguments=["run", "-i", "image", "codex"],
    )
    command.assert_called_once_with("podman")
    login.assert_called_once_with(
        "run",
        "-i",
        "image",
        "codex",
        "login",
        "--device-auth",
        _fg=True,
        _env={"CODEX_HOME": "/cfg"},
    )


def test_named_profile_is_not_verified_against_an_unselected_base_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    read = AsyncMock(
        side_effect=AssertionError("app-server cannot select this profile")
    )
    monkeypatch.setattr(launch, "read_account", read)

    launch.codex_login_preflight(tmp_path, {}, profile="offline")

    read.assert_not_awaited()
    assert "not verified" in capsys.readouterr().out


@pytest.mark.parametrize("sandbox", list(launch.LaunchSandbox))
@pytest.mark.parametrize("transport", ["commands", "x11"])
def test_session_authentication_uses_the_same_execution_boundary(
    sandbox: launch.LaunchSandbox,
    transport: ClipboardTransport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composition = Mock()
    composition.recipe.source.image.config_home = "/cfg"
    composition.recipe.source.image.forge.sourced.return_value = ""
    composition.recipe.source.image.clipboard = ClipboardBridge()
    composition.clipboard_transport = transport
    plugin = Mock(hooks=None)
    authenticate = Mock()
    monkeypatch.setattr(launch, "accessible_roots", lambda *args: [])
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "settle_boundary", Mock())
    monkeypatch.setattr(launch, "say_opening", Mock())
    monkeypatch.setattr(launch, "verify_inside", Mock(return_value=[]))
    monkeypatch.setattr(
        launch, "contained_argv", Mock(return_value=["podman", "run", "-it", "image"])
    )

    argv = launch.session_argv(
        "codex",
        ["resume", "session"],
        composition,
        plugin,
        tmp_path,
        CODEX_LOGIN,
        sandbox,
        {},
        authenticate=authenticate,
    )

    if sandbox.contained():
        authenticate.assert_called_once_with(
            ["podman", "run", "-i", "image", "codex"], Path("/cfg")
        )
        assert argv == [
            "podman",
            "run",
            "-it",
            "image",
            *ClipboardBridge().wrap(["codex", "resume", "session"], transport),
        ]
    else:
        authenticate.assert_called_once_with(["codex"], tmp_path)
        assert argv == ["codex", "resume", "session"]
