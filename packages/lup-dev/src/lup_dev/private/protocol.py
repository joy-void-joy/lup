"""The gate's request for values never published, from a room, and the host's answer.

`docs/private.md`, *The gate's `private` step*. A room never sees the list, so the gate's
`private` step there sends the host each file it would check, whole, and the
commit `HEAD` names, on the launch's request socket; the `Private` module's
handler answers on the host (`lup_dev.private.scanning`) with each kind and
place, never a value.
"""

import base64
from typing import Literal

from lup.types import Model
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.publishing import Refusal


class Sent(Model):
    """One file the gate checks: its path from the worktree's root, and its content, as base64 so a file that isn't text crosses JSON whole."""

    path: str
    encoded: str
    """The content, in base64."""

    @classmethod
    def of(cls, path: str, content: bytes) -> Sent:
        r"""Send `content`, at `path`.

        >>> Sent.of("a.bin", b"\x00a").content()
        b'\x00a'
        """
        return cls(path=path, encoded=base64.b64encode(content).decode())

    def content(self) -> bytes:
        """Return the content, decoded."""
        return base64.b64decode(self.encoded, validate=True)


class Scanning(Request, reads=True):
    """Ask the host for every value never published in these files, and in the commits `head` reaches that the remotes lack."""

    kind: Literal["private-scan"] = "private-scan"
    files: list[Sent]
    head: str | None = None
    """The commit `HEAD` names, whose commits the remotes lack are read too;
    none before the first commit."""


class Scanned(Reply):
    """What the host found, each by its kind and place, and what it couldn't read."""

    kind: Literal["private-scanned"] = "private-scanned"
    found: list[Refusal] = []
    """Each value found: its kind, its place, and how it's written instead."""
    commits: int = 0
    """How many commits were read."""
    unchecked: str | None = None
    """Why something wasn't read, where it wasn't: no launch approved on the
    machine, or a remote that couldn't be listed. The gate passes."""
    unbuilt: str | None = None
    """Why the list couldn't be built on the host, where none was kept. The
    gate fails."""
