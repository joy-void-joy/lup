"""Named config-dir profiles (accounts), shared across repos.

A profile maps a name to a backend config dir — a complete account home:
its own login/credentials, settings, history, and plugin registry.
Selecting a profile decides which account a backend's runner launches as
and which account usage reporting reads.

This module is the neutral half: the registry stores only ``name ->
config dir`` and the active selection, machine-wide in
``~/.lup/profiles.json`` because accounts are reused across projects. What
a config dir *means* — where a backend's home lives by default, and the
env var that points its runner at a chosen one — is a per-backend
property supplied by a :class:`ProfileSupport` implementation beside this
module (e.g. :mod:`lup.adapters.profiles.claude`). A backend without a
``ProfileSupport`` simply has no profile capability.
"""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypedDict, cast

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


class ProfileSupport(ABC):
    """A backend's account-profile capability.

    The registry above is neutral; a subclass supplies the one
    backend-specific piece: where the account home lives when nothing is
    selected (:attr:`default_config_dir`). The env var that points a
    runner at a chosen dir is a constant beside the subclass (e.g.
    ``lup.adapters.profiles.claude.CONFIG_DIR_ENV``).
    """
    #lup: This ABC seems too strict. The fact that there isn't any codex.py is a sign that there is a problem, no?

    @property
    @abstractmethod
    def default_config_dir(self) -> Path:
        """The account home used when no profile is selected."""

    def resolve_config_dir(self, name: str | None = None) -> Path:
        """Resolve a config dir: explicit name > active profile > default."""
        chosen = name or active_profile()
        if chosen is None:
            return self.default_config_dir
        return config_dir_for(chosen)
