"""Where Codex's adapter keeps what it stores: lup's own Codex home, beside the operator's.

Every ask runs Codex under a home of lup's own, `$XDG_STATE_HOME/lup/codex`, so the
operator's configuration, MCP servers, hooks, skills, `AGENTS.md` and history don't
reach a call from code. Its one link to the operator's home is their login:
`auth.json` in lup's home is a symbolic link to theirs (`$CODEX_HOME/auth.json`, or
`~/.codex/auth.json`). Codex rewrites that file in place, so a refresh writes through
the link to the one real copy, and logging out from lup's home removes only the link.

A terminal session runs in the operator's own home instead, with the launch's
managed requirements, a file of the launch's own, mounted where Codex reads them.
"""

from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING

from lup.sessions.errors import RuntimeMissingError
from lup.types import Model

if TYPE_CHECKING:
    from lup.adapters.codex.settings import CodexSettings

MANAGED_REQUIREMENTS = Path("/etc/codex/requirements.toml")
"""Where Codex reads the system's requirements on Linux, managed hooks among them."""


class CodexLayout(Model):
    """lup's own Codex home, and the operator's, whose login it links to."""

    home: Path
    """lup's own Codex home: no configuration of its own, the operator's login linked in."""
    operator_home: Path
    """The operator's Codex home, where their login is kept."""

    @classmethod
    def of(cls, settings: CodexSettings) -> CodexLayout:
        """Place both homes where the settings say, or at their defaults."""
        state = settings.xdg_state_home or Path.home() / ".local" / "state"
        operator = settings.codex_home or Path.home() / ".codex"
        return cls(home=state / "lup" / "codex", operator_home=operator.absolute())

    @property
    def login(self) -> Path:
        """The login in lup's home: a link to the operator's."""
        return self.home / "auth.json"

    @property
    def operator_login(self) -> Path:
        """The operator's login, as Codex keeps it in a file."""
        return self.operator_home / "auth.json"

    @property
    def operator_config(self) -> Path:
        """The operator's own Codex configuration."""
        return self.operator_home / "config.toml"

    @property
    def bundled(self) -> Path:
        """The directory of the Codex CLI the SDK pins: the binary, and the helpers beside it."""
        found = find_spec("codex_cli_bin")
        origin = None if found is None else found.origin
        package = None if origin is None else Path(origin).parent
        if package is None or not (package / "bin" / "codex").is_file():
            message = (
                "the Codex CLI the SDK pins isn't installed: reinstall the "
                "`lup[codex]` extra, or give the CLI's path"
            )
            raise RuntimeMissingError(message)
        return package

    @property
    def bundled_cli(self) -> Path:
        """The Codex CLI the SDK pins, inside `bundled`."""
        return self.bundled / "bin" / "codex"


class CodexLaunch(Model):
    """The files a launch writes for Codex, in its own directory."""

    directory: Path

    @property
    def requirements(self) -> Path:
        """The launch's managed requirements: lup's hooks, and no others."""
        return self.directory / "requirements.toml"
