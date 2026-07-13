"""Claude account profiles: whole config-dir homes, selected per client.

The Claude runner reads its entire home — login/credentials, settings,
history, plugin registry — from ``CLAUDE_CONFIG_DIR``, defaulting to
``~/.claude``. :meth:`ClaudeProfile.select` rebinds an already-built
Claude client onto the chosen account's home, resolving explicit name >
active profile > default over the registry store
(:mod:`lup.adapters.profiles.claude.store`).
"""

import copy
from pathlib import Path

from lup.adapters.clients.Client import Client
from lup.adapters.profiles.claude.store import ProfileStore
from lup.adapters.profiles.Profile import Profile

DEFAULT_CONFIG_DIR = Path.home() / ".claude"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"


class ClaudeProfile(Profile):
    """Claude's profile implementation: selection over the registry store.

    Args:
        store: The registry store names resolve against — the
            machine-wide document by default.
    """

    def __init__(self, store: ProfileStore | None = None) -> None:
        self.store = store if store is not None else ProfileStore()

    def select(self, name: str | None, client: Client) -> Client:
        """Return *client* running as the named account.

        The Claude runner subprocess picks its home from
        ``CLAUDE_CONFIG_DIR``, so selection is an env rebind: the
        returned client is the Claude composition rebuilt around native
        options that carry the resolved dir; the given client is left
        untouched.
        """
        from lup.adapters.clients.claude.create import compose_claude
        from lup.adapters.clients.claude.sessions import ClaudeSessions
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
                    "ClaudeProfile selects accounts on clients composed "
                    f"from Claude sessions; got {type(client).__name__}"
                )

    def resolve_config_dir(self, name: str | None = None) -> Path:
        """Resolve a config dir: explicit name > active profile > default."""
        chosen = name or self.store.active_profile()
        if chosen is None:
            return DEFAULT_CONFIG_DIR
        return self.store.config_dir_for(chosen)
