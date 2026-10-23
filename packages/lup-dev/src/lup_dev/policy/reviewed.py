"""What the operator reviewed: each file of a branch they marked reviewed in its agent's "since you approved" drawer, at the version they read.

`docs/dashboard.md`, *The drawers*. Space `a` on a file of the drawer marks it
reviewed at the version the page shows, whether or not anything flagged it, as
a forge's "viewed" box is ticked: the drawer then shows the file as one line,
until the agent writes it again, when it shows only what changed since that
version (`lup_dev.policy.since`); a hold at landing starts there too
(`Baseline`, `lup_dev.policy.landing`).

A mark is kept per repository, branch and path, the latest alone (`Marks`), in
lup's state on the host (`ReviewedLayout`), which no room mounts, so an agent
can't mark its own work reviewed. Each version marked is kept beside the marks
by git's id for it, its bytes as they were, so a later diff reads it whatever
became of the worktree's store: a snapshot there is no ref's, and the store
goes with its worktree. A branch's marks are one file, replaced whole; a
version, once written, never changes.
"""

import hashlib
from datetime import datetime
from pathlib import Path

from lup.types import Model
from lup_dev.layout import ReviewedLayout
from lup_dev.stored import read_model, write_model


class Mark(Model):
    """One file the operator marked reviewed: its path, the version they reviewed, and when."""

    path: Path
    """From the worktree's root."""
    version: str | None
    """git's id for the content they reviewed; none where they reviewed its
    deletion."""
    at: datetime


class Marks(Model):
    """The files of one branch the operator marked reviewed, each at the version they reviewed last."""

    branch: str
    files: list[Mark] = []

    def of(self, path: Path) -> Mark | None:
        """Return the mark on the file at `path`; none where they never marked it."""
        return next((each for each in self.files if each.path == path), None)


class Reviews(Model):
    """The marks of one repository's branches, kept in lup's state on the host."""

    layout: ReviewedLayout

    def marks(self, branch: str) -> Marks:
        """Return the marks on `branch`; none made, where nothing is kept."""
        return read_model(self.layout.branch(branch), Marks) or Marks(branch=branch)

    def stamp(self, branch: str) -> str:
        """Say the marks on `branch` in a few characters, which change as one is made: so a version read from them does."""
        found = self.layout.branch(branch)
        kept = found.read_bytes() if found.is_file() else b""
        return hashlib.blake2b(kept, digest_size=6).hexdigest()

    def marked(
        self, branch: str, marks: list[Mark], contents: dict[str, bytes]
    ) -> Marks:
        """Keep `marks` on `branch`, each in place of the one on its file, and each version's bytes in `contents`, by git's id for it; return the branch's marks."""
        for version, content in contents.items():
            kept = self.layout.version(version)
            if not kept.is_file():
                kept.parent.mkdir(parents=True, exist_ok=True)
                partial = kept.with_name(f"{version}.partial")
                partial.write_bytes(content)
                partial.replace(kept)
        # Each file's latest mark, in the order its first was made.
        latest = {each.path: each for each in [*self.marks(branch).files, *marks]}
        after = Marks(branch=branch, files=list(latest.values()))
        write_model(self.layout.branch(branch), after)
        return after

    def content(self, mark: Mark) -> bytes | None:
        """Return the bytes of the version `mark` reviewed; none where it reviewed a deletion, or they aren't kept."""
        if mark.version is None:
            return None
        kept = self.layout.version(mark.version)
        return kept.read_bytes() if kept.is_file() else None
