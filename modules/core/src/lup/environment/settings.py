"""What lup reads of the environment it runs in, each variable a field."""

from pathlib import Path

from pydantic import Field

from lup.types import Settings


class LupSettings(Settings):
    """The environment variables lup reads."""

    xdg_config_home: Path = Field(default_factory=lambda: Path.home() / ".config")
    """The operator's configuration directory, where the machine's layer is
    (`lup.environment.layout.MachineLayout`)."""
    lup_calling: Path | None = None
    """The socket of lup's program on the operator's machine, which a room's
    command line, and the operator's, call through: who calls is that
    socket's word. None to answer in this process, over the declaration of
    the worktree it runs in."""
