"""The environment variables Codex's adapter reads, as one settings model.

Each field is one variable, named after it (`docs/conventions.md`, *Constants*), so
this is the one place that says which variables the adapter reads. Where each
points by default is `layout.py`'s.
"""

from pathlib import Path

from lup.types import Settings


class CodexSettings(Settings):
    """The environment variables Codex's adapter reads, one field per variable."""

    codex_home: Path | None = None
    """`CODEX_HOME`, the operator's own Codex home, which holds their login."""
    xdg_state_home: Path | None = None
    """`XDG_STATE_HOME`, where per-user state lives, lup's own Codex home among it."""
