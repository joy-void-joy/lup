"""The neutral profile registry: ``name -> config dir`` plus the active pick.

Stored machine-wide in ``~/.lup/profiles.json`` because accounts are
reused across projects. What a config dir *means* is the per-backend half
— see :class:`~lup.adapters.profiles.Profiles.ProfileSupport`.
"""

import json
from pathlib import Path
from typing import TypedDict, cast

REGISTRY_PATH = Path.home() / ".lup" / "profiles.json"


# lup: Yeah, this really doesn't work
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
