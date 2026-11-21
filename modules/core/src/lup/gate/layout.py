"""Where the gate keeps the runs it records.

A run is kept in the repository's git directory, the one every worktree and
every room of the repository shares, so a pass one worktree recorded is found
by another holding the same files, a branch's landing among them, and what a
run said is read where the branch is reviewed.
"""

from pathlib import Path

from lup.types import Model


class GateLayout(Model):
    """Where a repository's gate keeps its runs: in the git directory every worktree shares."""

    common: Path
    """The repository's git directory every worktree shares."""

    @property
    def runs(self) -> Path:
        """The directory of the runs recorded, a file each, named by what it ran on: the last run on those files."""
        return self.common / "lup" / "gate" / "runs"
