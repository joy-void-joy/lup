"""Claude account profiles: whole config-dir homes, selected per client.

The Claude runner reads its entire home — login/credentials, settings,
history, plugin registry — from ``CLAUDE_CONFIG_DIR``, defaulting to
``~/.claude``. Everything that fact implies is this implementation's own
concern and lives here: the machine-wide ``name -> config dir`` registry
(``~/.lup/profiles.json``, shared across projects because accounts are),
the resolve order (explicit name > active profile > default), and
:meth:`ClaudeProfileSupport.select`, which rebinds an already-built
Claude client onto the chosen account's home. Claude-only devtools (the
runner, usage reporting, profile CRUD) call this concrete class directly
— none of that surface belongs to the seam contract.
"""

import copy
from pathlib import Path

from pydantic import BaseModel, Field

from lup.adapters.clients.Client import Client
from lup.adapters.profiles.Profiles import ProfileSupport

DEFAULT_CONFIG_DIR = Path.home() / ".claude"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
REGISTRY_PATH = Path.home() / ".lup" / "profiles.json"


class Profile(BaseModel):
    """One registered account: the config dir the runner reads as its home."""

    config_dir: str


class Registry(BaseModel):
    """The registry document as stored on disk: named profiles plus the active pick."""

    profiles: dict[str, Profile] = Field(default_factory=dict)
    active: str | None = None


class ClaudeProfileSupport(ProfileSupport):
    """Claude's profile implementation, storage and resolution included.

    Args:
        registry_path: Where the registry document lives — machine-wide
            by default, because accounts are reused across projects.
    """

    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self.registry_path = registry_path

    def select(self, name: str | None, client: Client) -> Client:
        """Return *client* running as the named account.

        The Claude runner subprocess picks its home from
        ``CLAUDE_CONFIG_DIR``, so selection is an env rebind: the
        returned client is the Claude composition rebuilt around native
        options that carry the resolved dir; the given client is left
        untouched.
        """
        from lup.adapters.clients.claude.client import ClaudeSessions, compose_claude
        from lup.adapters.clients.composed import ComposedClient

        match client:
            case ComposedClient(sessions=ClaudeSessions() as sessions):
                native = copy.copy(sessions.options)
                native.env = {
                    **native.env,
                    CONFIG_DIR_ENV: str(self.resolve_config_dir(name)),
                }
                return compose_claude(native)
            case _:
                raise TypeError(
                    "ClaudeProfileSupport selects accounts on clients composed "
                    f"from Claude sessions; got {type(client).__name__}"
                )

    def resolve_config_dir(self, name: str | None = None) -> Path:
        """Resolve a config dir: explicit name > active profile > default."""
        chosen = name or self.load_registry().active
        if chosen is None:
            return DEFAULT_CONFIG_DIR
        return self.config_dir_for(chosen)

    def config_dir_for(self, name: str) -> Path:
        """Config dir for a named profile. Raises ``KeyError`` if unknown."""
        return Path(self.load_registry().profiles[name].config_dir).expanduser()

    def active_profile(self) -> str | None:
        """The name marked active, or ``None`` when nothing is selected."""
        return self.load_registry().active

    def load_registry(self) -> Registry:
        """Read the registry document; a missing file reads as empty."""
        if not self.registry_path.exists():
            return Registry()
        return Registry.model_validate_json(self.registry_path.read_text())

    def save_registry(self, registry: Registry) -> None:
        """Write the registry document, creating its directory if needed."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(registry.model_dump_json(indent=2) + "\n")

    def add_profile(self, name: str, config_dir: Path) -> None:
        """Register a profile; the first one added becomes active."""
        registry = self.load_registry()
        registry.profiles[name] = Profile(config_dir=str(config_dir))
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
