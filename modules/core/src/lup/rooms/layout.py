"""Where rooms' things are kept on the operator's machine, and where they land in a room.

The rooms' history homes and the accounts' logins are kept where the second lup
keeps them, under lup's data (`$XDG_DATA_HOME/lup`), so a login and a session's
history are the same for both: a session started under the second lup resumes
in this one.
"""

import hashlib
from pathlib import Path

import platformdirs
from pydantic import Field

from lup.types import Model


def digest(path: Path) -> str:
    """Name a directory by its absolute path, as a stable name, as the second lup names a project's home.

    >>> len(digest(Path("/work/lup")))
    64
    """
    return hashlib.sha256(str(path).encode()).hexdigest()


class Kept(Model):
    """What rooms share across sessions, kept on the operator's machine: each project's history home per runtime, and each account's logins."""

    data: Path = Field(default_factory=lambda: platformdirs.user_data_path("lup"))
    """lup's data, shared with the second lup."""

    def history(self, common: Path, runtime: str, *, shared: bool = False) -> Path:
        """Return where runtime `runtime`'s rooms keep their history for the repository whose git directory is `common`: its project's own, or the one every project shares where its profile says."""
        if shared:
            return self.data / "homes" / "shared" / runtime
        return self.data / "homes" / "projects" / digest(common) / runtime

    def login(self, account: str, runtime: str, name: str) -> Path:
        """Return where account `account` keeps its login for runtime `runtime`, the file the runtime's sign-in writes, named `name`."""
        return self.data / "accounts" / account / runtime / name


class InRoom(Model):
    """Where lup's own things land in every room."""

    sockets: Path = Path("/run/lup")
    """The room's directory of sockets: the machine's, and its holder's."""
    clis: Path = Path("/opt/lup/clis")
    """Each runtime's CLI, a directory each, read-only."""

    def calling(self) -> Path:
        """Return the socket the room calls the machine through."""
        return self.sockets / "calling.sock"

    def holder(self) -> Path:
        """Return the socket the room's first program connects its runtime to."""
        return self.sockets / "session.sock"

    def cli(self, runtime: str) -> Path:
        """Return where runtime `runtime`'s CLI is in the room."""
        return self.clis / runtime
