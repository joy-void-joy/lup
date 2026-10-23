"""Since the operator approved: what a conversation's branch changed since the version of each file they last saw, read as its worktree stands, and marking files reviewed.

`docs/dashboard.md`, *The drawers*. A flagged write (`lup_dev.policy.flags`)
is no item of the review: the "since you approved" drawer under an agent's
banner shows each file its branch changed, from the version of it the operator
last saw on that branch, the one they marked reviewed or one kept beside an
item of it they settled (`Baseline`, `lup_dev.policy.landing`), or, where they
saw none, from where the branch left the integration branch, the merge base of
the two branches' tips (`Reader.base`), so what the integration branch took in
since is never shown as the branch undoing it; with the parts the judge flagged
marked by its reading. A file that stands as they last saw it is said in a line, with
nothing under it, so the drawer shows the whole branch. Uncommitted changes
count: the worktree is read as it stands, snapshotted through the judge's
store of it (`Store`) by an index of this reader's own, so what git ignores is
left out and the judge's index is never waited on. The reply says the version
read (`Since.version`), the snapshot's tree and the baseline: the page asks
again with the version it shows (`ShowSince.seen`), and the files are left out
where it's the one as it stands.

Marking files reviewed (`ReviewSince`), as the review's Space `a` on one and
Space `A` on the drawer do, keeps for each the version the page showed
(`lup_dev.policy.reviewed`), whether or not anything flagged it: what the
drawer shows of it starts there from then on. It approves the flagged writes
on each file only where the file still stands at that version, so a write that
came after the page read it, which the operator never saw, waits: the file
comes back with it, and its landing waits on its flags
(`docs/judging-writes.md`, *Landing a branch*).

The host runs git on the repository pinned to its git directory
(`docs/credentials.md`, *Running git on the host*), never from the worktree.
"""

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, override

from pydantic import Field, StringConstraints

from lup.types import Model, MutableModel
from lup_dev.git import Git
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.inbox import store as inbox
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import ChangedFile, Conversation, Flagged, InboxError, Item
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import LastDeclaration
from lup_dev.policy.landing import (
    Baseline,
    approved,
    changed_files,
    short,
    started,
    worktrees,
)
from lup_dev.policy.reviewed import Mark, Reviews
from lup_dev.policy.roles import Roles
from lup_dev.policy.store import Store
from lup_dev.policy.worktrees import SessionIndex
from lup_dev.stored import read_model

type Version = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
]
"""git's id for a file's content: 40 hexadecimal digits, or 64 in a repository
of SHA-256."""


class ShowSince(Request, reads=True):
    """Read what a conversation's branch changed since the operator last saw it, as its worktree stands; with `seen`, the version the page shows, the files are left out where it's the one as it stands."""

    kind: Literal["policy-show-since"] = "policy-show-since"
    conversation: Conversation
    seen: str | None = None


class ViewedFile(Model):
    """A file of the drawer as the page shows it: its path, and the version shown."""

    path: Path
    """From the worktree's root."""
    version: Version | None = None
    """git's id for the content shown (`SinceFile.version`); none where it's
    shown deleted."""


class ReviewSince(Request, reads=False):
    """Mark files of a conversation's branch reviewed at the versions the page shows: what the drawer shows of each starts there, and the flagged writes on each still standing at it are approved."""

    kind: Literal["policy-review-since"] = "policy-review-since"
    conversation: Conversation
    files: list[ViewedFile] = Field(min_length=1)


class SinceFile(Model):
    """One file a branch changed, as the drawer shows it: whole, from the version the operator last saw, or none where it stands as that; with the judge's reading of its latest flag, which flags cover it, the version it stands at, and where they saw it."""

    path: Path
    """From the worktree's root."""
    file: ChangedFile | None = None
    """Whole on each side, from the version they last saw to the file as it
    stands; none where it stands as they saw it, which the drawer says in a
    line."""
    version: str | None = None
    """git's id for the file's content as it stands, which a comment on it
    records (`Quoted.version`) and marking it reviewed keeps (`ViewedFile.version`);
    none where the branch deleted it."""
    flags: list[int] = []
    """The flagged writes on it the operator hasn't approved, each approved
    by marking it reviewed where it stands as shown."""
    since: int | None = None
    """The item whose version of the file it's shown from, the latest the
    operator approved, read or commented on; none where they saw none, or
    marked it reviewed since (`reviewed`)."""
    reviewed: datetime | None = None
    """When they marked the version it's shown from reviewed, where that's the
    latest they saw of it; none else, and it's shown from the item `since`, or
    from where the branch left the integration branch (`Reader.base`)."""


