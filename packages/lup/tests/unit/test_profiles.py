"""The profile surface a launch selects an account through.

A wrong answer here launches the harness under the wrong account, or silently
takes over a config home the caller had already chosen: these pin that an
explicit name beats the selected one, that naming neither inherits the
surrounding environment rather than forcing a default, that the command tree
reports an unknown name with the roster instead of a traceback, and that one
name is one account on every runtime.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lup.devtools.harness.profile_app import create_profile_app
from lup.providers.claude.login import CLAUDE_LOGIN
from lup.providers.codex.login import CODEX_LOGIN
from lup.providers.profile_tree import user_profile_directory
from lup.providers.profiles import ProfileDirectory, UnknownProfile
from lup.providers.user_config import UserConfigFile

PLAIN_CONSOLE = {"FORCE_COLOR": None, "NO_COLOR": "1", "TERM": "dumb"}

runner = CliRunner(env=PLAIN_CONSOLE)


@pytest.fixture
def config(tmp_path: Path) -> UserConfigFile:
    return UserConfigFile(tmp_path / "lup")


@pytest.fixture
def directory(config: UserConfigFile) -> ProfileDirectory:
    return user_profile_directory(CLAUDE_LOGIN, config)


def sign_in(home: Path) -> None:
    """Leave the file Claude Code writes on a completed login."""
    home.mkdir(parents=True, exist_ok=True)
    CLAUDE_LOGIN.credentials_path(home).write_text("{}", encoding="utf-8")


def test_a_person_who_has_started_no_profiles_reads_an_empty_roster(
    directory: ProfileDirectory,
) -> None:
    assert directory.entries() == []
    assert directory.launch_home(None) is None


def test_a_profile_selects_the_home_inside_its_own_directory(
    directory: ProfileDirectory, config: UserConfigFile
) -> None:
    added = directory.add("work")

    assert added.config_dir == config.profiles_root() / "work" / "claude-config"
    assert added.config_dir.is_dir()
    assert directory.launch_home("work") == added.config_dir


def test_one_name_holds_a_home_for_each_runtime_side_by_side(
    directory: ProfileDirectory, config: UserConfigFile
) -> None:
    directory.add("work")
    codex = user_profile_directory(CODEX_LOGIN, config)

    assert codex.launch_home("work") == config.profiles_root() / "work" / "codex-home"
    assert directory.launch_home("work") != codex.launch_home("work")


def test_the_first_profile_started_becomes_the_selection_in_the_config_file(
    directory: ProfileDirectory, config: UserConfigFile
) -> None:
    directory.add("work")
    directory.add("personal")

    assert config.load().profile == "work"
    assert directory.launch_home(None) == directory.profile("work").config_dir

    directory.use("personal")
    assert config.load().profile == "personal"
    assert directory.launch_home(None) == directory.profile("personal").config_dir


def test_launch_prefers_an_explicit_name_over_the_selected_one(
    directory: ProfileDirectory,
) -> None:
    directory.add("work")
    directory.add("personal")

    assert directory.launch_home("personal") == directory.profile("personal").config_dir


def test_entries_report_activeness_and_whether_a_home_holds_a_login(
    directory: ProfileDirectory,
) -> None:
    sign_in(directory.add("work").config_dir)
    directory.add("personal")

    entries = {entry.name: entry for entry in directory.entries()}

    assert entries["work"].active and entries["work"].logged_in
    assert not entries["personal"].active
    assert not entries["personal"].logged_in


def test_a_profile_refuses_a_home_its_name_does_not_derive(
    directory: ProfileDirectory, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="symlink"):
        directory.add("work", tmp_path / "elsewhere")


def test_forgetting_a_profile_says_to_remove_the_directory(
    directory: ProfileDirectory, config: UserConfigFile
) -> None:
    directory.add("work")

    with pytest.raises(ValueError, match=str(config.profiles_root() / "work")):
        directory.remove("work")


def test_forgetting_the_selected_profile_names_its_selection_too(
    directory: ProfileDirectory, config: UserConfigFile
) -> None:
    """Removed alone, the directory leaves launches refused for a ghost."""
    directory.add("work")
    directory.add("personal")

    with pytest.raises(ValueError) as selected:
        directory.remove("work")
    with pytest.raises(ValueError) as unselected:
        directory.remove("personal")

    assert f"the `profile` line in {config.path()}, which selects it" in str(
        selected.value
    )
    assert "selects it" not in str(unselected.value)


def test_a_selection_whose_directory_is_gone_reports_the_roster(
    directory: ProfileDirectory, config: UserConfigFile
) -> None:
    """The launch comment's second case: a selected name nothing answers to."""
    directory.add("work")
    config.select_profile("departed")

    with pytest.raises(UnknownProfile, match="unknown profile 'departed'"):
        directory.launch_home(None)


