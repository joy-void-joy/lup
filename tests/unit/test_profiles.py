"""Behavior tests for the profile registry (named Claude config dirs).

Exercises registry CRUD with state verification against a temporary
registry file: add/activate/remove transitions, persistence round-trips,
and the resolve order (explicit name > active profile > default).
"""

from pathlib import Path

import pytest

from lup import profiles


@pytest.fixture(autouse=True)
def tmp_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the machine-wide registry at a throwaway file."""
    registry_path = tmp_path / "lup" / "profiles.json"
    monkeypatch.setattr(profiles, "REGISTRY_PATH", registry_path)
    return registry_path


def test_missing_registry_reads_as_empty(tmp_registry: Path) -> None:
    assert not tmp_registry.exists()
    assert profiles.profiles() == {}
    assert profiles.active_profile() is None


def test_first_added_profile_becomes_active(tmp_path: Path) -> None:
    profiles.add_profile("work", tmp_path / "work-config")
    assert profiles.active_profile() == "work"

    profiles.add_profile("personal", tmp_path / "personal-config")
    # A later addition must not steal the active selection.
    assert profiles.active_profile() == "work"
    assert set(profiles.profiles()) == {"work", "personal"}


def test_registry_round_trips_through_disk(tmp_registry: Path, tmp_path: Path) -> None:
    profiles.add_profile("work", tmp_path / "cfg")
    assert tmp_registry.exists()
    # A fresh load from disk sees the same state (no in-memory cache).
    reloaded = profiles.load_registry()
    assert reloaded.get("active") == "work"
    assert (reloaded.get("profiles") or {})["work"]["config_dir"] == str(
        tmp_path / "cfg"
    )


def test_set_active_switches_and_rejects_unknown(tmp_path: Path) -> None:
    profiles.add_profile("a", tmp_path / "a")
    profiles.add_profile("b", tmp_path / "b")

    profiles.set_active("b")
    assert profiles.active_profile() == "b"

    with pytest.raises(KeyError):
        profiles.set_active("ghost")
    assert profiles.active_profile() == "b"


def test_remove_clears_active_only_for_the_removed_profile(tmp_path: Path) -> None:
    profiles.add_profile("a", tmp_path / "a")
    profiles.add_profile("b", tmp_path / "b")

    profiles.remove_profile("b")  # not active: selection untouched
    assert profiles.active_profile() == "a"
    assert set(profiles.profiles()) == {"a"}

    profiles.remove_profile("a")  # active: selection cleared
    assert profiles.active_profile() is None
    assert profiles.profiles() == {}

    profiles.remove_profile("never-existed")  # unknown: a no-op, not an error


def test_config_dir_for_expands_user_and_rejects_unknown(tmp_path: Path) -> None:
    profiles.add_profile("home", Path("~/claude-home"))
    assert profiles.config_dir_for("home") == Path.home() / "claude-home"

    with pytest.raises(KeyError):
        profiles.config_dir_for("ghost")


def test_resolve_config_dir_prefers_name_then_active_then_default(
    tmp_path: Path,
) -> None:
    assert profiles.resolve_config_dir() == profiles.DEFAULT_CONFIG_DIR

    profiles.add_profile("a", tmp_path / "a")
    profiles.add_profile("b", tmp_path / "b")
    assert profiles.resolve_config_dir() == tmp_path / "a"  # active
    assert profiles.resolve_config_dir("b") == tmp_path / "b"  # explicit wins

    profiles.remove_profile("a")
    assert profiles.resolve_config_dir() == profiles.DEFAULT_CONFIG_DIR