class Since(Reply):
    """What a conversation's branch changed since the operator last saw it, as its worktree stands."""

    kind: Literal["policy-since"] = "policy-since"
    worktree: Path
    branch: str | None
    """The branch the worktree has checked out; none on a detached `HEAD`,
    where nothing is flagged or marked by branch."""
    version: str
    """The worktree as it stands and the baseline it's read from: the tree of
    its snapshot, how many flagged writes on the branch are approved, and the
    marks on it, so it changes as any does; what the page asks again with
    (`ShowSince.seen`)."""
    same: bool = False
    """Whether the version is the one the page said it shows, its files left out."""
    files: list[SinceFile] = []


class SinceReviewed(Reply):
    """The files marked reviewed, the flagged writes approved with them, and the files that changed since the version shown, whose flags wait."""

    kind: Literal["policy-reviewed"] = "policy-reviewed"
    reviewed: list[Path]
    approved: list[int] = []
    moved: list[Path] = []
    """The files that stand at another version than the one shown, a write
    having come after the page read it: marked reviewed at the version shown,
    their flags left waiting."""


class Snapshotting(MutableModel, arbitrary_types_allowed=True):
    """One snapshot at a time of each worktree through the reader's own index, which git locks while it writes it: the lock of each worktree, made the first time one's asked for."""

    locks: dict[Path, threading.Lock] = {}

    def of(self, root: Path) -> threading.Lock:
        """Return the lock of the worktree at `root`."""
        return self.locks.setdefault(root, threading.Lock())


class Located(Model):
    """Where a conversation's work stands: its worktree, and the branch it has checked out."""

    root: Path
    branch: str | None


class Snapshot(Model, arbitrary_types_allowed=True):
    """The worktree as it stands, read once for each file: its snapshot's tree in the store, where the branch left the integration branch in the repository, and what the operator saw."""

    baseline: Baseline
    store: Store
    git: Git
    tree: str
    base: str | None
    """The commit the branch left the integration branch at (`Reader.base`),
    which a file the operator saw none of is shown from."""
    branches: list[str]
    roles: Roles | None
    """The role of each path, by the repository's declaration the judge last
    loaded; none where it has loaded none, and an unflagged file has no role."""

    def filed(self, path: Path) -> SinceFile | None:
        """Return the file at `path` as the drawer shows it: as it stands in the tree, from the version the operator last saw on the branches, else from `base`; with no `file` where it stands as they saw it, and none where they saw none and it stands as at `base`."""
        after = self.store.content(self.tree, path)
        saw = self.baseline.saw(path, self.branches)
        before = started(saw, self.git, self.base, path)
        flags = self.baseline.flags(self.branches, path)
        shown = SinceFile(
            path=path,
            version=self.store.blob(self.tree, path),
            flags=[each.number for each in flags],
            since=None if saw is None else saw.item,
            reviewed=None if saw is None or saw.reviewed is None else saw.reviewed.at,
        )
        if before == after:
            return None if saw is None else shown
        latest = max(flags, key=lambda each: each.number, default=None)
        # A file nothing flagged has no reading of the judge's but its role, which
        # the drawer folds a test or a data file whole by.
        reading = (
            self.baseline.reading(latest, after)
            if latest is not None
            else None
            if self.roles is None
            else inbox.Reading(role=self.roles.role(path))
        )
        return shown.model_copy(
            update={"file": ChangedFile.of(path, before, after, reading)}
        )


