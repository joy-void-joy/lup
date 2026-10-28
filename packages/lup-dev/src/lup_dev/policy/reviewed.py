"""What the operator reviewed: each file of a branch they marked reviewed in its agent's "since you approved" drawer, at the version they read, as the judge's review marks.

`docs/dashboard.md`, *The drawers*. Space `d` on a file of the drawer marks it
reviewed at the version the page shows, whether or not anything flagged it, as
a forge's "viewed" box is ticked, and so does a comment sent on its lines, at
the version it was written on: the drawer then shows the file as one line,
until the agent writes it again, when it shows only what changed since that
version (`lup_dev.policy.since`); a hold at landing starts there too
(`Baseline`, `lup_dev.policy.landing`).

A mark is the judge's review mark of the file (`lup_dev.inbox.marks`), keyed
by its branch and path (`FileKey`), whichever view shows it, the latest alone,
saying the version reviewed, in the store the core keeps in lup's state on the
host, which no room mounts, so an agent can't mark its own work reviewed. Each
version marked is kept beside the marks by git's id for it, its bytes as they
were, so a later diff reads it whatever became of the worktree's store: a
snapshot there is no ref's, and the store goes with its worktree. A version,
once written, never changes.

Before the store held them, each branch's marks were a file of their own
(`ReviewedLayout.branch`). They're carried into the store once, the first time
the judge's marks are read (`Reviews.kept`), and left as they are, since an
older copy of lup still reads them.
"""

import hashlib
from datetime import datetime
from pathlib import Path

from lup.types import Model, MutableModel
from lup_dev.inbox.marks import MarkStore, ModuleMarks, ReviewMark
from lup_dev.layout import Layout, ReviewedLayout
from lup_dev.stored import read_model

JUDGE = "judge"
"""The module whose review marks a file's are: the judge's, whose drawer shows
the file."""
CARRIED = "reviewed branches"
"""The older store of each branch's marks, by the name the judge's marks record
carrying it under (`ModuleMarks.carried`)."""


class FileKey(Model):
    """What a mark of the judge's is on: a file of a branch, by its path from the worktree's root."""

    branch: str
    path: Path


class Mark(Model):
    """One file the operator marked reviewed: its path, the version they reviewed, and when."""

    path: Path
    """From the worktree's root."""
    version: str | None
    """git's id for the content they reviewed; none where they reviewed its
    deletion."""
    at: datetime

    def keyed(self, branch: str) -> ReviewMark:
        """Return it as the judge's review mark of its file on `branch`."""
        key = FileKey(branch=branch, path=self.path).model_dump(mode="json")
        return ReviewMark(key=key, up_to=self.version, at=self.at)


class Marks(Model):
    """The files of one branch the operator marked reviewed, each at the version they reviewed last."""

    branch: str
    files: list[Mark] = []

    def of(self, path: Path) -> Mark | None:
        """Return the mark on the file at `path`; none where they never marked it."""
        return next((each for each in self.files if each.path == path), None)


class Reviews(MutableModel):
    """The marks of one repository's branches, the judge's in the store the core keeps on the host, read once for as long as one reading lasts."""

    layout: ReviewedLayout
    """Where each version marked is kept, and where each branch's marks were
    before the store held them."""
    store: MarkStore
    held: ModuleMarks | None = None
    """The judge's marks as first read, or as last marked here; none until
    then."""

    @classmethod
    def of(cls, layout: Layout, repository: Path) -> Reviews:
        """Return the marks of the repository whose git directory is `repository`, as lup's state at `layout` keeps them."""
        return cls(
            layout=layout.reviewed(repository),
            store=MarkStore(layout=layout.marks(repository)),
        )

    def kept(self) -> ModuleMarks:
        """Return the judge's marks of the repository, read once, each branch's of the older store carried in first where they never were."""
        if self.held is None:
            self.held = self.store.carried(JUDGE, CARRIED, self.older)
        return self.held

    def older(self) -> list[ReviewMark]:
        """Return the marks each branch's file of the older store holds, as the judge's review marks."""
        found = sorted(self.layout.branches.glob("*.json"))
        branches = [marks for each in found if (marks := read_model(each, Marks))]
        return [each.keyed(marks.branch) for marks in branches for each in marks.files]

    def marks(self, branch: str) -> Marks:
        """Return the marks on `branch`; none made, where nothing is kept."""
        files = [
            Mark(path=key.path, version=each.up_to, at=each.at)
            for each in self.kept().marks
            if (key := FileKey.model_validate(each.key)).branch == branch
        ]
        return Marks(branch=branch, files=files)

    def stamp(self, branch: str) -> str:
        """Say the marks on `branch` in a few characters, which change as one is made: so a version read from them does."""
        kept = self.marks(branch).model_dump_json().encode()
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
        self.kept()
        self.held = self.store.moved(JUDGE, [each.keyed(branch) for each in marks])
        return self.marks(branch)

    def content(self, mark: Mark) -> bytes | None:
        """Return the bytes of the version `mark` reviewed; none where it reviewed a deletion, or they aren't kept."""
        if mark.version is None:
            return None
        kept = self.layout.version(mark.version)
        return kept.read_bytes() if kept.is_file() else None
