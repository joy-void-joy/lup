"""The environment variables `lup_dev` reads, as one settings model.

Each field is one variable, named after it (`docs/conventions.md`, *Constants*), so
this is the one place that says which variables `lup_dev` reads. The variables a
runtime sets in the commands it runs are that runtime's wire spellings, and live in
its adapter (`lup_dev.adapters`).
"""

from pathlib import Path

from lup.types import Settings


class LupDevSettings(Settings):
    """The environment variables `lup_dev` reads, one field per variable."""

    xdg_state_home: Path | None = None
    """`XDG_STATE_HOME`, where per-user state lives; `layout.py` says the default."""
