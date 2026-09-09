# lup: ignore[constant-declaration]
# The directory names here are where every worktree of one repository writes
# one DAG. Two processes that spelled them differently would keep two
# ledgers, so they are an identity of this layout rather than a caller's
# choice.
"""Where one repository's notes live, and the one decision a project makes about it.

Two placements, one store. **Shared** is the default: the log sits under the
git directory every worktree of one clone resolves to, outside all of them,
so a branch cannot change what a reader sees and removing a worktree does not
take the notes with it. That is the whole answer to a ledger that forks — the
repository this came from kept eight copies in eight worktrees and reconciled
them with a script that dropped every modification. **In the tree** is the
option: the log sits inside the worktree, travels with commits, is reviewed
in a diff, and is the same on every machine. Every worktree then holds a
copy, and what makes that viable is the shape already chosen — append-only
lines with unique ids — so two branches appending is exactly what git's own
``union`` merge resolves losslessly, and a read folds any duplicate by id.

The placement is a declaration in the project's code rather than a path a
worktree could be configured with, so two checkouts of one branch cannot be
set differently: the code that says where the log is travels with the tree
that reads it. :mod:`lup.coordination` keeps its roster under the git
directory whichever is chosen, because a roster is about the live sessions
on this machine and nothing else.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

import sh
from pydantic import BaseModel

from lup.execution.shell import git
from lup.workspace.edition import shared_git_directory

STORE_DIR = "lup"
LEDGER_DIR = "ledger"
JOURNAL_FILE = "journal.jsonl"
BLOBS_DIR = "blobs"


class LedgerPlacement(BaseModel, ABC, frozen=True):
    """Where a repository keeps its log; each placement answers for its consequences."""

    kind: str

    @abstractmethod
    def root(self, project: Path) -> Path:
        """The directory this project's log and blobs live under, given its tree."""

    @abstractmethod
    def tracked(self) -> bool:
        """Whether the log is committed with the code, and so the same everywhere.

        What two things downstream turn on: a document rendered from the log
        can be drift-checked only where every machine renders the same one,
        and a snapshot branch is worth taking only where nothing else keeps
        the log.
        """

    @abstractmethod
    def problems(self, project: Path) -> list[str]:
        """What this checkout lacks for the placement to hold, in the words to fix it."""

    @abstractmethod
    def describe(self) -> str:
        """Where the log is, as the gate's row reads it."""


class SharedStore(LedgerPlacement, frozen=True):
    """Under the git directory every worktree shares: one log, and no seam to get wrong."""

    kind: Literal["shared"] = "shared"

    def root(self, project: Path) -> Path:
        return shared_git_directory(project) / STORE_DIR / LEDGER_DIR

    def tracked(self) -> bool:
        return False

    def problems(self, project: Path) -> list[str]:
        del project
        return []

    def describe(self) -> str:
        return "shared under the git directory"


class InTree(LedgerPlacement, frozen=True):
    """Inside the worktree, committed with the code and merged by union.

    ``path`` is relative to the working tree. The journal has to be declared
    ``merge=union`` in ``.gitattributes`` — git's own driver, needing no
    per-clone registration — so two branches that both appended keep both
    sides; :meth:`problems` says so where it is not. A forge merging on its
    server reads no attributes, so there the same two branches show a
    conflict, resolved by taking both sides. Blobs are content-addressed and
    never conflict.
    """

    kind: Literal["in-tree"] = "in-tree"
    path: Path = Path(LEDGER_DIR)

    def root(self, project: Path) -> Path:
        return project / self.path

    def tracked(self) -> bool:
        return True

    def journal(self) -> Path:
        """The journal's path relative to the tree, which the attribute names."""
        return self.path / JOURNAL_FILE

    def problems(self, project: Path) -> list[str]:
        spelled = self.journal().as_posix()
        if merges_by_union(project, self.journal()):
            return []
        return [
            f"{spelled} is not declared `merge=union`; add "
            f'"{spelled} merge=union" to .gitattributes, so two branches that '
            "both appended merge losslessly"
        ]

    def describe(self) -> str:
        return f"in the tree at {self.path.as_posix()}/, journal merged by union"


def merges_by_union(project: Path, path: Path) -> bool:
    """Whether git resolves the ``union`` merge driver for one path in this checkout.

    Asked of git rather than read from ``.gitattributes``, because git is the
    reader whose answer matters and more than one file in a tree may set it.
    ``-z`` frames the answer as NUL-terminated fields — path, attribute, value
    — so the one answer that satisfies is a whole string to compare against,
    and nothing is parsed. Outside a repository there is no answer, which
    reads as undeclared.
    """
    try:
        framed = str(
            git("check-attr", "-z", "merge", "--", path.as_posix(), _cwd=str(project))
        )
    except sh.ErrorReturnCode:
        return False
    return framed == f"{path.as_posix()}\0merge\0union\0"


def ledger_root(root: Path, placement: LedgerPlacement = SharedStore()) -> Path:
    """The directory *root*'s repository records into, under the placement it declared.

    A path in no repository answers for itself through
    :func:`~lup.workspace.edition.shared_git_directory`, so a caller outside a
    clone gets somewhere to write rather than an exception about git.
    """
    return placement.root(root)
