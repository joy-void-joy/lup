"""Since the operator approved: what a conversation's branch changed since the version of each file they last approved, read as its worktree stands, and marking it good.

`docs/dashboard.md`, *The drawers*. A flagged write (`lup_dev.policy.flags`)
is no item of the review: the "since you approved" drawer under an agent's
banner shows each file its branch changed, whole, from the version the
operator last approved on that branch, or from the integration branch's tip
where they approved none, as a hold at landing starts from it (`Baseline`,
`lup_dev.policy.landing`), with the parts the judge flagged marked by its
reading. Uncommitted changes count: the worktree is read as it stands,
snapshotted through the judge's store of it (`Store`) by an index of this
reader's own, so what git ignores is left out and the judge's index is
never waited on. The reply says the version read (`Since.version`), the
snapshot's tree, and how many writes the branch's flags gathered: the page
keeps what the operator reads still and brings the rest in on a key, asking
again with the version it shows (`ShowSince.seen`), which the files are left
out for where it's the one as it stands.

Marking it good (`ApproveSince`) approves every flagged write on the branch,
or those on one file, as the review's Space `a` on that file does: each stays
in the store as it is, approved, which is what a landing waits on
(`docs/judging-writes.md`, *Landing a branch*), and the baseline moves to it.

The host runs git on the repository pinned to its git directory
(`docs/credentials.md`, *Running git on the host*), never from the worktree.
"""

import asyncio
from pathlib import Path
from typing import Literal, override

from lup.types import Model
from lup_dev.git import Git
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import ChangedFile, Conversation, Flagged, InboxError, Item
from lup_dev.layout import Layout
from lup_dev.policy.landing import (
    Baseline,
    approved,
    blob,
    changed_files,
    short,
    worktrees,
)
from lup_dev.policy.store import Store
from lup_dev.policy.worktrees import SessionIndex


class ShowSince(Request, reads=True):
    """Read what a conversation's branch changed since the operator approved it, as its worktree stands; with `seen`, the version the page shows, the files are left out where it's the one as it stands."""

    kind: Literal["policy-show-since"] = "policy-show-since"
    conversation: Conversation
    seen: str | None = None


class ApproveSince(Request, reads=False):
    """Approve every flagged write on a conversation's branch, or those on the file at `path`: the branch's landing waits on none of them, and what the operator reads since starts from them."""

    kind: Literal["policy-approve-since"] = "policy-approve-since"
    conversation: Conversation
    path: Path | None = None


class SinceFile(Model):
    """One file a branch changed since the operator approved it: whole, from the version they approved, with the judge's reading of its latest flag; which flags cover it, and the version it stands at."""

    file: ChangedFile
    version: str | None = None
    """git's id for the file's content as it stands, which a comment on it
    records (`Quoted.version`); none where the branch deleted it."""
    flags: list[int] = []
    """The flagged writes on it the operator hasn't approved, each approved
    by Space `a` on the file."""
    since: int | None = None
    """The item whose version of the file it's shown from, the latest the
    operator approved, read or commented on; none where they saw none, and
    it's shown from the integration branch's tip."""


class Since(Reply):
    """What a conversation's branch changed since the operator approved it, as its worktree stands."""

    kind: Literal["policy-since"] = "policy-since"
    worktree: Path
    branch: str | None
    """The branch the worktree has checked out; none on a detached `HEAD`,
    where nothing is flagged by branch."""
    version: str
    """The worktree as it stands and the baseline it's read from: the tree of
    its snapshot, then how many flagged writes on the branch are approved, so
    it changes as either does; what the page asks again with (`ShowSince.seen`)."""
    writes: int
    """How many writes the branch's flagged writes gathered, approved or not:
    grows with each, so the page can say how many came since it last read."""
    same: bool = False
    """Whether the version is the one the page said it shows, its files left out."""
    files: list[SinceFile] = []


class Approved(Reply):
    """The flagged writes marking it good approved."""

    kind: Literal["policy-approved"] = "policy-approved"
    flags: list[int]


class Located(Model):
    """Where a conversation's work stands: its worktree, and the branch it has checked out."""

    root: Path
    branch: str | None


