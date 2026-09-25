"""A contained profile keeps its selected settings and leaves local trust local."""

import asyncio
from pathlib import Path
import shutil
import stat
from unittest.mock import AsyncMock, Mock

import pytest
import sh
import tomlkit
from typer.testing import CliRunner

import lup.devtools.harness.launch as launch
import lup.devtools.harness.contained as contained
import lup.providers.codex.install as installation
from lup.harness.image import Image
from lup.providers.codex.account import read_account
from lup.providers.codex.home import CodexHomeSelection
from lup.providers.codex.profile import CodexProfileSettings
from lup.providers.codex.runtime import CodexSessionConfig, CodexSessionOpener
from lup.sessions.errors import UnsupportedCapability


def source_home(root: Path) -> Path:
    home = root / "source"
    home.mkdir()
    (home / "config.toml").write_text(
        'model="gpt-5.5"\nmodel_reasoning_effort="medium"\n'
        'model_instructions_file="instructions.md"\n'
        '[model_providers.fixture]\nname="Fixture"\nbase_url="http://localhost:9999/v1"\n'
        '[plugins."private@account"]\nenabled=true\n'
        '[projects."/private/project"]\ntrust_level="trusted"\n'
        '[hooks.state.private]\ntrusted_hash="private-hash"\n',
        encoding="utf-8",
    )
    (home / "review.config.toml").write_text(
        'model="gpt-6-astra"\nmodel_reasoning_effort="high"\n'
        '[model_providers.fixture]\nname="Review fixture"\n',
        encoding="utf-8",
    )
    (home / "instructions.md").write_text("A fixture instruction.", encoding="utf-8")
    return home


def test_selected_settings_merge_without_transporting_home_state(
    tmp_path: Path,
) -> None:
    settings = CodexProfileSettings.capture(source_home(tmp_path), "review")
    assert settings.settings["model"] == "gpt-6-astra"
    assert settings.settings["model_providers"] == {
        "fixture": {"name": "Review fixture", "base_url": "http://localhost:9999/v1"}
    }
    assert "plugins" not in settings.settings
    assert "projects" not in settings.settings
    assert "private-hash" not in settings.model_dump_json()


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is not installed")
def test_native_settings_preserve_source_paths_and_destination_state(
    tmp_path: Path,
) -> None:
    source = source_home(tmp_path)
    settings = CodexProfileSettings.capture(source, "review")
    destination = tmp_path / "destination"
    destination.mkdir()
    trust = '[plugins."lup@fixture"]\nenabled=true\n[hooks.state.owned]\ntrusted_hash="owned"\n'
    (destination / "config.toml").write_text(trust, encoding="utf-8")

    settings.install(destination)

    installed = tomlkit.parse(
        (destination / f"{settings.installed_name()}.config.toml").read_text(
            encoding="utf-8"
        )
    )
    assert installed["model"] == "gpt-6-astra"
    assert installed["model_instructions_file"] == str(source / "instructions.md")
    assert (destination / "config.toml").read_text(encoding="utf-8") == trust
    assert not (destination / "auth.json").exists()
    assert (
        stat.S_IMODE(
            (destination / f"{settings.installed_name()}.config.toml").stat().st_mode
        )
        == 0o600
    )


def test_changed_profile_gets_another_immutable_name(tmp_path: Path) -> None:
    source = source_home(tmp_path)
    first = CodexProfileSettings.capture(source, "review")
    (source / "review.config.toml").write_text('model="gpt-5.5"\n', encoding="utf-8")
    second = CodexProfileSettings.capture(source, "review")
    assert first.installed_name() != second.installed_name()


