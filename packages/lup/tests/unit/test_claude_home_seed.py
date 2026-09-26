"""What a contained Claude session's home is seeded with, and what comes back from it.

The seed is the account's settings with the person's lup config winning; the
return is only what a session changed of the person's, each key where it
belongs, and nothing that runs code or was the session's own to pick. A
return that carried a hook would run it on the host; one that carried a
``/model`` would make one session's pick every session's default.
"""

import json
import subprocess
from pathlib import Path

import pytest

from lup.harness.image import Image
from lup.harness.requirements import Manifest
from lup.providers.claude.config_home import ClaudeConfigHome
from lup.providers.claude.home_seed import ClaudeHomeReturn, ClaudeHomeSeed
from lup.providers.user_config import UserConfig, UserConfigFile
from lup.types import JsonObject


@pytest.fixture
def account(tmp_path: Path) -> ClaudeConfigHome:
    """A selected account's home, with settings, a document and key bindings."""
    directory = tmp_path / "account"
    directory.mkdir()
    (directory / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
                "verbose": False,
                "model": "sonnet",
            }
        ),
        encoding="utf-8",
    )
    (directory / "keybindings.json").write_text('{"bindings": []}\n', encoding="utf-8")
    document = tmp_path / "account.claude.json"
    document.write_text(
        json.dumps(
            {
                "theme": "light-ansi",
                "verbose": True,
                "diffTool": "terminal",
                "numStartups": 40,
                "oauthAccount": {"emailAddress": "someone@example.invalid"},
            }
        ),
        encoding="utf-8",
    )
    return ClaudeConfigHome(directory=directory, document=document)


def test_the_seed_is_the_account_with_the_lup_config_winning(
    account: ClaudeConfigHome,
) -> None:
    personal = UserConfig.model_validate(
        {
            "editor": "vim",
            "claude": {"settings": {"verbose": True, "tui": "fullscreen"}},
        }
    )

    seed = ClaudeHomeSeed.compose(account, personal, model="opus[1m]", effort="xhigh")

    assert seed.settings == {
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
        "verbose": True,
        "tui": "fullscreen",
        "model": "opus[1m]",
        "effortLevel": "xhigh",
        "editorMode": "vim",
        "theme": "light-ansi",
    }
    assert seed.document == {"diffTool": "terminal"}
    assert seed.keybindings == '{"bindings": []}\n'


def test_a_named_theme_wins_and_an_unnamed_one_falls_to_lups_palette(
    tmp_path: Path, account: ClaudeConfigHome
) -> None:
    named = UserConfig.model_validate({"theme": {"claude": "dark"}})
    assert ClaudeHomeSeed.compose(account, named).settings["theme"] == "dark"

    bare = ClaudeConfigHome(directory=tmp_path / "empty", document=tmp_path / "none")
    assert ClaudeHomeSeed.compose(bare, UserConfig()).settings == {
        "theme": "dark-daltonized"
    }
    assert ClaudeHomeSeed.compose(bare, UserConfig()).keybindings is None


def returned(
    account: ClaudeConfigHome,
    personal: UserConfig,
    settings: JsonObject,
    document: JsonObject | None = None,
    keybindings: str | None = '{"bindings": []}\n',
) -> ClaudeHomeReturn:
    """What a session leaving ``settings`` in its volume sends back."""
    seed = ClaudeHomeSeed.compose(account, personal, model="opus[1m]")
    return ClaudeHomeReturn.between(
        seed,
        {**seed.settings, **settings},
        {**seed.document, **(document or {})},
        keybindings,
        personal,
    )


def test_a_preference_returns_to_the_account_and_a_portable_one_to_the_lup_config(
    tmp_path: Path, account: ClaudeConfigHome
) -> None:
    config = UserConfigFile(tmp_path / "lup")

    back = returned(
        account,
        UserConfig(),
        {"theme": "light", "editorMode": "vim", "showTurnDuration": False},
        {"diffTool": "auto"},
    )
    back.apply(account, config)

    assert back.portable == {("theme", "claude"): "light", ("editor",): "vim"}
    assert back.settings == {"showTurnDuration": False}
    assert back.document == {"diffTool": "auto"}
    loaded = config.load()
    assert (loaded.theme.claude, loaded.editor) == ("light", "vim")
    written = json.loads((account.directory / "settings.json").read_text())
    assert written["showTurnDuration"] is False and "hooks" in written
    document = json.loads(account.document.read_text())
    assert document["diffTool"] == "auto" and document["numStartups"] == 40


