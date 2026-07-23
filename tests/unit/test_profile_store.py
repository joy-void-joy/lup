"""The personal Claude profile registry that selects the launched account.

A wrong resolution here launches the harness with the wrong Claude
account: these pin that the first added profile becomes active, removal
clears activeness only for the removed profile, resolution prefers
explicit name over active over the ``~/.claude`` default, and an unknown
name is a loud error instead of a silent fallback.
"""

from pathlib import Path

import pytest

from lup.adapters.claude.profile_store import ClaudeProfileStore


@pytest.fixture
def store(tmp_path: Path) -> ClaudeProfileStore:
    return ClaudeProfileStore(tmp_path / "profiles.json")


def test_first_added_profile_becomes_active(store: ClaudeProfileStore) -> None:
    store.add_profile("work", Path("/homes/work-claude"))
    store.add_profile("personal", Path("/homes/personal-claude"))

    assert store.active_profile() == "work"
    assert store.config_dir_for("personal") == Path("/homes/personal-claude")


def test_set_active_requires_a_registered_profile(store: ClaudeProfileStore) -> None:
    store.add_profile("work", Path("/homes/work-claude"))

    with pytest.raises(KeyError):
        store.set_active("ghost")
    store.set_active("work")
    assert store.active_profile() == "work"


def test_removing_the_active_profile_clears_only_its_activeness(
    store: ClaudeProfileStore,
) -> None:
    store.add_profile("work", Path("/homes/work-claude"))
    store.add_profile("personal", Path("/homes/personal-claude"))
    store.set_active("personal")

    store.remove_profile("personal")

    registry = store.load_registry()
    assert registry.active is None
    assert list(registry.profiles) == ["work"]

    store.set_active("work")
    store.remove_profile("personal")  # absent name is a no-op
    assert store.active_profile() == "work"


def test_resolution_prefers_explicit_then_active_then_default(
    store: ClaudeProfileStore,
) -> None:
    assert store.resolve_config_dir() == Path.home() / ".claude"

    store.add_profile("work", Path("/homes/work-claude"))
    store.add_profile("personal", Path("/homes/personal-claude"))

    assert store.resolve_config_dir() == Path("/homes/work-claude")
    assert store.resolve_config_dir("personal") == Path("/homes/personal-claude")


def test_unknown_profile_resolution_is_a_loud_error(
    store: ClaudeProfileStore,
) -> None:
    store.add_profile("work", Path("/homes/work-claude"))

    with pytest.raises(KeyError, match="unknown Claude profile 'ghost'"):
        store.resolve_config_dir("ghost")


def test_registry_updates_replace_the_file_atomically(
    store: ClaudeProfileStore, tmp_path: Path
) -> None:
    store.add_profile("work", Path("~/work-claude"))

    assert store.config_dir_for("work") == Path.home() / "work-claude"
    leftovers = [path.name for path in tmp_path.iterdir()]
    assert leftovers == ["profiles.json"]
