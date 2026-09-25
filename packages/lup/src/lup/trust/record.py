"""Where the launcher keeps what its operator approved, and what that record holds.

One directory per repository under the launcher's own state directory --
``$XDG_STATE_HOME/lup/trust/<repository>/``, ``~/.local/state`` where the
variable is unset -- holding the record of approvals, the object store the
approved snapshots live in, the relay the launch questions are asked through,
the exports a trusted launch runs from, and the environments it runs in.

**Nothing here is ever mounted into a container**, and that is the property
the whole mechanism rests on. A session's container binds its checkout and
the checkouts a registry declares, their shared git directories, the
per-project environments under ``~/.cache/lup/environments``, cache volumes,
a named config volume, and the bridge directories a launch creates under the
system's temporary directory (:meth:`lup.harness.image.Image.session_arguments`
and :func:`lup.devtools.harness.contained.contained_argv` are where those are
assembled). None of them is under the state directory, so an answer recorded
here is one no session could have written -- unlike ``.lup/questions.jsonl``,
which lives in the checkout and is writable from inside, where no gate
remains to stop a session answering its own question.
"""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings

from lup.policy.relay import QuestionRelay
from lup.trust.objects import ObjectStore
from lup.trust.zone import TrustError


class StateLocation(BaseSettings, populate_by_name=True):
    """Where this machine keeps state that outlives a process, per the XDG convention."""

    xdg_state_home: Path | None = Field(default=None, validation_alias="XDG_STATE_HOME")

    def directory(self) -> Path:
        """The state home, falling back to the convention's own default."""
        return self.xdg_state_home or Path.home() / ".local" / "state"


type ApprovedBy = Literal["operator", "regeneration", "free zones"]
"""How a tree came to be approved.

``operator`` answered a question about it. ``regeneration`` is the tree an
approved launch's own generation produced from an approved one, differing
only in files the generator vouched for. ``free zones`` is an approved tree
with the paths a newly approved free zone covers taken out, which holds
nothing the operator did not already see.
"""


class Approval(BaseModel, frozen=True):
    """One tree this repository's operator approved, and how."""

    tree: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    by: ApprovedBy = "operator"
    question: str = ""
    """The question whose answer approved it, where one did."""


class WorktreeApproval(BaseModel, frozen=True):
    """The tree one worktree of the repository was last launched from."""

    worktree: Path
    tree: str


class TrustRecord(BaseModel, frozen=True):
    """Everything approved for one repository, read before anything of it runs."""

    repository: Path
    free: list[PurePosixPath] | None = None
    """The free zones last approved, or ``None`` before the first approval.

    Kept here rather than read from the checkout, because the declaration in
    the checkout is written by whoever last edited it -- a session included.
    """

    approvals: list[Approval] = []
    worktrees: list[WorktreeApproval] = []

    def approves(self, tree: str) -> bool:
        """Whether this exact tree was ever approved here."""
        return any(approval.tree == tree for approval in self.approvals)

    def approval(self, tree: str) -> Approval | None:
        """The approval of one tree, or ``None``."""
        return next((item for item in self.approvals if item.tree == tree), None)

    def base_for(self, worktree: Path) -> str | None:
        """What a change in this worktree is measured against.

        The tree this worktree was last launched from, which is what the
        operator last saw here; a worktree never launched from falls back to
        the repository's most recent approval, and a repository with none has
        no base at all.
        """
        own = next(
            (item.tree for item in self.worktrees if item.worktree == worktree), None
        )
        if own is not None:
            return own
        latest = max(self.approvals, key=lambda item: item.at, default=None)
        return latest.tree if latest is not None else None

    def approved(
        self,
        trees: list[Approval],
        worktree: Path,
        launched: str,
        free: list[PurePosixPath],
    ) -> "TrustRecord":
        """This record with new approvals, and ``launched`` as the worktree's tree.

        A tree approved already keeps its first approval, and a tree named
        twice among the new ones is recorded once, as the first names it: an
        operator's answer outranks the narrowing derived from it.
        """
        fresh = [
            item
            for index, item in enumerate(trees)
            if not self.approves(item.tree)
            and all(earlier.tree != item.tree for earlier in trees[:index])
        ]
        return self.model_copy(
            update={
                "free": free,
                "approvals": [*self.approvals, *fresh],
                "worktrees": [
                    *[item for item in self.worktrees if item.worktree != worktree],
                    WorktreeApproval(worktree=worktree, tree=launched),
                ],
            }
        )


class TrustState(BaseModel, frozen=True):
    """One repository's directory under the launcher's state, and what it holds."""

    root: Path
    repository: Path

    @classmethod
    def of(
        cls, identity: str, repository: Path, location: StateLocation | None = None
    ) -> "TrustState":
        """The state directory for one repository identity."""
        chosen = location if location is not None else StateLocation()
        return cls(
            root=chosen.directory() / "lup" / "trust" / identity, repository=repository
        )

    def store(self) -> ObjectStore:
        """The object store every snapshot of this repository is kept in."""
        return ObjectStore(root=self.root / "objects.git").prepared()

    def relay(self) -> QuestionRelay:
        """The relay launch questions are asked and answered through."""
        return QuestionRelay(self.root / "questions.jsonl")

    def export(self, tree: str) -> Path:
        """Where one approved tree is materialized for a launch to run from."""
        return self.root / "exports" / tree

    def environment(self, worktree_digest: str) -> Path:
        """The Python environment a launch from one worktree runs in."""
        return self.root / "environments" / worktree_digest

    def pycache(self) -> Path:
        """Where the launched interpreter keeps its compiled bytecode."""
        return self.root / "pycache"

    def read(self) -> TrustRecord:
        """The record as it stands, or an empty one for a repository never approved.

        A record that does not parse is refused rather than treated as empty:
        empty would mean "first launch", and a first launch shows the whole
        zone, which is safe -- but silently dropping approvals the operator
        gave would teach them that the launcher forgets.
        """
        path = self.root / "record.json"
        if not path.is_file():
            return TrustRecord(repository=self.repository)
        try:
            return TrustRecord.model_validate_json(path.read_bytes())
        except ValidationError as error:
            raise TrustError(
                f"the trust record at {path} does not parse; move it aside to start "
                f"over: {error}"
            ) from error

    def write(self, record: TrustRecord) -> None:
        """Replace the record in one rename, so no reader meets half of it."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "record.json"
        staged = path.with_name("record.json.tmp")
        staged.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        staged.replace(path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize read-modify-write of the record across concurrent launches."""
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "record.lock").open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
