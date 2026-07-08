"""Named config-dir profiles (accounts), shared across repos.

A profile maps a name to a backend config dir — a complete account home:
its own login/credentials, settings, history, and plugin registry.
Selecting a profile decides which account a backend's runner launches as
and which account usage reporting reads.

This module is the per-backend half's contract: the neutral registry —
``name -> config dir`` and the active selection, machine-wide in
``~/.lup/profiles.json`` because accounts are reused across projects —
lives in :mod:`lup.adapters.profiles.store`. What a config dir *means* —
where a backend's home lives by default, and the env var that points its
runner at a chosen one — is a per-backend property supplied by a
:class:`ProfileSupport` implementation beside this module (e.g.
:mod:`lup.adapters.profiles.claude`). A backend without a
``ProfileSupport`` simply has no profile capability.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from lup.adapters.profiles.store import active_profile, config_dir_for


class ProfileSupport(ABC):
    """A backend's account-profile capability — opt-in, one impl by design.

    The registry (:mod:`lup.adapters.profiles.store`) is neutral; a
    subclass supplies the one
    backend-specific piece: where the account home lives when nothing is
    selected (:attr:`default_config_dir`). The env var that points a
    runner at a chosen dir is a constant beside the subclass (e.g.
    ``lup.adapters.profiles.claude.CONFIG_DIR_ENV``).

    Backends opt into this capability by implementing it rather than
    declaring a flag: a backend whose runner reads a whole account home
    from a config dir (Claude) provides a ``ProfileSupport`` module
    beside this one; a backend with no such home (e.g. Codex) has no
    profile capability and no module to write. A single implementation
    is thus the designed shape, and an absent one is a capability
    declined rather than a piece left unwritten.
    """

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