def test_a_hook_a_session_wrote_never_leaves_its_container(
    tmp_path: Path, account: ClaudeConfigHome
) -> None:
    hooks: JsonObject = {
        "PreToolUse": [{"hooks": [{"type": "command", "command": "curl x"}]}]
    }

    back = returned(account, UserConfig(), {"hooks": hooks, "env": {"A": "1"}})
    back.apply(account, UserConfigFile(tmp_path / "lup"))

    assert back.carried() == []
    assert back.withheld == ["env", "hooks"]
    written = json.loads((account.directory / "settings.json").read_text())
    assert written["hooks"] == {
        "Stop": [{"hooks": [{"type": "command", "command": "x"}]}]
    }


def test_a_sessions_model_and_effort_stay_in_that_session(
    account: ClaudeConfigHome,
) -> None:
    back = returned(
        account,
        UserConfig(),
        {"model": "haiku", "modelSettings": {"claude-haiku": {"effortLevel": "low"}}},
    )

    assert back.carried() == []
    assert back.session == ["model", "modelSettings"]


def test_a_key_the_lup_config_holds_returns_there(
    tmp_path: Path, account: ClaudeConfigHome
) -> None:
    config = UserConfigFile(tmp_path / "lup")
    config.record({("claude", "settings", "verbose"): True})
    personal = config.load()

    back = returned(account, personal, {"verbose": False})
    back.apply(account, config)

    assert back.portable == {("claude", "settings", "verbose"): False}
    assert config.load().claude.settings == {"verbose": False}


def test_a_value_the_lup_config_refuses_stays_with_the_account(
    tmp_path: Path, account: ClaudeConfigHome
) -> None:
    config = UserConfigFile(tmp_path / "lup")

    back = returned(account, UserConfig(), {"editorMode": "emacs"})
    back.apply(account, config)

    assert config.load().editor is None
    written = json.loads((account.directory / "settings.json").read_text())
    assert written["editorMode"] == "emacs"


def test_key_bindings_come_back_only_where_the_session_changed_them(
    tmp_path: Path, account: ClaudeConfigHome
) -> None:
    unchanged = returned(account, UserConfig(), {})
    assert unchanged.keybindings is None

    changed = returned(account, UserConfig(), {}, keybindings='{"bindings": [1]}\n')
    changed.apply(account, UserConfigFile(tmp_path / "lup"))

    assert (account.directory / "keybindings.json").read_text() == (
        '{"bindings": [1]}\n'
    )


def test_the_entrypoint_applies_a_written_seed_to_a_volume(
    tmp_path: Path, account: ClaudeConfigHome
) -> None:
    """The image's own seeding lines, run against a directory standing in for the volume."""
    rendered = Image().dockerfile(Manifest())
    image = Image()
    block = rendered[rendered.index(f"seed={image.home_seed}") :]
    block = block[: block.index("\nfi\n") + 4]
    seed = ClaudeHomeSeed.compose(account, UserConfig.model_validate({"editor": "vim"}))
    written = seed.write(tmp_path / "seed")
    volume = tmp_path / "volume"
    volume.mkdir()
    (volume / ".claude.json").write_text('{"numStartups": 3}', encoding="utf-8")
    (volume / "settings.json").write_text('{"hooks": {"x": 1}}', encoding="utf-8")
    (volume / "keybindings.json").write_text("stale", encoding="utf-8")
    script = f"config={volume}\n" + block.replace(
        f"seed={image.home_seed}", f"seed={written}"
    )

    subprocess.run(["sh", "-c", script], check=True)
    (written / "replace" / "keybindings.json").unlink()
    subprocess.run(["sh", "-c", script], check=True)

    assert json.loads((volume / "settings.json").read_text()) == seed.settings
    assert json.loads((volume / ".claude.json").read_text()) == {
        "numStartups": 3,
        "diffTool": "terminal",
    }
    assert not (volume / "keybindings.json").exists()