def test_an_unknown_name_carries_the_roster_however_it_was_resolved(
    directory: ProfileDirectory,
) -> None:
    """What the launcher renders, so it stops reporting a bare ``KeyError``."""
    directory.add("work")

    with pytest.raises(UnknownProfile) as raised:
        directory.launch_home("ghost")

    assert "unknown profile 'ghost'" in str(raised.value)
    assert "known: work" in str(raised.value)
    assert "profile add ghost" in str(raised.value)


def test_the_command_tree_lists_every_profile_and_marks_the_active_one(
    directory: ProfileDirectory,
) -> None:
    directory.add("work")
    directory.add("personal")

    result = runner.invoke(create_profile_app(directory), ["list"])

    assert result.exit_code == 0
    assert "* work" in result.output
    assert "  personal" in result.output
    assert "no login yet" in result.output


def test_the_command_tree_names_the_roster_on_an_unknown_profile(
    directory: ProfileDirectory,
) -> None:
    directory.add("work")

    result = runner.invoke(create_profile_app(directory), ["use", "ghost"])

    assert result.exit_code != 0
    assert "unknown profile 'ghost'" in result.output
    assert "known: work" in result.output


def test_adding_through_the_command_tree_says_how_to_sign_the_home_in(
    directory: ProfileDirectory,
) -> None:
    result = runner.invoke(create_profile_app(directory), ["add", "work"])

    assert result.exit_code == 0
    assert CLAUDE_LOGIN.config_home_env in result.output
    assert directory.launch_home("work") == directory.profile("work").config_dir


def test_an_account_is_named_where_a_run_starts_rather_than_inherited(
    directory: ProfileDirectory,
) -> None:
    """The seam an entry point takes instead of reading the console.

    Selecting a profile has to reach everything a run opens — planners,
    workers, reviewers — and it reached only what a launcher opened, because
    every other entry point derived its environment from whatever the shell
    exported. Resolving once, into a value the run is handed, is what makes
    an entry point that forgets impossible to write rather than merely wrong.
    """
    home = directory.add("work").config_dir

    account = directory.account("work")

    assert (account.name, account.home) == ("work", home)
    exported = account.exported({"PATH": "/usr/bin"})
    assert exported["PATH"] == "/usr/bin"
    assert exported == {**exported, **CLAUDE_LOGIN.environment(home)}


def test_an_explicit_name_beats_the_selection_for_an_account(
    directory: ProfileDirectory,
) -> None:
    directory.add("work")
    directory.add("personal")
    directory.use("personal")

    assert directory.account(None).name == "personal"
    assert directory.account("work").name == "work"
    assert directory.account("work").home == directory.profile("work").config_dir


def test_naming_no_account_where_none_is_selected_stays_on_the_surrounding_one(
    directory: ProfileDirectory,
) -> None:
    """A real answer rather than a gap, and it writes nothing.

    A person who keeps no profiles has no account to name, and a session
    opened inside another one should stay on the account it was started
    under. Both are the same fact: this account exports nothing, so what the
    environment already carries survives.
    """
    account = directory.account(None)

    assert (account.name, account.home) == (None, None)
    assert account.exported({"CLAUDE_CONFIG_DIR": "/already/chosen"}) == {
        "CLAUDE_CONFIG_DIR": "/already/chosen"
    }
