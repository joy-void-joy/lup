"""Personal Claude account registry used by concrete CLI composition roots."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from lup.channels.models import publish_atomic
from lup.adapters.claude.config import (
    ClaudeProfileRegistry,
    ClaudeProfileSelection,
)
from lup.runtime.profiles import ProfileStore

REGISTRY_PATH = Path.home() / ".lup" / "profiles.json"


class Account(BaseModel):
    """One registered Claude configuration home."""

    model_config = ConfigDict(frozen=True)

    config_dir: str


class Registry(BaseModel):
    """Personal on-disk named account registry."""

    profiles: dict[str, Account] = Field(default_factory=dict)
    active: str | None = None


class ClaudeProfileStore(ProfileStore):
    """Read and atomically update personal profile selections.

    The origin for a project that keeps no accounts of its own: names are
    registered by hand and each carries wherever its home happens to live.
    """

    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self.registry_path = registry_path

    def homes_root(self) -> Path:
        """Where a profile registered without a home of its own is put.

        Beside the registry rather than under a fixed absolute path, so a
        store pointed at a scratch registry keeps its homes there too.
        """
        return self.registry_path.parent / "homes"

    def load_registry(self) -> Registry:
        if not self.registry_path.exists():
            return Registry()
        return Registry.model_validate_json(
            self.registry_path.read_text(encoding="utf-8")
        )

    def save_registry(self, registry: Registry) -> None:
        publish_atomic(self.registry_path, registry)

    def names(self) -> list[str]:
        return sorted(self.load_registry().profiles)

    def config_dir_for(self, name: str) -> Path:
        return Path(self.load_registry().profiles[name].config_dir).expanduser()

    def active_profile(self) -> str | None:
        return self.load_registry().active

    def add_profile(self, name: str, config_dir: Path | None = None) -> Path:
        home = config_dir if config_dir is not None else self.homes_root() / name
        registry = self.load_registry()
        profiles = dict(registry.profiles)
        profiles[name] = Account(config_dir=str(home))
        self.save_registry(
            registry.model_copy(
                update={
                    "profiles": profiles,
                    "active": registry.active or name,
                }
            )
        )
        return home.expanduser()

    def set_active(self, name: str) -> None:
        registry = self.load_registry()
        if name not in registry.profiles:
            raise KeyError(name)
        self.save_registry(registry.model_copy(update={"active": name}))

    def remove_profile(self, name: str) -> None:
        registry = self.load_registry()
        profiles = dict(registry.profiles)
        profiles.pop(name, None)
        self.save_registry(
            registry.model_copy(
                update={
                    "profiles": profiles,
                    "active": None if registry.active == name else registry.active,
                }
            )
        )

    def resolver_registry(self) -> ClaudeProfileRegistry:
        """Project personal storage into immutable runtime selection data."""
        registry = self.load_registry()
        return ClaudeProfileRegistry(
            profiles={
                name: ClaudeProfileSelection(
                    config_directory=Path(account.config_dir).expanduser()
                )
                for name, account in registry.profiles.items()
            },
            active=registry.active,
        )

    def resolve_config_dir(self, name: str | None = None) -> Path:
        """Resolve explicit, active, then default through the typed registry."""
        registry = self.resolver_registry()
        selected = name or registry.active
        if selected is None:
            return registry.default.config_directory
        try:
            return registry.profiles[selected].config_directory
        except KeyError as error:
            raise KeyError(f"unknown Claude profile {selected!r}") from error
