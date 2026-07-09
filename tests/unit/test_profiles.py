"""Behavior tests for Claude account profiles.

The seam is one verb — ``select(name, client)`` — so these pin its
behavior: the returned client's subprocess env carries the resolved
``CLAUDE_CONFIG_DIR``, the given client stays untouched, and the resolve
order is explicit name > active profile > default. The rest exercises
what the Claude implementation owns: registry CRUD with state
verification against a temporary registry file, and that registry
documents already on disk keep loading, resolving, and round-tripping.
"""

import json
from pathlib import Path

import claude_agent_sdk as claude
import pytest

from lup.adapters.clients.claude.create import compose_claude
from lup.adapters.clients.claude.sessions import ClaudeSessions
from lup.adapters.clients.composed import ComposedClient
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.claude.profile import (
    CONFIG_DIR_ENV,
    DEFAULT_CONFIG_DIR,
    ClaudeProfile,
)
from lup.adapters.profiles.claude.store import ProfileStore
from tests.unit.conftest import RecordingSessions


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    """A registry store pointed at a throwaway file."""
    return ProfileStore(registry_path=tmp_path / "lup" / "profiles.json")


@pytest.fixture
def support(store: ProfileStore) -> ClaudeProfile:
    """Profile support composing the throwaway store."""
    return ClaudeProfile(store=store)


def selected_config_dir(
    support: ClaudeProfile, name: str | None, client: ComposedClient
) -> str:
    """Run ``select`` and read the config dir it put on the client's env."""
    selected = support.select(name, client)
    assert isinstance(selected, ComposedClient)
    assert isinstance(selected.sessions, ClaudeSessions)
    return selected.sessions.options.env[CONFIG_DIR_ENV]


# ── the select verb ────────────────────────────────────────


def test_select_injects_the_account_env_onto_a_copy(
    support: ClaudeProfile, store: ProfileStore, tmp_path: Path
) -> None:
    store.add_profile("work", tmp_path / "work-config")
    native = claude.ClaudeAgentOptions(env={"KEEP": "1"})
    client = compose_claude(native)

    selected = support.select("work", client)

    assert isinstance(selected, ComposedClient)
    assert isinstance(selected.sessions, ClaudeSessions)
    assert selected.sessions.options.env[CONFIG_DIR_ENV] == str(
        tmp_path / "work-config"
    )
    assert selected.sessions.options.env["KEEP"] == "1"  # existing env survives
    assert CONFIG_DIR_ENV not in native.env  # given client untouched


def test_select_precedence_explicit_then_active_then_default(
    support: ClaudeProfile, store: ProfileStore, tmp_path: Path
) -> None:
    client = compose_claude(claude.ClaudeAgentOptions())

    assert selected_config_dir(support, None, client) == str(DEFAULT_CONFIG_DIR)

    store.add_profile("a", tmp_path / "a")
    store.add_profile("b", tmp_path / "b")
    assert selected_config_dir(support, None, client) == str(tmp_path / "a")  # active
    assert selected_config_dir(support, "b", client) == str(tmp_path / "b")  # explicit

    store.remove_profile("a")
    assert selected_config_dir(support, None, client) == str(DEFAULT_CONFIG_DIR)


def test_select_refuses_a_non_claude_client(support: ClaudeProfile) -> None:
    with pytest.raises(TypeError):
        support.select(
            None, ComposedClient(RecordingSessions(LupAgentOptions(model="probe"), []))
        )


# ── the implementation's own registry ──────────────────────


def test_missing_registry_reads_as_empty(
    support: ClaudeProfile, store: ProfileStore
) -> None:
    assert not store.registry_path.exists()
    assert store.load_registry().profiles == {}
    assert store.active_profile() is None
    assert support.resolve_config_dir() == DEFAULT_CONFIG_DIR


def test_first_added_profile_becomes_active(
    store: ProfileStore, tmp_path: Path
) -> None:
    store.add_profile("work", tmp_path / "work-config")
    assert store.active_profile() == "work"

    store.add_profile("personal", tmp_path / "personal-config")
    # A later addition must not steal the active selection.
    assert store.active_profile() == "work"
    assert sorted(store.load_registry().profiles) == ["personal", "work"]


def test_registry_round_trips_through_disk(store: ProfileStore, tmp_path: Path) -> None:
    store.add_profile("work", tmp_path / "cfg")
    assert store.registry_path.exists()
    # A fresh instance on the same path sees the same state (no in-memory cache).
    reloaded = ProfileStore(registry_path=store.registry_path)
    assert reloaded.active_profile() == "work"
    assert reloaded.config_dir_for("work") == tmp_path / "cfg"


def test_existing_registry_document_loads_and_round_trips(tmp_path: Path) -> None:
    """A registry document already on disk keeps loading, resolving, round-tripping."""
    registry_path = tmp_path / "profiles.json"
    registry_path.write_text(
        json.dumps(
            {
                "profiles": {"work": {"config_dir": str(tmp_path / "work-config")}},
                "active": "work",
            },
            indent=2,
        )
        + "\n"
    )
    store = ProfileStore(registry_path=registry_path)
    support = ClaudeProfile(store=store)

    assert support.resolve_config_dir() == tmp_path / "work-config"

    store.add_profile("personal", tmp_path / "personal-config")
    on_disk = json.loads(registry_path.read_text())
    assert on_disk["active"] == "work"
    assert on_disk["profiles"]["work"] == {"config_dir": str(tmp_path / "work-config")}
    assert on_disk["profiles"]["personal"] == {
        "config_dir": str(tmp_path / "personal-config")
    }


def test_set_active_switches_and_rejects_unknown(
    store: ProfileStore, tmp_path: Path
) -> None:
    store.add_profile("a", tmp_path / "a")
    store.add_profile("b", tmp_path / "b")

    store.set_active("b")
    assert store.active_profile() == "b"

    with pytest.raises(KeyError):
        store.set_active("ghost")
    assert store.active_profile() == "b"


def test_remove_clears_active_only_for_the_removed_profile(
    store: ProfileStore, tmp_path: Path
) -> None:
    store.add_profile("a", tmp_path / "a")
    store.add_profile("b", tmp_path / "b")

    store.remove_profile("b")  # not active: selection untouched
    assert store.active_profile() == "a"
    assert sorted(store.load_registry().profiles) == ["a"]

    store.remove_profile("a")  # active: selection cleared
    assert store.active_profile() is None
    assert store.load_registry().profiles == {}

    store.remove_profile("never-existed")  # unknown: a no-op, not an error


def test_config_dir_for_expands_user_and_rejects_unknown(
    store: ProfileStore,
) -> None:
    store.add_profile("home", Path("~/claude-home"))
    assert store.config_dir_for("home") == Path.home() / "claude-home"

    with pytest.raises(KeyError):
        store.config_dir_for("ghost")


def test_resolve_config_dir_prefers_name_then_active_then_default(
    support: ClaudeProfile, store: ProfileStore, tmp_path: Path
) -> None:
    assert support.resolve_config_dir() == DEFAULT_CONFIG_DIR

    store.add_profile("a", tmp_path / "a")
    store.add_profile("b", tmp_path / "b")
    assert support.resolve_config_dir() == tmp_path / "a"  # active
    assert support.resolve_config_dir("b") == tmp_path / "b"  # explicit wins

    store.remove_profile("a")
    assert support.resolve_config_dir() == DEFAULT_CONFIG_DIR
