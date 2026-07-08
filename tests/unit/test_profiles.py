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

from lup.adapters.clients.claude.client import ClaudeClient
from lup.adapters.options import LupAgentOptions
from lup.adapters.profiles.claude import (
    CONFIG_DIR_ENV,
    DEFAULT_CONFIG_DIR,
    ClaudeProfileSupport,
)
from tests.unit.conftest import RecordingClient


@pytest.fixture
def support(tmp_path: Path) -> ClaudeProfileSupport:
    """Profile support pointed at a throwaway registry file."""
    return ClaudeProfileSupport(registry_path=tmp_path / "lup" / "profiles.json")


def selected_config_dir(
    support: ClaudeProfileSupport, name: str | None, client: ClaudeClient
) -> str:
    """Run ``select`` and read the config dir it put on the client's env."""
    selected = support.select(name, client)
    assert isinstance(selected, ClaudeClient)
    return selected.options.env[CONFIG_DIR_ENV]


# ── the select verb ────────────────────────────────────────


def test_select_injects_the_account_env_onto_a_copy(
    support: ClaudeProfileSupport, tmp_path: Path
) -> None:
    support.add_profile("work", tmp_path / "work-config")
    client = ClaudeClient(claude.ClaudeAgentOptions(env={"KEEP": "1"}))

    selected = support.select("work", client)

    assert isinstance(selected, ClaudeClient)
    assert selected.options.env[CONFIG_DIR_ENV] == str(tmp_path / "work-config")
    assert selected.options.env["KEEP"] == "1"  # existing env survives
    assert CONFIG_DIR_ENV not in client.options.env  # given client untouched


def test_select_precedence_explicit_then_active_then_default(
    support: ClaudeProfileSupport, tmp_path: Path
) -> None:
    client = ClaudeClient(claude.ClaudeAgentOptions())

    assert selected_config_dir(support, None, client) == str(DEFAULT_CONFIG_DIR)

    support.add_profile("a", tmp_path / "a")
    support.add_profile("b", tmp_path / "b")
    assert selected_config_dir(support, None, client) == str(tmp_path / "a")  # active
    assert selected_config_dir(support, "b", client) == str(tmp_path / "b")  # explicit

    support.remove_profile("a")
    assert selected_config_dir(support, None, client) == str(DEFAULT_CONFIG_DIR)


def test_select_refuses_a_non_claude_client(support: ClaudeProfileSupport) -> None:
    with pytest.raises(TypeError):
        support.select(None, RecordingClient(LupAgentOptions(model="probe"), []))


# ── the implementation's own registry ──────────────────────


def test_missing_registry_reads_as_empty(support: ClaudeProfileSupport) -> None:
    assert not support.registry_path.exists()
    assert support.load_registry().profiles == {}
    assert support.active_profile() is None
    assert support.resolve_config_dir() == DEFAULT_CONFIG_DIR


def test_first_added_profile_becomes_active(
    support: ClaudeProfileSupport, tmp_path: Path
) -> None:
    support.add_profile("work", tmp_path / "work-config")
    assert support.active_profile() == "work"

    support.add_profile("personal", tmp_path / "personal-config")
    # A later addition must not steal the active selection.
    assert support.active_profile() == "work"
    assert sorted(support.load_registry().profiles) == ["personal", "work"]


def test_registry_round_trips_through_disk(
    support: ClaudeProfileSupport, tmp_path: Path
) -> None:
    support.add_profile("work", tmp_path / "cfg")
    assert support.registry_path.exists()
    # A fresh instance on the same path sees the same state (no in-memory cache).
    reloaded = ClaudeProfileSupport(registry_path=support.registry_path)
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
    support = ClaudeProfileSupport(registry_path=registry_path)

    assert support.resolve_config_dir() == tmp_path / "work-config"

    support.add_profile("personal", tmp_path / "personal-config")
    on_disk = json.loads(registry_path.read_text())
    assert on_disk["active"] == "work"
    assert on_disk["profiles"]["work"] == {"config_dir": str(tmp_path / "work-config")}
    assert on_disk["profiles"]["personal"] == {
        "config_dir": str(tmp_path / "personal-config")
    }


def test_set_active_switches_and_rejects_unknown(
    support: ClaudeProfileSupport, tmp_path: Path
) -> None:
    support.add_profile("a", tmp_path / "a")
    support.add_profile("b", tmp_path / "b")

    support.set_active("b")
    assert support.active_profile() == "b"

    with pytest.raises(KeyError):
        support.set_active("ghost")
    assert support.active_profile() == "b"


def test_remove_clears_active_only_for_the_removed_profile(
    support: ClaudeProfileSupport, tmp_path: Path
) -> None:
    support.add_profile("a", tmp_path / "a")
    support.add_profile("b", tmp_path / "b")

    support.remove_profile("b")  # not active: selection untouched
    assert support.active_profile() == "a"
    assert sorted(support.load_registry().profiles) == ["a"]

    support.remove_profile("a")  # active: selection cleared
    assert support.active_profile() is None
    assert support.load_registry().profiles == {}

    support.remove_profile("never-existed")  # unknown: a no-op, not an error


def test_config_dir_for_expands_user_and_rejects_unknown(
    support: ClaudeProfileSupport,
) -> None:
    support.add_profile("home", Path("~/claude-home"))
    assert support.config_dir_for("home") == Path.home() / "claude-home"

    with pytest.raises(KeyError):
        support.config_dir_for("ghost")


def test_resolve_config_dir_prefers_name_then_active_then_default(
    support: ClaudeProfileSupport, tmp_path: Path
) -> None:
    assert support.resolve_config_dir() == DEFAULT_CONFIG_DIR

    support.add_profile("a", tmp_path / "a")
    support.add_profile("b", tmp_path / "b")
    assert support.resolve_config_dir() == tmp_path / "a"  # active
    assert support.resolve_config_dir("b") == tmp_path / "b"  # explicit wins

    support.remove_profile("a")
    assert support.resolve_config_dir() == DEFAULT_CONFIG_DIR
