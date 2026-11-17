"""What lup reads of the environment it runs in, each variable a field."""

from pathlib import Path

from pydantic import Field

from lup.types import Settings


class LupSettings(Settings):
    """The environment variables lup reads."""

    xdg_config_home: Path = Field(default_factory=lambda: Path.home() / ".config")
    """The operator's configuration directory, where the machine's layer is
    (`lup.environment.layout.MachineLayout`)."""
