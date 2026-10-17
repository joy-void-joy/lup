"""The environment variables `lup_dev` reads, as settings models.

Each field is one variable, named after it (`docs/conventions.md`, *Constants*), so
this is the one place that says which variables `lup_dev` reads: its own, and the
terminal's, which a room passes through. The variables a runtime sets in the
commands it runs are that runtime's wire spellings, and live in its adapter
(`lup_dev.adapters`).
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
    xdg_cache_home: Path | None = None
    """`XDG_CACHE_HOME`, where per-user caches, what can be fetched again, live; `layout.py` says the default."""
    xdg_data_home: Path | None = None
    """`XDG_DATA_HOME`, where per-user data lives, programs installed for the user among it; `layout.py` says the default."""
    lup_dashboard_port: int = 8766
    """`LUP_DASHBOARD_PORT`: the port the dashboard listens on, on localhost
    (`host/dashboard.py`); the same at each start, so a page left open finds it again."""
    lup_engine_idle: timedelta = timedelta(minutes=15)
    """`LUP_ENGINE_IDLE`: how long a worktree's engine waits unasked before it stops.

    As ISO 8601 (`PT30M`) or `HH:MM:SS`. A stopped engine starts again when asked,
    reloading the project; a running one holds pyright's whole program in memory.
    """
    lup_integration_branch: str = "dev"
    """`LUP_INTEGRATION_BRANCH`: the branch whose tip holds what the host runs, and the declaration judged by.

    Trust on launch approves the host zone at its tip, and once a commit is
    approved, every worktree of the repository is judged by the declaration
    committed there; before any approval, by the declaration at the tip, so a
    branch's edits to it take effect when they land there. A repository without
    the branch is judged by the declaration each worktree's `HEAD` commit holds.
    """


class TerminalVariables(Settings):
    """The terminal's variables a room passes through as they are, one field per variable.

    A room's session lost its colour, its locale, its time zone and Ctrl+G until
    these were passed (`docs/launch.md`, *The user, the process, the network*).
    Each is passed under its own name, the field's in capitals; one unset isn't
    passed.
    """

    term: str | None = None
    """`TERM`: the terminal's type."""
    colorterm: str | None = None
    """`COLORTERM`: the colours it shows."""
    lang: str | None = None
    """`LANG`: the locale."""
    tz: str | None = None
    """`TZ`: the time zone, where it's set beside `/etc/localtime`."""
    editor: str | None = None
    """`EDITOR`: the editor Ctrl+G opens."""
    visual: str | None = None
    """`VISUAL`: the editor for a full screen, which some programs prefer to `EDITOR`."""

    def passed(self) -> dict[str, str]:
        """Return each variable set, by its name, as a room sets it.

        >>> TerminalVariables(term="xterm-kitty", colorterm=None, lang=None,
        ...     tz=None, editor="nvim", visual=None).passed()
        {'TERM': 'xterm-kitty', 'EDITOR': 'nvim'}
        """
        return {
            name.upper(): value
            for name, value in self.model_dump(exclude_none=True).items()
        }
