"""What the machine's parts read from the machine's own environment, as the loader handed it from the operator's terminal."""

from pathlib import Path

from lup.types import Settings


class Lending(Settings):
    """What the machine lends a part holding it from its own environment: the operator's SSH agent."""

    ssh_auth_sock: Path | None = None
    """The operator's SSH agent's socket, where one runs: bound into the
    container of a part holding it (`SshAgent`)."""
