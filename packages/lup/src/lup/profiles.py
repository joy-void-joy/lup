"""Named Claude config-dir profiles (accounts), shared across repos.

A profile maps a name to a Claude Code config dir — the ``CLAUDE_CONFIG_DIR``
target, which is a complete Claude home: its own login/credentials,
settings, history, and plugin registry. Selecting a profile decides which
account the ``claude`` runner launches as and which account ``usage``
reports on.

The registry is machine-wide (``~/.lup/profiles.json``) because accounts
are reused across projects; the active selection lives there too.
``resolve_config_dir`` picks a dir in this order: an explicit profile
name, else the active profile, else the default ``~/.claude``.
"""

import json
from pathlib import Path
from typing import TypedDict, cast

DEFAULT_CONFIG_DIR = Path.home() / ".claude"
REGISTRY_PATH = Path.home() / ".lup" / "profiles.json"


class Profile(TypedDict):
    config_dir: str


class Registry(TypedDict, total=False):
    profiles: dict[str, Profile]
    active: str | None


def load_registry() -> Registry:
    if not REGISTRY_PATH.exists():
        return Registry(profiles={}, active=None)
    return cast(Registry, json.loads(REGISTRY_PATH.read_text()))


def save_registry(registry: Registry) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2) + "\n")


def profiles() -> dict[str, Profile]:
    return load_registry().get("profiles") or {}


def active_profile() -> str | None:
    return load_registry().get("active")


def config_dir_for(name: str) -> Path:
    """Config dir for a named profile. Raises ``KeyError`` if unknown."""
    profs = profiles()
    if name not in profs:
        raise KeyError(name)
    return Path(profs[name]["config_dir"]).expanduser()


def resolve_config_dir(name: str | None = None) -> Path:
    """Resolve a Claude config dir: explicit name > active profile > ~/.claude."""
    chosen = name or active_profile()
    if chosen is None:
        return DEFAULT_CONFIG_DIR
    return config_dir_for(chosen)


def add_profile(name: str, config_dir: Path) -> None:
    """Register a profile; the first one added becomes active."""
    registry = load_registry()
    profs = registry.get("profiles") or {}
    profs[name] = {"config_dir": str(config_dir)}
    registry["profiles"] = profs
    if registry.get("active") is None:
        registry["active"] = name
    save_registry(registry)


def set_active(name: str) -> None:
    """Mark a registered profile active. Raises ``KeyError`` if unknown."""
    registry = load_registry()
    if name not in (registry.get("profiles") or {}):
        raise KeyError(name)
    registry["active"] = name
    save_registry(registry)


def remove_profile(name: str) -> None:
    """Drop a profile; clears the active selection if it was the one removed."""
    registry = load_registry()
    profs = registry.get("profiles") or {}
    profs.pop(name, None)
    registry["profiles"] = profs
    if registry.get("active") == name:
        registry["active"] = None
    save_registry(registry)
