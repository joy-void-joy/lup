"""The profile surface a launch selects an account through.

A wrong answer here launches the harness under the wrong Claude account, or
silently takes over a config home the caller had already chosen: these pin
that an explicit name beats the active one, that naming neither inherits the
surrounding environment rather than forcing a default, and that the command
tree reports an unknown name with the roster instead of a traceback.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lup.adapters.claude.login import CLAUDE_LOGIN
from lup.adapters.claude.profile_store import ClaudeProfileStore
from lup.devtools.harness.profile_app import create_profile_app
from lup.runtime.profiles import ProfileDirectory

PLAIN_CONSOLE = {"FORCE_COLOR": None, "NO_COLOR": "1", "TERM": "dumb"}

runner = CliRunner(env=PLAIN_CONSOLE)


@pytest.fixture
def directory(tmp_path: Path) -> ProfileDirectory:
    return ProfileDirectory(
        ClaudeProfileStore(tmp_path / "profiles.json"), CLAUDE_LOGIN
    )


def sign_in(home: Path) -> None:
    """Leave the file Claude Code writes on a completed login."""
    home.mkdir(parents=True, exist_ok=True)
    CLAUDE_LOGIN.credentials_path(home).write_text("{}", encoding="utf-8")


def test_naming_no_profile_without_an_active_one_inherits_the_environment(
    directory: ProfileDirectory,
) -> None:
    assert directory.launch_home(None) is None


def test_launch_prefers_an_explicit_name_over_the_active_one(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    directory.add("work", tmp_path / "work-home")
    directory.add("personal", tmp_path / "personal-home")

    assert directory.launch_home(None) == tmp_path / "work-home"
    assert directory.launch_home("personal") == tmp_path / "personal-home"

    directory.use("personal")
    assert directory.launch_home(None) == tmp_path / "personal-home"


def test_launching_an_unknown_profile_is_a_loud_error(
    directory: ProfileDirectory,
) -> None:
    with pytest.raises(KeyError):
        directory.launch_home("ghost")


def test_entries_report_activeness_and_whether_a_home_holds_a_login(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    sign_in(tmp_path / "work-home")
    directory.add("work", tmp_path / "work-home")
    directory.add("personal", tmp_path / "personal-home")

    entries = {entry.name: entry for entry in directory.entries()}

    assert entries["work"].active and entries["work"].logged_in
    assert not entries["personal"].active
    assert not entries["personal"].logged_in


def test_a_profile_added_without_a_home_gets_one_beside_the_registry(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    added = directory.add("work")

    assert added.config_dir == tmp_path / "homes" / "work"
    assert not added.logged_in


def test_removing_a_profile_leaves_its_configuration_home_on_disk(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    sign_in(tmp_path / "work-home")
    directory.add("work", tmp_path / "work-home")

    removed = directory.remove("work")

    assert removed.name == "work"
    assert CLAUDE_LOGIN.credentials_path(tmp_path / "work-home").exists()
    assert directory.entries() == []


def test_the_command_tree_lists_every_profile_and_marks_the_active_one(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    directory.add("work", tmp_path / "work-home")
    directory.add("personal", tmp_path / "personal-home")

    result = runner.invoke(create_profile_app(directory), ["list"])

    assert result.exit_code == 0
    assert "* work" in result.output
    assert "  personal" in result.output
    assert "no login yet" in result.output


def test_the_command_tree_names_the_roster_on_an_unknown_profile(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    directory.add("work", tmp_path / "work-home")

    result = runner.invoke(create_profile_app(directory), ["use", "ghost"])

    assert result.exit_code != 0
    assert "unknown profile 'ghost'" in result.output
    assert "known: work" in result.output


def test_adding_through_the_command_tree_says_how_to_sign_the_home_in(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    result = runner.invoke(
        create_profile_app(directory),
        ["add", "work", "--config-dir", str(tmp_path / "work-home")],
    )

    assert result.exit_code == 0
    assert CLAUDE_LOGIN.config_home_env in result.output
    assert directory.launch_home("work") == tmp_path / "work-home"
