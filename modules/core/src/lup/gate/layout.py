"""Where the gate keeps the passes it records.

A pass is kept in the repository's git directory, the one every worktree and
every room of the repository shares, so a pass one worktree recorded is found
by another holding the same files, a branch's landing among them.
"""

from pathlib import Path

from lup.types import Model


class GateLayout(Model):
    """Where a repository's gate keeps its passes: in the git directory every worktree shares."""

    common: Path
    """The repository's git directory every worktree shares."""

    @property
    def passes(self) -> Path:
        """The directory of the passes recorded, a file each, named by what it passed on."""
        return self.common / "lup" / "gate" / "passes"