def test_same_effective_settings_reuse_native_state_and_changes_partition_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = CodexProfileSettings(
        name=None,
        source_home=tmp_path,
        as_base=True,
        settings={"model": "gpt-5.5", "model_reasoning_effort": "high"},
    )
    reordered = settings.model_copy(
        update={
            "settings": {
                "model_reasoning_effort": "high",
                "model": "gpt-5.5",
            }
        }
    )
    changed = settings.model_copy(update={"settings": {"model": "gpt-6-astra"}})
    layout = Mock()
    layout.name.return_value = "fixture"
    monkeypatch.setattr(contained, "repository_layout", Mock(return_value=layout))
    volume = contained.state_volume_name(tmp_path, settings.state_scope())
    assert volume == contained.state_volume_name(tmp_path, reordered.state_scope())
    assert volume != contained.state_volume_name(tmp_path, changed.state_scope())
    assert contained.state_volume_name(tmp_path) == "lup-cfg-fixture"


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is not installed")
def test_selected_profile_cannot_disable_owned_policy(tmp_path: Path) -> None:
    source = source_home(tmp_path)
    (source / "review.config.toml").write_text(
        "[features]\nhooks=false\nmulti_agent=false\n"
        '[plugins."lup@fixture"]\nenabled=false\n'
        '[projects."/private/project"]\ntrust_level="untrusted"\n'
        '[hooks.state.owned]\nenabled=false\ntrusted_hash="untrusted"\n',
        encoding="utf-8",
    )
    settings = CodexProfileSettings.capture(source, "review")
    destination = tmp_path / "destination"
    destination.mkdir()
    trusted = '[plugins."lup@fixture"]\nenabled=true\n[hooks.state.owned]\ntrusted_hash="owned"\n'
    (destination / "config.toml").write_text(trusted, encoding="utf-8")

    settings.install(destination, enforce_policy=True)

    installed = tomlkit.parse(
        (destination / f"{settings.installed_name()}.config.toml").read_text(
            encoding="utf-8"
        )
    )
    assert installed["features"] == {"hooks": True, "multi_agent": False}
    assert "plugins" not in installed
    assert "projects" not in installed
    assert installed["hooks"] == {}
    assert (destination / "config.toml").read_text(encoding="utf-8") == trusted


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is not installed")
def test_unavailable_profile_dependency_refuses_before_install(tmp_path: Path) -> None:
    source = source_home(tmp_path)
    (source / "instructions.md").unlink()
    settings = CodexProfileSettings.capture(source, "review")
    destination = tmp_path / "destination"
    with pytest.raises(ValueError, match="absolute, accessible paths"):
        settings.install(destination)
    assert not (destination / f"{settings.installed_name()}.config.toml").exists()


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is not installed")
def test_native_paths_keep_the_source_users_home(tmp_path: Path) -> None:
    original_home = tmp_path / "operator"
    original_home.mkdir()
    (original_home / "instructions.md").write_text("A fixture instruction.")
    snapshot = CodexProfileSettings(
        name=None,
        source_home=tmp_path / "config",
        source_user_home=original_home,
        settings={"model_instructions_file": "~/instructions.md"},
        as_base=True,
    )
    destination = tmp_path / "contained"
    snapshot.install(destination)
    installed = tomlkit.parse((destination / "config.toml").read_text())
    assert installed["model_instructions_file"] == str(
        original_home / "instructions.md"
    )


def test_stdin_payload_is_sanitized_even_without_capture(tmp_path: Path) -> None:
    settings = CodexProfileSettings(
        name="review",
        source_home=tmp_path,
        settings={
            "plugins": {"lup@fixture": {"enabled": False}},
            "hooks": {"state": {"owned": {"enabled": False}}},
            "features": {"hooks": False, "multi_agent": False},
        },
    )
    assert settings.personal_settings(enforce_policy=True) == {
        "hooks": {},
        "features": {"hooks": True, "multi_agent": False},
    }


@pytest.mark.skipif(shutil.which("codex") is None, reason="Codex CLI is not installed")
@pytest.mark.parametrize("profile", [None, "review"])
def test_contained_base_is_the_native_account_configuration(
    tmp_path: Path, profile: str | None
) -> None:
    source = source_home(tmp_path)
    base = source / "config.toml"
    base.write_text('model_provider="fixture"\n' + base.read_text(encoding="utf-8"))
    snapshot = CodexProfileSettings.capture(source, profile, as_base=True)
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "config.toml").write_text(
        '[plugins."lup@fixture"]\nenabled=true\n'
        '[hooks.state.owned]\ntrusted_hash="owned"\n',
        encoding="utf-8",
    )

    snapshot.install(destination, enforce_policy=True)
    settings = tomlkit.parse((destination / "config.toml").read_text(encoding="utf-8"))
    assert settings["model"] == ("gpt-6-astra" if profile else "gpt-5.5")
    assert settings["model_provider"] == "fixture"
    assert settings["plugins"] == {"lup@fixture": {"enabled": True}}
    assert settings["hooks"] == {"state": {"owned": {"trusted_hash": "owned"}}}
    inode = (destination / "config.toml").stat().st_ino
    snapshot.install(destination, enforce_policy=True)
    assert (destination / "config.toml").stat().st_ino == inode
    state = asyncio.run(read_account(Path("codex"), {"CODEX_HOME": str(destination)}))
    assert state.ready
    assert state.account is None


