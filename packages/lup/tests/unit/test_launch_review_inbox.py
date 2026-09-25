"""Both native launchers compose an optional host review service without authority leakage."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import lup.devtools.harness.launch as launch
from lup.harness.environment import launcher_decided_names, tool_server_env
from lup.harness.review_environment import REVIEW_INBOX_URL_ENV


@pytest.mark.parametrize("runtime", ["claude", "codex"])
@pytest.mark.parametrize("sandbox", list(launch.LaunchSandbox))
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("browser_opened", [False, True])
def test_service_selection_is_independent_of_runtime_and_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
    sandbox: launch.LaunchSandbox,
    enabled: bool,
    browser_opened: bool,
) -> None:
    import lup.devtools.dev.review_service as service

    events: list[str] = []
    forwarded: list[str] = []
    calls: list[Path] = []
    composition = Mock()
    composition.recipe.root = tmp_path
    composition.recipe.source.review_inbox = enabled
    composition.recipe.source.image.forge.sourced.return_value = ""
    composition.recipe.source.image.config_home = "/cfg"
    composition.recipe.source.image.clipboard.wrap.side_effect = lambda argv, _mode: (
        argv
    )
    login = Mock()
    cleared = Mock(findings=[])
    login.credentials_path.return_value = tmp_path / "absent-credentials"

    def ensure(root: Path) -> SimpleNamespace:
        calls.append(root)
        events.append("inbox")
        return SimpleNamespace(
            endpoint="http://127.0.0.1:19876",
            started=True,
            browser_opened=browser_opened,
        )

    def container(*_args: object, **kwargs: object) -> list[str]:
        inherited = kwargs["inherited_environment"]
        assert isinstance(inherited, list)
        forwarded.extend(inherited)
        return ["container"]

    monkeypatch.setattr(service, "ensure_review_inbox", ensure)
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "accessible_roots", lambda _told: [])
    monkeypatch.setattr(launch, "granted_devices", lambda _told: [])
    monkeypatch.setattr(launch, "editor_rendezvous", lambda _login: None)
    monkeypatch.setattr(launch, "contained_argv", container)
    monkeypatch.setattr(launch, "probing", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(launch, "verify_inside", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        launch, "settle_boundary", lambda *_args, **_kwargs: events.append("boundary")
    )
    monkeypatch.setattr(
        launch, "say_opening", lambda *_args, **_kwargs: events.append("ready")
    )
    environment = {REVIEW_INBOX_URL_ENV: "http://127.0.0.1:11111"}

    argv = launch.session_argv(
        runtime,
        ["--model", "chosen"],
        composition,
        Mock(),
        tmp_path,
        login,
        sandbox,
        environment,
        prepare=lambda *_args: events.append("prepare"),
        authenticate=lambda *_args: events.append("authenticate"),
        cleared=cleared,
    )

    assert events == [
        "prepare",
        "authenticate",
        "boundary",
        *(["inbox"] if enabled else []),
        "ready",
    ]
    assert calls == ([tmp_path] if enabled else [])
    assert argv == [
        *(["container"] if sandbox.contained() else []),
        runtime,
        "--model",
        "chosen",
    ]
    if enabled:
        assert environment[REVIEW_INBOX_URL_ENV] == "http://127.0.0.1:19876"
    else:
        assert REVIEW_INBOX_URL_ENV not in environment
    assert (REVIEW_INBOX_URL_ENV in forwarded) is (enabled and sandbox.contained())
    assert all("token" not in value.lower() for value in [*argv, *environment.values()])
    notices = [
        notice.text
        for call in cleared.banner.add.call_args_list
        for notice in call.args[0]
    ]
    assert any("lup-devtools dev questions open" in text for text in notices) is (
        enabled and not browser_opened
    )


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_failed_service_does_not_announce_launch_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str
) -> None:
    import lup.devtools.dev.review_service as service

    composition = Mock()
    composition.recipe.root = tmp_path
    composition.recipe.source.review_inbox = True
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "accessible_roots", lambda _told: [])
    monkeypatch.setattr(launch, "settle_boundary", lambda *_args, **_kwargs: None)
    announced = Mock()
    monkeypatch.setattr(launch, "say_opening", announced)

    def unavailable(_root: Path) -> None:
        raise RuntimeError("Review inbox could not become ready")

    monkeypatch.setattr(service, "ensure_review_inbox", unavailable)
    with pytest.raises(RuntimeError, match="could not become ready"):
        launch.session_argv(
            runtime,
            [],
            composition,
            Mock(),
            tmp_path,
            Mock(),
            launch.LaunchSandbox.NONE,
            {},
        )
    announced.assert_not_called()


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_generate_only_does_not_enter_session_startup(
    monkeypatch: pytest.MonkeyPatch, runtime: str
) -> None:
    composition = Mock()
    composition.recipe.source.plugins = [Mock()]
    composition.recipe.source.review_inbox = True
    monkeypatch.setattr(launch, "announce_relaxed_rules", lambda *_args: None)
    prepared = Mock(return_value=None)
    monkeypatch.setattr(launch, "ready_to_open", prepared)
    opening = Mock(side_effect=AssertionError("generation must not open a session"))
    monkeypatch.setattr(launch, "session_argv", opening)

    if runtime == "claude":
        launch.launch_claude(composition, [], Mock(), None, None, True)
    else:
        launch.launch_codex(composition, [], None, None, None, True, False)

    assert prepared.call_args.args[1] is True
    opening.assert_not_called()


def test_safe_endpoint_reaches_native_tool_servers_and_is_cleared_for_tests() -> None:
    assert REVIEW_INBOX_URL_ENV in tool_server_env()
    assert REVIEW_INBOX_URL_ENV in launcher_decided_names({})
