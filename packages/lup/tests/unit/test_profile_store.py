"""The personal Claude profile registry that selects the launched account.

A wrong resolution here launches the harness with the wrong Claude
account: these pin that the first added profile becomes active, removal
clears activeness only for the removed profile, resolution prefers
explicit name over active over the home the environment selects, and an
unknown name is a loud error instead of a silent fallback.

Reading and curating are separate capabilities over one file, so each test
holds whichever it exercises and both are pointed at the same registry.
"""

from pathlib import Path

import pytest

from lup.providers.claude.login import CLAUDE_CONFIG_DIR, CLAUDE_LOGIN
from lup.providers.claude.profile_store import (
    AccountFile,
    ClaudeProfileNames,
    ClaudeProfileRegistrar,
)
from lup.providers.profiles import DefaultHomeProfile


@pytest.fixture
def accounts(tmp_path: Path) -> AccountFile:
    return AccountFile(tmp_path / "profiles.json")


@pytest.fixture
def names(accounts: AccountFile) -> ClaudeProfileNames:
    return ClaudeProfileNames(accounts)


@pytest.fixture
def registrar(accounts: AccountFile) -> ClaudeProfileRegistrar:
    return ClaudeProfileRegistrar(accounts)


def test_first_added_profile_becomes_active(
    names: ClaudeProfileNames, registrar: ClaudeProfileRegistrar
) -> None:
    registrar.add_profile("work", Path("/homes/work-claude"))
    registrar.add_profile("personal", Path("/homes/personal-claude"))

    assert names.active_profile() == "work"
    assert names.config_dir_for("personal") == Path("/homes/personal-claude")


def test_set_active_requires_a_registered_profile(
    names: ClaudeProfileNames, registrar: ClaudeProfileRegistrar
) -> None:
    registrar.add_profile("work", Path("/homes/work-claude"))

    with pytest.raises(KeyError):
        registrar.set_active("ghost")
    registrar.set_active("work")
    assert names.active_profile() == "work"


def test_removing_the_active_profile_clears_only_its_activeness(
    accounts: AccountFile,
    names: ClaudeProfileNames,
    registrar: ClaudeProfileRegistrar,
) -> None:
    registrar.add_profile("work", Path("/homes/work-claude"))
    registrar.add_profile("personal", Path("/homes/personal-claude"))
    registrar.set_active("personal")

    registrar.remove_profile("personal")

    registry = accounts.load_registry()
    assert registry.active is None
    assert list(registry.profiles) == ["work"]

    registrar.set_active("work")
    registrar.remove_profile("personal")  # absent name is a no-op
    assert names.active_profile() == "work"


def test_resolution_prefers_explicit_then_active_then_default(
    accounts: AccountFile,
    registrar: ClaudeProfileRegistrar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CLAUDE_CONFIG_DIR, raising=False)
    assert accounts.resolve_config_dir() == CLAUDE_LOGIN.ambient_home

    registrar.add_profile("work", Path("/homes/work-claude"))
    registrar.add_profile("personal", Path("/homes/personal-claude"))

    assert accounts.resolve_config_dir() == Path("/homes/work-claude")
    assert accounts.resolve_config_dir("personal") == Path("/homes/personal-claude")


def test_the_default_is_the_home_the_environment_selects(
    accounts: AccountFile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming none leaves the home a session inherits, and its login is there."""
    monkeypatch.setenv(CLAUDE_CONFIG_DIR, str(tmp_path / "selected"))

    assert accounts.resolve_config_dir() == tmp_path / "selected"


def test_unknown_profile_resolution_is_a_loud_error(
    accounts: AccountFile, registrar: ClaudeProfileRegistrar
) -> None:
    registrar.add_profile("work", Path("/homes/work-claude"))

    with pytest.raises(KeyError, match="unknown Claude profile 'ghost'"):
        accounts.resolve_config_dir("ghost")


def test_a_stored_default_home_refuses_itself_rather_than_its_neighbours(
    accounts: AccountFile,
) -> None:
    """Resolution judges the name asked for, as a launch does, not the whole file."""
    accounts.registry_path.write_text(
        '{"profiles":{"main":{"config_dir":"~/.claude"},'
        '"work":{"config_dir":"/homes/work-claude"}},"active":"main"}',
        encoding="utf-8",
    )

    assert accounts.resolve_config_dir("work") == Path("/homes/work-claude")
    with pytest.raises(KeyError, match="unknown Claude profile 'ghost'"):
        accounts.resolve_config_dir("ghost")
    with pytest.raises(DefaultHomeProfile, match="profile 'main'"):
        accounts.resolve_config_dir()


def test_registry_updates_replace_the_file_atomically(
    names: ClaudeProfileNames, registrar: ClaudeProfileRegistrar, tmp_path: Path
) -> None:
    registrar.add_profile("work", Path("~/work-claude"))

    assert names.config_dir_for("work") == Path.home() / "work-claude"
    leftovers = [path.name for path in tmp_path.iterdir()]
    assert leftovers == ["profiles.json"]


def test_the_two_capabilities_read_one_registry(
    names: ClaudeProfileNames, registrar: ClaudeProfileRegistrar
) -> None:
    """Splitting the powers must not split the file they answer for."""
    registrar.add_profile("work", Path("/homes/work-claude"))

    assert names.names() == ["work"]
