"""The environment variables `lup_dev` reads, as one settings model.

Each field is one variable, named after it (`docs/conventions.md`, *Constants*), so
this is the one place that says which variables `lup_dev` reads. The variables a
runtime sets in the commands it runs are that runtime's wire spellings, and live in
its adapter (`lup_dev.adapters`).
"""

from datetime import timedelta
from pathlib import Path

from lup.types import Settings


class LupDevSettings(Settings):
    """The environment variables `lup_dev` reads, one field per variable."""

    xdg_state_home: Path | None = None
    """`XDG_STATE_HOME`, where per-user state lives; `layout.py` says the default."""
    xdg_runtime_dir: Path | None = None
    """`XDG_RUNTIME_DIR`, where per-user sockets live; `layout.py` says the default."""
    lup_engine_idle: timedelta = timedelta(minutes=15)
    """`LUP_ENGINE_IDLE`: how long a worktree's engine waits unasked before it stops.

    As ISO 8601 (`PT30M`) or `HH:MM:SS`. A stopped engine starts again when asked,
    reloading the project; a running one holds pyright's whole program in memory.
    """
    lup_interim_review_legacy_checkout: Path = Path("lup-legacy.git/tree/dev")
    """`LUP_INTERIM_REVIEW_LEGACY_CHECKOUT`: the first lup's checkout, whose dashboard
    reviews the judge before `lup-dev install` installs it.

    Relative to the directory holding the repository's git directory, or absolute.
    The interim review hook reads the same variable the same way, so one setting
    points both at the first lup. It goes with the bridge.
    """
    lup_integration_branch: str = "dev"
    """`LUP_INTEGRATION_BRANCH`: the branch whose tip holds the declaration judged by.

    Every worktree of a repository is judged by the declaration committed at that
    branch's tip, so a branch's edits to it take effect when they land there. A
    repository without the branch is judged by the declaration each worktree's
    `HEAD` commit holds.
    """