class Reader(Model, arbitrary_types_allowed=True):
    """Reads what a conversation's branch changed since the operator last saw it, and marks its files reviewed, over the inbox and lup's state on the host."""

    delivery: Delivery
    layout: Layout
    """lup's state on the host: the judge's session index and stores, and the
    files marked reviewed."""
    integration: str
    """The integration branch's name, where the branch left which is the
    baseline where the operator saw none of a file (`base`)."""
    remote: str = "origin"
    """The remote whose copy of the integration branch is read, as `land`
    lands on it; the local branch where there's none."""
    snapshotting: Snapshotting = Field(default_factory=Snapshotting)
    """Held while a worktree is snapshotted: a read at an agent's hook, one as
    its drawer opens and a marking may come at once."""

    def located(self, party: Conversation) -> Located:
        """Return where `party` works: the worktree its file tools write in, as the judge's session index has it, else the one its launch started in; and the branch it has checked out.

        Raise `InboxError` where lup never heard the conversation.
        """
        place = self.delivery.inbox.whereabouts.get(party.key())
        if place is None:
            message = "lup's inbox has never heard of the conversation"
            raise InboxError(message)
        held = SessionIndex(layout=self.layout).read(party.session)
        wrote = [] if held is None else held.works(party.agent or "")
        root = next(iter(wrote), place.worktree)
        git = Git.pinned(party.repository)
        branch = next(
            (each.branch for each in worktrees(git) if each.root == root), None
        )
        return Located(root=root, branch=None if branch is None else short(branch))

    def old(self, git: Git) -> str | None:
        """Return the integration branch's tip, the remote's copy where it's there, else the local branch's; none where there's neither."""
        remote = git.commit(f"refs/remotes/{self.remote}/{self.integration}")
        return remote or git.commit(f"refs/heads/{self.integration}")

    def base(self, git: Git, old: str | None, tip: str | None) -> str | None:
        """Return where the branch at `tip` left the integration branch at `old`: their merge base, the latest commit both hold, so a file only the integration branch changed since isn't one the branch changed, and one both changed shows the branch's change alone; `old` where there's no `tip`, or the two share no history.

        Once the integration branch is merged into the branch, the merge base
        moves to the tip merged, so what the merge brought in isn't shown as
        the branch's.
        """
        if old is None or tip is None:
            return old
        found = git.run("merge-base", old, tip, ok=[0, 1])
        return found.output.decode().strip() if found.status == 0 else old

    def store(self, party: Conversation, root: Path) -> Store:
        """Return the judge's store of the worktree at `root`, read through this reader's own index."""
        layout = self.layout.store(root)
        return Store(
            layout=layout, worktree=root, common=party.repository, index=layout.reading
        )

    def baseline(self, party: Conversation) -> Baseline:
        """Return what the operator last saw of the files of `party`'s repository."""
        repository = party.repository
        return Baseline(
            inbox=self.delivery.inbox,
            repository=repository,
            reviews=Reviews(layout=self.layout.reviewed(repository)),
        )

    def flagged(self, party: Conversation, branch: str | None) -> list[Item]:
        """Return the flagged writes on `branch`, in every state."""
        return [
            item
            for item in self.delivery.inbox.about(party.repository)
            if isinstance(item.reason, Flagged)
            and branch is not None
            and item.reason.branch == branch
        ]

    def version(self, party: Conversation, branch: str | None, tree: str) -> str:
        """Say the version read: `tree`, the worktree as it stands, then the baseline, how many flagged writes on `branch` are approved and the marks on it."""
        settled = [each for each in self.flagged(party, branch) if approved(each)]
        reviews = self.baseline(party).reviews
        marked = "-" if branch is None else reviews.stamp(branch)
        return f"{tree} {len(settled)} {marked}"

    def read(self, request: ShowSince) -> Since:
        """Read what the branch changed since the operator last saw it, as the worktree stands (`Since`)."""
        party = request.conversation
        located = self.located(party)
        root, branch = located.root, located.branch
        git = Git.pinned(party.repository)
        store = self.store(party, root)
        with self.snapshotting.of(root):
            tree = store.snapshot()
        version = self.version(party, branch, tree)
        if request.seen == version:
            return Since(worktree=root, branch=branch, version=version, same=True)
        tip = None if branch is None else git.commit(f"refs/heads/{branch}")
        base = self.base(git, self.old(git), tip)
        committed = [] if tip is None else changed_files(git, base, tip)
        at_tip = (
            {} if tip is None else {each.path: each.object for each in git.tracked(tip)}
        )
        standing = {each.path: each.object for each in store.snapshots().tracked(tree)}
        uncommitted = [
            path
            for path in dict.fromkeys([*at_tip, *standing])
            if at_tip.get(path) != standing.get(path)
        ]
        paths = sorted(
            dict.fromkeys([*committed, *(Path(each) for each in uncommitted)])
        )
        snapshot = Snapshot(
            baseline=self.baseline(party),
            store=store,
            git=git,
            tree=tree,
            base=base,
            branches=[] if branch is None else [branch],
            roles=self.roles(party, root),
        )
        files = [found for path in paths if (found := snapshot.filed(path)) is not None]
        return Since(worktree=root, branch=branch, version=version, files=files)

    def roles(self, party: Conversation, root: Path) -> Roles | None:
        """Return the role of each path in the worktree at `root`, by the last of `party`'s repository's declarations the judge loaded (`LastDeclaration`): read from lup's state, never loaded here, which would run the declaration at each reading; none where the judge has loaded none."""
        last = read_model(self.layout.declaration(party.repository), LastDeclaration)
        return None if last is None else Roles(root=root, declaration=last.declaration)

    def reviewed(self, request: ReviewSince) -> SinceReviewed:
        """Mark each file of `request` reviewed at the version shown, approving the flagged writes on those still standing at it, and say which; refused on a detached `HEAD`, where nothing is marked by branch, and where a version shown isn't in the worktree's store."""
        party = request.conversation
        located = self.located(party)
        branch = located.branch
        if branch is None:
            message = (
                f"{located.root} has no branch checked out, and a file is marked "
                "reviewed on its branch"
            )
            raise InboxError(message)
        store = self.store(party, located.root)
        contents = {
            each.version: store.object(each.version)
            for each in request.files
            if each.version is not None
        }
        lost = [version for version, content in contents.items() if content is None]
        if lost:
            message = (
                f"the worktree's store keeps no {', '.join(lost)}, a version the "
                "page shows: read the drawer again"
            )
            raise InboxError(message)
        with self.snapshotting.of(located.root):
            tree = store.snapshot()
        baseline = self.baseline(party)
        moved = [
            each.path
            for each in request.files
            if store.blob(tree, each.path) != each.version
        ]
        flags = [
            flag
            for each in request.files
            if each.path not in moved
            for flag in baseline.flags([branch], each.path)
        ]
        for flag in flags:
            self.delivery.flag_approved(flag.number)
        # Made once the flags are approved, so each mark is the latest the operator saw, at the same moment.
        at = self.delivery.clock.now()
        baseline.reviews.marked(
            branch,
            [
                Mark(path=each.path, version=each.version, at=at)
                for each in request.files
            ],
            {
                version: content
                for version, content in contents.items()
                if content is not None
            },
        )
        return SinceReviewed(
            reviewed=[each.path for each in request.files],
            approved=[each.number for each in flags],
            moved=moved,
        )