@pytest.mark.parametrize("profile", [None, "review"])
@pytest.mark.parametrize("sandbox", list(launch.LaunchSandbox))
def test_launcher_selects_the_same_settings_for_preparation_auth_and_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str | None,
    sandbox: launch.LaunchSandbox,
) -> None:
    source = source_home(tmp_path)
    composition = Mock()
    composition.recipe.source.plugins = [Mock(hooks=None)]
    composition.recipe.source.image = Image()
    composition.recipe.source.companions = []
    monkeypatch.setattr(
        launch, "ready_to_open", Mock(return_value=launch.LaunchOpening())
    )
    monkeypatch.setattr(launch, "project_root", lambda: tmp_path)
    monkeypatch.setattr(launch, "non_interactive_environment", lambda environment: {})
    monkeypatch.setattr(launch, "codex_sandbox_arguments", Mock(return_value=[]))
    monkeypatch.setattr(
        launch,
        "select_codex_home",
        Mock(return_value=CodexHomeSelection(path=source, isolated=False)),
    )
    monkeypatch.setattr(launch, "start_harness_transcript", Mock())
    monkeypatch.setattr(sh, "Command", Mock())
    opening = Mock(return_value=["codex"])
    monkeypatch.setattr(launch, "session_argv", opening)
    prepare = Mock()
    authenticate = Mock()
    monkeypatch.setattr(launch, "prepare_codex_plugin", prepare)
    monkeypatch.setattr(launch, "codex_login_preflight", authenticate)

    launch.launch_codex(
        composition, [], source, profile, None, False, False, sandbox=sandbox
    )

    call = opening.call_args
    native_home = Path("/cfg") if sandbox.contained() else source
    call.kwargs["prepare"]([], native_home)
    call.kwargs["authenticate"](["codex"], native_home, False)
    snapshot = prepare.call_args.kwargs["settings"]
    if sandbox.contained():
        assert snapshot.as_base
        assert snapshot.settings["model"] == ("gpt-6-astra" if profile else "gpt-5.5")
        assert call.kwargs["state_scope"] == snapshot.state_scope()
        assert "--profile" not in call.args[1]
        assert authenticate.call_args.kwargs["profile"] is None
    else:
        assert call.kwargs["state_scope"] is None
        assert authenticate.call_args.kwargs["profile"] == profile
        if profile:
            assert call.args[1] == ["--profile", snapshot.installed_name()]
        else:
            assert snapshot is None


def test_missing_or_malformed_profile_does_not_expose_setting_values(
    tmp_path: Path,
) -> None:
    source = source_home(tmp_path)
    (source / "review.config.toml").write_text('secret="DO-NOT-LOG', encoding="utf-8")
    with pytest.raises(ValueError) as error:
        CodexProfileSettings.capture(source, "review")
    assert "DO-NOT-LOG" not in str(error.value)


def test_invalid_owned_settings_do_not_expose_validation_values(tmp_path: Path) -> None:
    source = source_home(tmp_path)
    (source / "review.config.toml").write_text('hooks="DO-NOT-LOG"\n')
    with pytest.raises(ValueError) as error:
        CodexProfileSettings.capture(source, "review")
    assert "DO-NOT-LOG" not in str(error.value)


def test_native_configuration_failure_does_not_expose_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = CodexProfileSettings.capture(source_home(tmp_path), "review")
    monkeypatch.setattr(
        CodexProfileSettings,
        "normalized",
        AsyncMock(side_effect=RuntimeError("DO-NOT-LOG secret from native stderr")),
    )
    with pytest.raises(ValueError) as error:
        settings.install(tmp_path / "destination")
    assert "DO-NOT-LOG" not in str(error.value)
    assert "not logged" in str(error.value)


def test_malformed_stdin_payload_does_not_expose_values(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        installation.app,
        ["--root", str(tmp_path), "--home", str(tmp_path / "home"), "--settings-stdin"],
        input='{"name":"review","source_home":"x","settings":"DO-NOT-LOG"}',
    )
    assert result.exit_code != 0
    assert "DO-NOT-LOG" not in result.output


def test_profile_payload_crosses_stdin_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = CodexProfileSettings.capture(source_home(tmp_path), "review")
    command = Mock(return_value="{}")
    monkeypatch.setattr(sh, "Command", Mock(return_value=command))
    launch.prepare_codex_plugin(
        ["podman", "run", "-i", "image"],
        tmp_path / "destination",
        tmp_path,
        {},
        settings=settings,
    )
    assert "--settings-stdin" in command.call_args.args
    assert "Review fixture" not in " ".join(command.call_args.args)
    assert (
        CodexProfileSettings.model_validate_json(command.call_args.kwargs["_in"])
        == settings
    )


def test_sdk_named_profile_is_refused_before_startup(tmp_path: Path) -> None:
    config = CodexSessionConfig(
        cwd=tmp_path, named_profile="review", environment={"SECRET": "DO-NOT-LOG"}
    )
    with pytest.raises(UnsupportedCapability) as error:
        CodexSessionOpener(config)
    assert "app-server cannot select named profiles" in str(error.value)
    assert "DO-NOT-LOG" not in str(error.value)
