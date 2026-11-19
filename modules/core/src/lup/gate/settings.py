"""What the gate reads of the environment it runs in, each variable a field."""

from pathlib import Path

from pydantic import Field

from lup.types import Settings


class GateSettings(Settings):
    """The environment variables the gate reads."""

    xdg_config_home: Path = Field(default_factory=lambda: Path.home() / ".config")
    """The operator's configuration directory, where the machine's layer of the
    declaration is (`lup.declaration.layout.MachineLayout`), which a pass is
    keyed on."""