class SinceShowing(Model, Reading[ShowSince], arbitrary_types_allowed=True):
    """Answers `ShowSince`: what the branch changed since the operator last saw it, read off the event loop; for a room, of a conversation of its repository alone."""

    reader: Reader

    @override
    def request(self) -> type[ShowSince]:
        return ShowSince

    @override
    async def answer(self, request: ShowSince) -> Reply:
        return await asyncio.to_thread(self.reader.read, request)

    @override
    async def scoped(self, request: ShowSince, repository: Path) -> Reply:
        if request.conversation.repository != repository:
            message = "the conversation isn't one of this repository's"
            raise InboxError(message)
        return await self.answer(request)


class SinceReviewing(Model, Handler[ReviewSince], arbitrary_types_allowed=True):
    """Answers `ReviewSince`: the files marked reviewed, one marking at a time, since each replaces its branch's marks whole; a room never reaches it."""

    reader: Reader
    turns: asyncio.Lock = Field(default_factory=asyncio.Lock)

    @override
    def request(self) -> type[ReviewSince]:
        return ReviewSince

    @override
    async def answer(self, request: ReviewSince) -> Reply:
        async with self.turns:
            return await asyncio.to_thread(self.reader.reviewed, request)


def routes(delivery: Delivery, layout: Layout, integration: str) -> list[Route]:
    """Route the kinds the drawer asks to their handlers, over `delivery`, lup's state at `layout`, and the integration branch `integration`."""
    reader = Reader(delivery=delivery, layout=layout, integration=integration)
    return [
        Route.reading(SinceShowing(reader=reader)),
        Route.to(SinceReviewing(reader=reader)),
    ]
