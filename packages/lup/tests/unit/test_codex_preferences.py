"""Codex's half of the person's settings: laid over each home, and sorted on the way back.

A Codex home is given the account's configuration with the lup config's
editor and ``[codex.settings]`` winning, and what a session changes comes
back only where it is a preference. These pin both directions, the editor's
spelling in each vocabulary, a key nobody decided about staying where it was
written, and a contained session's configuration read back from its volume.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
import tomlkit

import lup.devtools.harness.launch as launch
from lup.devtools.harness.config_volume import HomeFile
from lup.harness.image import Image
from lup.providers.codex.home import CodexWorktreeHomeStore, personalized_codex_config
from lup.providers.codex.preferences import (
    CodexSettingsReturn,
    SettingChange,
    codex_setting_flow,
)
from lup.providers.user_config import UserConfig, UserConfigFile

ACCOUNT = (
    '[tui]\ntheme = "zenburn"\nanimations = true\n\n[mcp_servers.x]\ncommand = "x"\n'
)


def test_the_editor_and_the_persons_table_are_laid_over_the_account() -> None:
    laid = tomlkit.parse(
        personalized_codex_config(
            ACCOUNT, {"tui": {"animations": False}, "file_opener": "none"}, "vim"
        )
    ).unwrap()

    assert laid["tui"] == {
        "theme": "zenburn",
        "animations": False,
        "vim_mode_default": True,
    }
    assert laid["file_opener"] == "none"
    assert laid["mcp_servers"] == {"x": {"command": "x"}}
    assert personalized_codex_config(ACCOUNT, {}, None) == ACCOUNT


@pytest.mark.parametrize(
    ("path", "flow"),
    [
        (("tui", "theme"), "returns"),
        (("tui", "keymap", "global", "toggle_vim_mode"), "returns"),
        (("model",), "session"),
        (("model_reasoning_effort",), "session"),
        (("notify",), "withheld"),
        (("mcp_servers", "x", "command"), "withheld"),
        (("tui", "screen_reader_detection_done"), "withheld"),
        (("a_key_codex_adds_next_month",), "withheld"),
    ],
)
def test_each_codex_setting_has_a_flow(path: tuple[str, ...], flow: str) -> None:
    assert codex_setting_flow(path) == flow


def test_portable_settings_return_in_the_lup_configs_words() -> None:
    personal = UserConfig.model_validate(
        {"codex": {"settings": {"tui": {"pet": "cat"}}}}
    )

    returned = CodexSettingsReturn.sorted_out(
        [
            SettingChange(path=("tui", "theme"), value="dracula"),
            SettingChange(path=("tui", "vim_mode_default"), value=False),
            SettingChange(path=("tui", "pet"), value="dog"),
            SettingChange(path=("tui", "animations"), value=False),
            SettingChange(path=("model",), value="gpt-chosen"),
            SettingChange(path=("notify",), value=["curl", "x"]),
        ],
        personal,
    )

    assert returned.portable == {
        ("theme", "codex"): "dracula",
        ("editor",): "normal",
        ("codex", "settings", "tui", "pet"): "dog",
    }
    assert [change.name() for change in returned.account] == ["tui.animations"]
    assert returned.session == ["model"]
    assert returned.withheld == ["notify"]


def test_a_contained_sessions_theme_is_read_from_its_volume_and_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account = tmp_path / "account"
    account.mkdir()
    (account / "config.toml").write_text(ACCOUNT, encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    store = CodexWorktreeHomeStore(account)
    scoped = store.prepare(worktree)
    volume = tomlkit.parse((scoped / "config.toml").read_text(encoding="utf-8"))
    volume["tui"]["theme"] = "dracula"
    volume["hooks"] = {"Stop": [{"command": "curl x"}]}
    monkeypatch.setattr(launch, "project_root", lambda: worktree)
    monkeypatch.setattr(
        launch,
        "read_config_home",
        lambda image, root, login, names: [
            HomeFile(name="config.toml", content=tomlkit.dumps(volume).encode())
        ],
    )
    person = UserConfigFile(tmp_path / "lup")

    launch.carry_codex_home(store, Image(), person)

    said = capsys.readouterr().out
    assert "theme.codex" in said and "hooks (never leaves its home)" in said
    assert person.load().theme.codex == "dracula"
    assert "hooks" not in tomlkit.parse((account / "config.toml").read_text())


def test_a_contained_volume_that_cannot_be_read_moves_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = Mock()
    monkeypatch.setattr(launch, "read_config_home", lambda *a, **k: [])

    launch.carry_codex_home(store, Image(), UserConfigFile(tmp_path / "lup"))

    assert "nothing it changed was returned" in capsys.readouterr().out
    store.return_settings.assert_not_called()