class Snapshot(Model, arbitrary_types_allowed=True):
    """The worktree as it stands, read once for each file: its snapshot's tree in the store, the branch's tip and the baseline's commit in the repository, and what the operator saw."""

    baseline: Baseline
    store: Store
    git: Git
    tree: str
    old: str | None
    branches: list[str]

    def filed(self, path: Path) -> SinceFile | None:
        """Return the file at `path` as the drawer shows it: as it stands in the tree, from the version the operator last saw on the branches, else from the baseline's commit; none where it's as they saw it."""
        after = self.store.content(self.tree, path)
        seen = self.baseline.seen(path, self.branches)
        kept = None if seen is None else self.baseline.kept(seen, path)
        since = None if seen is None or kept is None else seen.number
        before = (
            kept
            if kept is not None or self.old is None
            else blob(self.git, self.old, path)
        )
        if before == after:
            return None
        flags = self.baseline.flags(self.branches, path)
        latest = max(flags, key=lambda each: each.number, default=None)
        reading = None if latest is None else self.baseline.reading(latest, after)
        return SinceFile(
            file=ChangedFile.of(path, before, after, reading),
            version=self.store.blob(self.tree, path),
            flags=[each.number for each in flags],
            since=since,
        )


class Reader(Model, arbitrary_types_allowed=True):
    """Reads what a conversation's branch changed since the operator approved it, and approves its flags, over the inbox and lup's state on the host."""

    delivery: Delivery
    layout: Layout
    """lup's state on the host: the judge's session index and stores."""
    integration: str
    """The integration branch's name, whose tip is the baseline where the
    operator approved none of a file."""
    remote: str = "origin"
    """The remote whose copy of the integration branch is read, as `land`
    lands on it; the local branch where there's none."""

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

    def store(self, party: Conversation, root: Path) -> Store:
        """Return the judge's store of the worktree at `root`, read through this reader's own index."""
        layout = self.layout.store(root)
        return Store(
            layout=layout, worktree=root, common=party.repository, index=layout.reading
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
        """Say the version read: `tree`, the worktree as it stands, then how many flagged writes on `branch` are approved, the baseline."""
        settled = [each for each in self.flagged(party, branch) if approved(each)]
        return f"{tree} {len(settled)}"

    def read(self, request: ShowSince) -> Since:
        """Read what the branch changed since the operator approved it, as the worktree stands (`Since`)."""
        party = request.conversation
        located = self.located(party)
        root, branch = located.root, located.branch
        git = Git.pinned(party.repository)
        store = self.store(party, root)
        tree = store.snapshot()
        flagged = self.flagged(party, branch)
        writes = sum(
            each.reason.writes for each in flagged if isinstance(each.reason, Flagged)
        )
        version = self.version(party, branch, tree)
        if request.seen == version:
            return Since(
                worktree=root, branch=branch, version=version, writes=writes, same=True
            )
        tip = None if branch is None else git.commit(f"refs/heads/{branch}")
        old = self.old(git)
        committed = [] if tip is None else changed_files(git, old, tip)
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
            baseline=Baseline(inbox=self.delivery.inbox, repository=party.repository),
            store=store,
            git=git,
            tree=tree,
            old=old,
            branches=[] if branch is None else [branch],
        )
        files = [found for path in paths if (found := snapshot.filed(path)) is not None]
        return Since(
            worktree=root, branch=branch, version=version, writes=writes, files=files
        )

    def approved(self, request: ApproveSince) -> Approved:
        """Approve every flagged write on the conversation's branch, or on the file at `path`, and return them; refused on a detached `HEAD`, where nothing is flagged by branch."""
        party = request.conversation
        located = self.located(party)
        if located.branch is None:
            message = (
                f"{located.root} has no branch checked out, so nothing is flagged "
                "on one to approve"
            )
            raise InboxError(message)
        baseline = Baseline(inbox=self.delivery.inbox, repository=party.repository)
        flags = baseline.flags([located.branch], request.path)
        for each in flags:
            self.delivery.flag_approved(each.number)
        return Approved(flags=[each.number for each in flags])


class SinceShowing(Model, Reading[ShowSince], arbitrary_types_allowed=True):
    """Answers `ShowSince`: what the branch changed since the operator approved it, read off the event loop; for a room, of a conversation of its repository alone."""

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


class SinceApproving(Model, Handler[ApproveSince], arbitrary_types_allowed=True):
    """Answers `ApproveSince`: the branch's flagged writes approved."""

    reader: Reader

    @override
    def request(self) -> type[ApproveSince]:
        return ApproveSince

    @override
    async def answer(self, request: ApproveSince) -> Reply:
        return await asyncio.to_thread(self.reader.approved, request)


def routes(delivery: Delivery, layout: Layout, integration: str) -> list[Route]:
    """Route the kinds the drawer asks to their handlers, over `delivery`, lup's state at `layout`, and the integration branch `integration`."""
    reader = Reader(delivery=delivery, layout=layout, integration=integration)
    return [
        Route.reading(SinceShowing(reader=reader)),
        Route.to(SinceApproving(reader=reader)),
    ]
