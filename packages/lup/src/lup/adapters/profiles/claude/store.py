"""The Claude profile registry: named accounts on disk.

The machine-wide ``name -> config dir`` registry
(``~/.lup/profiles.json``, shared across projects because accounts are)
and its CRUD. Selection composes this store
(:mod:`lup.adapters.profiles.claude.profile`); Claude-only devtools (the
setup wizard, the runner, usage reporting) call it directly — none of
that surface belongs to the seam contract.
"""

from pathlib import Path

from pydantic import BaseModel, Field

REGISTRY_PATH = Path.home() / ".lup" / "profiles.json"


class Account(BaseModel):
    """One registered account: the config dir the runner reads as its home."""

    config_dir: str


class Registry(BaseModel):
    """The registry document as stored on disk: named profiles plus the active pick."""

    profiles: dict[str, Account] = Field(default_factory=dict)
    active: str | None = None


class ProfileStore:
    """Reads and writes the registry document.

    Args:
        registry_path: Where the registry document lives — machine-wide
            by default, because accounts are reused across projects.
    """

    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self.registry_path = registry_path

    def load_registry(self) -> Registry:
        """Read the registry document; a missing file reads as empty."""
        if not self.registry_path.exists():
            return Registry()
        return Registry.model_validate_json(self.registry_path.read_text())

    def save_registry(self, registry: Registry) -> None:
        """Write the registry document, creating its directory if needed."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(registry.model_dump_json(indent=2) + "\n")

    def config_dir_for(self, name: str) -> Path:
        """Config dir for a named profile. Raises ``KeyError`` if unknown."""
        return Path(self.load_registry().profiles[name].config_dir).expanduser()

    def active_profile(self) -> str | None:
        """The name marked active, or ``None`` when nothing is selected."""
        return self.load_registry().active

    def add_profile(self, name: str, config_dir: Path) -> None:
        """Register a profile; the first one added becomes active."""
        registry = self.load_registry()
        registry.profiles[name] = Account(config_dir=str(config_dir))
        if registry.active is None:
            registry.active = name
        self.save_registry(registry)

    def set_active(self, name: str) -> None:
        """Mark a registered profile active. Raises ``KeyError`` if unknown."""
        registry = self.load_registry()
        if name not in registry.profiles:
            raise KeyError(name)
        registry.active = name
        self.save_registry(registry)

    def remove_profile(self, name: str) -> None:
        """Drop a profile; clears the active selection if it was the one removed."""
        registry = self.load_registry()
        registry.profiles.pop(name, None)
        if registry.active == name:
            registry.active = None
        self.save_registry(registry)
