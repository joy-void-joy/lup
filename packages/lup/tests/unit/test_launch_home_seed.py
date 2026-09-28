"""The launcher's half of a contained Claude home: the seed mounted, the changes read back.

The seed only reaches a session if the container is started with it, and a
session's changes only come back if the launcher reads the volume it ran in.
These pin the mount and the read-back against a volume stood in by files, and
that an unreadable volume moves nothing rather than something wrong.
"""

import json
from pathlib import Path

import pytest

import lup.devtools.harness.launch as launch
from lup.launch.config_volume import HomeFile
from lup.harness.image import Image
from lup.providers.claude.config_home import ClaudeConfigHome
from lup.providers.claude.home_seed import ClaudeHomeSeed
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.user_config import UserConfig, UserConfigFile


@pytest.fixture
def account(tmp_path: Path) -> ClaudeConfigHome:
    directory = tmp_path / "account"
    directory.mkdir()
    (directory / "settings.json").write_text('{"verbose": false}', encoding="utf-8")
    return ClaudeConfigHome(directory=directory, document=tmp_path / "doc.json")


def test_a_seed_is_mounted_read_only_where_the_entrypoint_reads_it(
    tmp_path: Path,
) -> None:
    image = Image()

    argv = image.session_arguments(
        tag="lup-agent:x",
        checkout=tmp_path,
        uid=1000,
        gid=1000,
        writable={},
        read_only={},
        state_volume="lup-claude-x",
        config_home_env="CLAUDE_CONFIG_DIR",
        home_seed=tmp_path / "seed",
    )

    assert f"{tmp_path / 'seed'}:{image.home_seed}:ro" in argv
    assert f"lup-claude-x:{image.config_home}" in argv


def test_what_a_session_changed_is_read_back_and_carried(
    tmp_path: Path,
    account: ClaudeConfigHome,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = ClaudeHomeSeed.compose(account, UserConfig())
    volume = {
        **seed.settings,
        "theme": "light",
        "verbose": True,
        "model": "haiku",
        "hooks": {"Stop": []},
    }
    monkeypatch.setattr(
        launch,
        "read_config_home",
        lambda image, root, login, names: [
            HomeFile(name="settings.json", content=json.dumps(volume).encode()),
            HomeFile(name=".claude.json", content=b'{"numStartups": 2}'),
        ],
    )
    config = UserConfigFile(tmp_path / "lup")

    launch.carry_claude_home(
        Image(), tmp_path, CLAUDE_LOGIN, seed, account, config, UserConfig()
    )

    said = capsys.readouterr().out
    assert "theme.claude" in said and "verbose" in said
    assert "hooks (never leaves a container)" in said
    assert "model (the session's own)" in said
    assert config.load().theme.claude == "light"
    settings = json.loads((account.directory / "settings.json").read_text())
    assert settings == {"verbose": True}


def test_a_volume_that_cannot_be_read_moves_nothing(
    tmp_path: Path,
    account: ClaudeConfigHome,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = ClaudeHomeSeed.compose(account, UserConfig())
    monkeypatch.setattr(launch, "read_config_home", lambda *a, **k: [])

    launch.carry_claude_home(
        Image(),
        tmp_path,
        CLAUDE_LOGIN,
        seed,
        account,
        UserConfigFile(tmp_path / "lup"),
        UserConfig(),
    )

    assert "nothing it changed was returned" in capsys.readouterr().out
    assert (account.directory / "settings.json").read_text() == '{"verbose": false}'


def test_only_a_runtime_keeping_trust_in_a_document_has_one_seeded(
    tmp_path: Path,
) -> None:
    """A Codex home gains no Claude document from the shared entrypoint."""
    image = Image()

    def argv(trust_document: str) -> list[str]:
        return image.session_arguments(
            tag="lup-agent:x",
            checkout=tmp_path,
            uid=1000,
            gid=1000,
            writable={},
            read_only={},
            state_volume="lup-x",
            config_home_env="HOME_VARIABLE",
            trust_document=trust_document,
        )

    assert "LUP_TRUST_DOCUMENT=.claude.json" in argv(CLAUDE_LOGIN.trust_document)
    assert not any("LUP_TRUST_DOCUMENT" in word for word in argv(""))
    assert CLAUDE_LOGIN.trust_document == ".claude.json"
