"""Where Codex's adapter keeps what it stores: lup's own Codex home, beside the operator's.

Every ask runs Codex under a home of lup's own, `$XDG_STATE_HOME/lup/codex`, so the
operator's configuration, MCP servers, hooks, skills, `AGENTS.md` and history don't
reach a call from code. Its one link to the operator's home is their login:
`auth.json` in lup's home is a symbolic link to theirs (`$CODEX_HOME/auth.json`, or
`~/.codex/auth.json`). Codex rewrites that file in place, so a refresh writes through
the link to the one real copy, and logging out from lup's home removes only the link.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model

if TYPE_CHECKING:
    from lup.adapters.codex.settings import CodexSettings


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
