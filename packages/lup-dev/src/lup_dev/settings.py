"""The environment variables `lup_dev` reads, as settings models.

Each field is one variable, named after it (`docs/conventions.md`, *Constants*), so
this is the one place that says which variables `lup_dev` reads: its own, and the
terminal's, which a room passes through. The variables a runtime sets in the
commands it runs are that runtime's wire spellings, and live in its adapter
(`lup_dev.adapters`).
"""

from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import NoDecode

from lup.types import Settings

type Address = IPv4Address | IPv6Address
"""An address of this machine's, as `LUP_DASHBOARD_ADDRESSES` names them."""


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
    xdg_config_home: Path | None = None
    """`XDG_CONFIG_HOME`, where a user's own configuration lives, their profiles among it; `layout.py` says the default."""
    wayland_display: str | None = None
    """`WAYLAND_DISPLAY`: the Wayland session the host service runs in, whose clipboard rooms reach (`clipboard/desktop.py`)."""
    display: str | None = None
    """`DISPLAY`: the X session the host service runs in, where there's no Wayland one."""
    lup_dashboard_port: int = 8766
    """`LUP_DASHBOARD_PORT`: the port the dashboard listens on, on localhost
    (`host/dashboard.py`); the same at each start, so a page left open finds it again."""
    lup_dashboard_addresses: Annotated[list[Address], NoDecode] = []
    """`LUP_DASHBOARD_ADDRESSES`: the addresses the dashboard listens on beyond
    localhost, separated by spaces (`10.8.0.2 fd00::2`), each one of this
    machine's, its WireGuard address among them: what another device reaches it
    at (`docs/dashboard.md`, *Access*). Each is named outright: `0.0.0.0` is
    refused, since it would offer the dashboard on every network the machine
    joins, a café's among them, with the token as its only wall.
    """
    lup_engine_idle: timedelta = timedelta(minutes=15)
    """`LUP_ENGINE_IDLE`: how long a worktree's engine waits unasked before it stops.

    As ISO 8601 (`PT30M`) or `HH:MM:SS`. A stopped engine starts again when asked,
    reloading the project; a running one holds pyright's whole program in memory.
    """
    lup_environments: Path | None = None
    """`LUP_ENVIRONMENTS`: in a room, its launch's own environments, one per
    worktree, which lup's `uv` names to uv there and the room's engine reads
    (`lup_dev/environments.py`); unset on the host."""
    lup_room_pyright: Path | None = None
    """`LUP_ROOM_PYRIGHT`: in a room whose image carries pyright's source, the
    project's rooms' directory where the engine's build fetches a release the
    image doesn't carry (`lup_dev/pyright_source.py`); unset on the host, whose
    build reads its own cache alone."""
    lup_integration_branch: str = "dev"
    """`LUP_INTEGRATION_BRANCH`: the branch whose tip holds what the host runs, and the declaration judged by.

    Trust on launch approves the host zone at its tip, and once a commit is
    approved, every worktree of the repository is judged by the declaration
    committed there; before any approval, by the declaration at the tip, so a
    branch's edits to it take effect when they land there. A repository without
    the branch is judged by the declaration each worktree's `HEAD` commit holds.
    """

    @field_validator("lup_dashboard_addresses", mode="before")
    @classmethod
    def separated(cls, value: str | list[Address]) -> list[str] | list[Address]:
        """Read the variable's addresses, one per word, as the environment gives them in one string."""
        return value.split() if isinstance(value, str) else value

    @field_validator("lup_dashboard_addresses")
    @classmethod
    def outright(cls, addresses: list[Address]) -> list[Address]:
        """Refuse an address standing for every one this machine has, or for localhost, which is always bound.

        >>> LupDevSettings(lup_dashboard_addresses="10.8.0.2 fd00::2").lup_dashboard_addresses
        [IPv4Address('10.8.0.2'), IPv6Address('fd00::2')]
        """
        for each in addresses:
            if each.is_unspecified:
                message = (
                    f"`{each}` would offer the dashboard on every network this machine "
                    "joins, with the token as its only wall: name each address it "
                    "listens on, as its WireGuard one"
                )
                raise ValueError(message)
            if each.is_loopback:
                message = (
                    f"`{each}` is localhost, which the dashboard always listens on"
                )
                raise ValueError(message)
        return addresses


class TerminalVariables(Settings):
    """The terminal's variables a room passes through as they are, one field per variable.

    A room's session lost their colour, their locale, their time zone and Ctrl+G until
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
    """`EDITOR`: the editor Ctrl+G opens where `VISUAL` names none."""
    visual: str | None = None
    """`VISUAL`: the editor for a full screen, which Ctrl+G and most programs prefer to `EDITOR`."""

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
