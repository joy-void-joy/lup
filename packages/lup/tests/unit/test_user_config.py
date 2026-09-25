"""One person's lup config: where it is, what it holds, and what it refuses.

A value read from the wrong place, or silently dropped, is a new project
opening signed out in the runtime's default theme again — the reset this file
exists to end. These pin the XDG location, lup's defaults for a person who
wrote nothing, a file that does not parse being refused rather than ignored,
and a selection written by a command leaving the person's own lines alone.
"""

from pathlib import Path

import pytest

from lup.providers.user_config import UserConfig, UserConfigFile, UserConfigHome


def written(home: Path, content: str) -> UserConfigFile:
    """A config home holding ``content`` as its config file."""
    config = UserConfigFile(home)
    config.path().parent.mkdir(parents=True, exist_ok=True)
    config.path().write_text(content, encoding="utf-8")
    return config


def test_the_config_home_follows_an_absolute_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert UserConfigHome().directory() == tmp_path / "xdg" / "lup"
    assert UserConfigFile().path() == tmp_path / "xdg" / "lup" / "config.toml"
    assert UserConfigFile().profiles_root() == tmp_path / "xdg" / "lup" / "profiles"


@pytest.mark.parametrize("named", ["", "relative/config"])
def test_an_empty_or_relative_xdg_config_home_falls_back_to_dot_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, named: str
) -> None:
    """The specification's rule: only an absolute path moves configuration."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", named)

    assert UserConfigHome().directory() == tmp_path / ".config" / "lup"


def test_a_person_who_wrote_nothing_gets_lups_defaults(tmp_path: Path) -> None:
    loaded = UserConfigFile(tmp_path / "lup").load()

    assert loaded == UserConfig()
    assert loaded.profile is None
    assert loaded.theme.claude is None
    assert loaded.theme.codex is None
    assert loaded.effort is None
    assert loaded.tier == "strongest"


def test_one_line_changes_one_answer_and_leaves_the_rest_lups(tmp_path: Path) -> None:
    config = written(
        tmp_path / "lup",
        'profile = "work"\neffort = "high"\ntier = "balanced"\n\n[theme]\nclaude = "light"\n',
    )

    loaded = config.load()

    assert (loaded.profile, loaded.effort, loaded.tier) == ("work", "high", "balanced")
    assert loaded.theme.claude == "light"
    assert loaded.theme.codex is None


def test_a_file_that_does_not_parse_is_refused_naming_itself(tmp_path: Path) -> None:
    config = written(tmp_path / "lup", "tier = \n")

    with pytest.raises(ValueError, match=str(config.path())):
        config.load()


@pytest.mark.parametrize(
    "content",
    ['tier = "enormous"\n', 'effort = "extreme"\n', 'colour = "blue"\n'],
    ids=["unknown-tier", "unknown-effort", "unknown-key"],
)
def test_a_setting_lup_cannot_read_is_refused_rather_than_dropped(
    tmp_path: Path, content: str
) -> None:
    config = written(tmp_path / "lup", content)

    with pytest.raises(ValueError, match="holds a setting lup cannot read"):
        config.load()


def test_a_theme_claude_code_does_not_ship_is_refused(tmp_path: Path) -> None:
    config = written(tmp_path / "lup", '[theme]\nclaude = "solarized"\n')

    with pytest.raises(ValueError):
        config.load()
    assert written(tmp_path / "custom", '[theme]\nclaude = "custom:mine"\n').load()


def test_selecting_a_profile_keeps_every_line_the_person_wrote(tmp_path: Path) -> None:
    config = written(
        tmp_path / "lup",
        '# my lup\ntier = "balanced"\n\n[theme]\n# drawn this way\nclaude = "light"\n',
    )

    config.select_profile("work")

    text = config.path().read_text(encoding="utf-8")
    assert "# my lup" in text and "# drawn this way" in text
    assert config.load().profile == "work"
    assert config.load().theme.claude == "light"

    config.select_profile(None)

    assert config.load().profile is None
    assert config.load().tier == "balanced"


def test_selecting_a_profile_starts_the_file_where_there_is_none(
    tmp_path: Path,
) -> None:
    config = UserConfigFile(tmp_path / "lup")

    config.select_profile("work")

    assert config.load() == UserConfig(profile="work")
