"""Both native launchers compose an optional host review service without authority leakage."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sh
import typer

import lup.devtools.harness.launch as launch
from lup.harness.environment import launcher_decided_names, tool_server_env
from lup.harness.review_environment import REVIEW_INBOX_URL_ENV
from lup.providers.codex.profile import CodexProfileSettings


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

    @contextmanager
    def lease(root: Path) -> Iterator[SimpleNamespace]:
        calls.append(root)
        events.append("inbox")
        try:
            yield SimpleNamespace(
                endpoint="http://127.0.0.1:19876",
                started=True,
                browser_opened=browser_opened,
            )
        finally:
            events.append("release")

    def container(*_args: object, **kwargs: object) -> list[str]:
        inherited = kwargs["inherited_environment"]
        assert isinstance(inherited, list)
        forwarded.extend(inherited)
        return ["container"]

    monkeypatch.setattr(service, "review_inbox_session", lease)
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

    with ExitStack() as services:
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
            services=services,
        )
        assert "release" not in events

    assert events == [
        "prepare",
        "authenticate",
        "boundary",
        *(["inbox"] if enabled else []),
        "ready",
        *(["release"] if enabled else []),
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

    monkeypatch.setattr(service, "review_inbox_session", unavailable)
    with (
        ExitStack() as services,
        pytest.raises(RuntimeError, match="could not become ready"),
    ):
        launch.session_argv(
            runtime,
            [],
            composition,
            Mock(),
            tmp_path,
            Mock(),
            launch.LaunchSandbox.NONE,
            {},
            services=services,
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


@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_enabled_inbox_requires_a_caller_owned_session_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime: str
) -> None:
    import lup.devtools.dev.review_service as service

    composition = Mock()
    composition.recipe.source.review_inbox = True
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "accessible_roots", lambda _told: [])
    monkeypatch.setattr(launch, "settle_boundary", Mock())
    acquire = Mock(side_effect=AssertionError("No unowned service may start"))
    monkeypatch.setattr(service, "review_inbox_session", acquire)

    with pytest.raises(ValueError, match="native session service scope"):
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
    acquire.assert_not_called()


@pytest.mark.parametrize("runtime", ["claude", "codex"])
@pytest.mark.parametrize("sandbox", list(launch.LaunchSandbox))
@pytest.mark.parametrize(
    "outcome", ["normal", "interrupt", "missing", "failed", "startup", "readiness"]
)
def test_native_launcher_releases_its_inbox_lease_on_every_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
    sandbox: launch.LaunchSandbox,
    outcome: str,
) -> None:
    import lup.devtools.dev.review_service as service

    events: list[str] = []
    plugin = Mock()
    plugin.name = "lup"
    composition = Mock()
    composition.recipe.root = tmp_path
    composition.recipe.source.plugins = [plugin]
    composition.recipe.source.review_inbox = True
    composition.recipe.source.image.forge.sourced.return_value = ""
    composition.recipe.source.image.config_home = "/cfg"
    composition.recipe.source.image.inboxes.serve.return_value = None
    composition.recipe.source.image.clipboard.wrap.side_effect = lambda argv, _mode: (
        argv
    )
    profiles = Mock()
    profiles.launch_home.return_value = tmp_path
    profiles.login.credentials_path.return_value = tmp_path / "absent-credentials"
    profiles.login.environment.return_value = {}
    transcript = Mock()
    transcript.journal.path = tmp_path / "transcript"

    @contextmanager
    def lease(root: Path) -> Iterator[SimpleNamespace]:
        assert root == tmp_path
        events.append("acquire")
        try:
            if outcome == "startup":
                raise RuntimeError("Review inbox startup failed")
            yield SimpleNamespace(
                endpoint="http://127.0.0.1:19876", started=True, browser_opened=True
            )
        finally:
            events.append("release")

    def ready(*_args: object, **_kwargs: object) -> None:
        assert events[-1] == "acquire"
        if outcome == "readiness":
            raise RuntimeError("Launch readiness failed")
        events.append("ready")

    def native(*_args: object, **kwargs: object) -> None:
        assert kwargs["_fg"] is True
        assert events[-1] == "command"
        events.append("native")
        match outcome:
            case "interrupt":
                raise KeyboardInterrupt
            case "failed":
                raise sh.ErrorReturnCode_7("fixture native", b"", b"")

    def command(_name: str) -> object:
        assert events[-1] == "ready"
        events.append("command")
        if outcome == "missing":
            raise sh.CommandNotFound(runtime)
        return native

    monkeypatch.setattr(service, "review_inbox_session", lease)
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "announce_relaxed_rules", Mock())
    member = Mock(cli_name="fixture")
    member.environment.return_value = {}
    monkeypatch.setattr(launch, "launched_member", Mock(return_value=member))
    monkeypatch.setattr(
        launch, "ready_to_open", Mock(return_value=launch.LaunchOpening())
    )
    monkeypatch.setattr(launch, "companion_plugin_directories", Mock(return_value=[]))
    monkeypatch.setattr(launch, "claude_sandbox_arguments", Mock(return_value=[]))
    monkeypatch.setattr(launch, "codex_sandbox_arguments", Mock(return_value=[]))
    monkeypatch.setattr(launch, "non_interactive_environment", Mock(return_value={}))
    monkeypatch.setattr(launch, "apply_sandbox_environment", Mock())
    monkeypatch.setattr(
        launch, "start_harness_transcript", Mock(return_value=transcript)
    )
    monkeypatch.setattr(launch, "accessible_roots", Mock(return_value=[]))
    monkeypatch.setattr(launch, "granted_devices", Mock(return_value=[]))
    monkeypatch.setattr(launch, "editor_rendezvous", Mock(return_value=None))
    monkeypatch.setattr(launch, "contained_argv", Mock(return_value=["container"]))
    monkeypatch.setattr(launch, "verify_inside", Mock(return_value=[]))
    monkeypatch.setattr(launch, "settle_boundary", Mock())
    monkeypatch.setattr(launch, "say_opening", ready)
    monkeypatch.setattr(
        launch, "release_ledger", lambda *_args: events.append("ledger")
    )
    monkeypatch.setattr(
        launch,
        "select_codex_home",
        Mock(return_value=Mock(path=tmp_path, isolated=False)),
    )
    monkeypatch.setattr(CodexProfileSettings, "capture", Mock(return_value=None))
    monkeypatch.setattr(launch, "prepare_codex_plugin", Mock())
    monkeypatch.setattr(launch, "codex_login_preflight", Mock())
    monkeypatch.setattr(sh, "Command", command)

    def run() -> None:
        if runtime == "claude":
            launch.launch_claude(
                composition, [], profiles, None, None, False, sandbox=sandbox
            )
        else:
            launch.launch_codex(
                composition, [], tmp_path, None, None, False, False, sandbox=sandbox
            )

    match outcome:
        case "normal":
            run()
        case "interrupt":
            with pytest.raises(KeyboardInterrupt):
                run()
        case "missing":
            with pytest.raises(typer.BadParameter, match="was not found"):
                run()
        case "failed":
            with pytest.raises(typer.Exit) as failed:
                run()
            assert failed.value.exit_code == 7
        case "startup" | "readiness":
            with pytest.raises(RuntimeError, match="failed"):
                run()

    assert events == [
        "acquire",
        *(["ready", "command"] if outcome not in {"startup", "readiness"} else []),
        *(["native"] if outcome in {"normal", "interrupt", "failed"} else []),
        "release",
        "ledger",
    ]
    transcript.close.assert_called_once_with(
        succeeded=outcome == "normal", interrupted=outcome == "interrupt"
    )
