"""Personal Claude account registry used by concrete CLI composition roots."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from lup.adapters.claude.config import (
    ClaudeProfileRegistry,
    ClaudeProfileSelection,
)

REGISTRY_PATH = Path.home() / ".lup" / "profiles.json"


class Account(BaseModel):
    """One registered Claude configuration home."""

    model_config = ConfigDict(frozen=True)

    config_dir: str


class Registry(BaseModel):
    """Personal on-disk named account registry."""

    profiles: dict[str, Account] = Field(default_factory=dict)
    active: str | None = None


class ClaudeProfileStore:
    """Read and atomically update personal profile selections."""

    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self.registry_path = registry_path

    def load_registry(self) -> Registry:
        if not self.registry_path.exists():
            return Registry()
        return Registry.model_validate_json(
            self.registry_path.read_text(encoding="utf-8")
        )

    def save_registry(self, registry: Registry) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.registry_path.with_name(f".{self.registry_path.name}.tmp")
        temporary.write_text(
            registry.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.registry_path)  # lup: ignore[string-replace]

    def config_dir_for(self, name: str) -> Path:
        return Path(self.load_registry().profiles[name].config_dir).expanduser()

    def active_profile(self) -> str | None:
        return self.load_registry().active

    def add_profile(self, name: str, config_dir: Path) -> None:
        registry = self.load_registry()
        profiles = dict(registry.profiles)
        profiles[name] = Account(config_dir=str(config_dir))
        self.save_registry(
            registry.model_copy(
                update={
                    "profiles": profiles,
                    "active": registry.active or name,
                }
            )
        )

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
