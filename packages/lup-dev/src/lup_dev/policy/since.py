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
(`docs/judging-writes.md`, *Landing a branch*). Where the drawer stood at the
version the page shows as they were marked (`ReviewSince.seen`), the answer
carries its version after and each file marked as the drawer shows it then, so
the page takes them in without reading the drawer again.

Each reading lists the snapshot's tree and the base once, and reads every
version it compares in one `git cat-file` of the store and one of the
repository, never one known by its id to stand as its diff starts: the drawer
is read at each of an agent's hooks, and a few git runs a file add up to
hundreds of milliseconds on a branch of tens of files.

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
from lup_dev.git import Git, GitError, Tracked
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.inbox import store as inbox
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import ChangedFile, Conversation, Flagged, InboxError, Item
from lup_dev.layout import Layout
from lup_dev.policy.checkpoint import LastDeclaration
from lup_dev.policy.landing import (
    Baseline,
    Saw,
    approved,
    changed_files,
    short,
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
    seen: str | None = None
    """The drawer's version the page shows (`Since.version`): where the drawer
    stood at it as the files were marked, the answer says the drawer as it
    stands after (`SinceReviewed.version`)."""


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
    version: str | None = None
    """The drawer's version once the files are marked, where it stood at the
    version the page shows (`ReviewSince.seen`) as they were: the drawer the
    page shows, with the files marked as `files` says, is the drawer as it
    stands. None else, and the page reads the drawer again."""
    files: list[SinceFile] = []
    """Each file marked, as the drawer shows it once marked, where `version` is
    given."""


class Snapshotting(MutableModel, arbitrary_types_allowed=True):
    """One snapshot at a time of each worktree through the reader's own index, which git locks while it writes it: the lock of each worktree, made the first time one's asked for."""

    locks: dict[Path, threading.Lock] = {}

    def of(self, root: Path) -> threading.Lock:
        """Return the lock of the worktree at `root`."""
        return self.locks.setdefault(root, threading.Lock())


class Located(Model):
    """Where a conversation's work stands: their worktree, and the branch they have checked out."""

    root: Path
    branch: str | None


def blobs(listed: list[Tracked]) -> dict[Path, str]:
    """Return git's id for each file's content of `listed`, by its path: its blobs, a directory and a submodule's commit left out."""
    return {Path(each.path): each.object for each in listed if each.kind == "blob"}


class Snapshot(Model, arbitrary_types_allowed=True):
    """The worktree as it stands and where the branch left the integration branch, each listed once, and what the operator saw: every file of the drawer read from them together."""

    baseline: Baseline
    store: Store
    git: Git
    standing: dict[Path, str]
    """git's id for each file's content in the worktree's snapshot, by its path
    (`blobs`)."""
    base: str | None
    """The commit the branch left the integration branch at (`Reader.base`),
    which a file the operator saw none of is shown from."""
    based: dict[Path, str]
    """git's id for each file's content at `base`, by its path."""
    branches: list[str]
    roles: Roles | None
    """The role of each path, by the repository's declaration the judge last
    loaded; none where it has loaded none, and an unflagged file has no role."""

    def files(self, paths: list[Path]) -> list[SinceFile]:
        """Return each file of `paths` as the drawer shows it, in order: as it stands in the snapshot, from the version the operator last saw on the branches, else from `base`; with no `file` where it stands as they saw it, and left out where they saw none and it stands as at `base`.

        Every version compared is read in one `git cat-file` of the store and
        one of the repository; one known by its id to stand as its diff starts
        (`same`), never.
        """
        saws = {path: self.baseline.saw(path, self.branches) for path in paths}
        known = {path: self.same(path, saws[path]) for path in paths}
        compared = [path for path in paths if known[path] is not True]
        after = self.read(self.store.snapshots(), self.standing, compared)
        unseen = [path for path in compared if saws[path] is None]
        based = self.read(self.git, self.based, unseen)

        def shown(path: Path) -> SinceFile | None:
            saw = saws[path]
            before = based.get(path) if saw is None else saw.content
            same = known[path]
            return self.filed(
                path,
                saw,
                same=before == after.get(path) if same is None else same,
                before=before,
                after=after.get(path),
            )

        return [found for path in paths if (found := shown(path)) is not None]

    def same(self, path: Path, saw: Saw | None) -> bool | None:
        """Say whether the file at `path` stands as its diff starts, by git's ids where both are known: against the version at `base` where the operator saw none (`saw`), or the version they marked reviewed; none where its bytes are to be compared, as with a version kept beside an item."""
        if saw is None:
            return self.standing.get(path) == self.based.get(path)
        if saw.reviewed is not None:
            return saw.reviewed.version == self.standing.get(path)
        return None

    @staticmethod
    def read(git: Git, ids: dict[Path, str], paths: list[Path]) -> dict[Path, bytes]:
        """Return the content of each of `paths` that has an id in `ids`, read by one `git cat-file` of `git`."""
        wanted = [path for path in paths if path in ids]
        return dict(
            zip(wanted, git.contents([ids[path] for path in wanted]), strict=True)
        )

    def filed(
        self,
        path: Path,
        saw: Saw | None,
        *,
        same: bool,
        before: bytes | None,
        after: bytes | None,
    ) -> SinceFile | None:
        """Return the file at `path` as the drawer shows it, from `before`, what the operator last saw (`saw`) or the version at `base`, to `after`, as it stands, unless it stands as its diff starts (`same`), where it's a line; none where they saw none and it stands as at `base`."""
        flags = self.baseline.flags(self.branches, path)
        shown = SinceFile(
            path=path,
            version=self.standing.get(path),
            flags=[each.number for each in flags],
            since=None if saw is None else saw.item,
            reviewed=None if saw is None or saw.reviewed is None else saw.reviewed.at,
        )
        if same:
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
        """Return where `party` works: the worktree their file tools write in, as the judge's session index has it, else the one their launch started in; and the branch they have checked out.

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

    def baseline(self, party: Conversation, *, once: bool = False) -> Baseline:
        """Return what the operator last saw of the files of `party`'s repository: with the inbox's items about it read `once`, for a whole drawer."""
        repository = party.repository
        inbox = self.delivery.inbox
        return Baseline(
            inbox=inbox,
            repository=repository,
            reviews=Reviews.of(self.layout, repository),
            items=inbox.about(repository) if once else None,
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
        listed = store.snapshots().tracked(tree)
        snapshot = self.snapshot(party, located, store, listed=listed, tip=tip)
        committed = [] if tip is None else changed_files(git, snapshot.base, tip)
        at_tip = (
            {} if tip is None else {each.path: each.object for each in git.tracked(tip)}
        )
        standing = {each.path: each.object for each in listed}
        uncommitted = [
            path
            for path in dict.fromkeys([*at_tip, *standing])
            if at_tip.get(path) != standing.get(path)
        ]
        paths = sorted(
            dict.fromkeys([*committed, *(Path(each) for each in uncommitted)])
        )
        files = snapshot.files(paths)
        return Since(worktree=root, branch=branch, version=version, files=files)

    def snapshot(
        self,
        party: Conversation,
        located: Located,
        store: Store,
        *,
        listed: list[Tracked],
        tip: str | None,
    ) -> Snapshot:
        """Return the worktree's snapshot as `listed` lists its tree, with where the branch at `tip` left the integration branch, listed too, and what the operator saw of `party`'s repository."""
        git = Git.pinned(party.repository)
        base = self.base(git, self.old(git), tip)
        return Snapshot(
            baseline=self.baseline(party, once=True),
            store=store,
            git=git,
            standing=blobs(listed),
            base=base,
            based={} if base is None else blobs(git.tracked(base)),
            branches=[] if located.branch is None else [located.branch],
            roles=self.roles(party, located.root),
        )

    def roles(self, party: Conversation, root: Path) -> Roles | None:
        """Return the role of each path in the worktree at `root`, by the last of `party`'s repository's declarations the judge loaded (`LastDeclaration`): read from lup's state, never loaded here, which would run the declaration at each reading; none where the judge has loaded none."""
        last = read_model(self.layout.declaration(party.repository), LastDeclaration)
        return None if last is None else Roles(root=root, declaration=last.declaration)

    def reviewed(self, request: ReviewSince) -> SinceReviewed:
        """Mark each file of `request` reviewed at the version shown, approving the flagged writes on those still standing at it, and say which, with the drawer's version after and the files as it shows them where it stood at the version the page shows (`ReviewSince.seen`); refused on a detached `HEAD`, where nothing is marked by branch, and where a version shown isn't in the worktree's store."""
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
        contents = self.kept(
            store, [each.version for each in request.files if each.version is not None]
        )
        with self.snapshotting.of(located.root):
            tree = store.snapshot()
        # The drawer the page shows is the one as it stands, but for the files marked, where it stood at the version shown.
        shown = request.seen is not None and request.seen == self.version(
            party, branch, tree
        )
        listed = store.snapshots().tracked(tree)
        standing = blobs(listed)
        baseline = self.baseline(party)
        moved = [
            each.path
            for each in request.files
            if standing.get(each.path) != each.version
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
            contents,
        )
        reviewed = SinceReviewed(
            reviewed=[each.path for each in request.files],
            approved=[each.number for each in flags],
            moved=moved,
        )
        if not shown:
            return reviewed
        tip = Git.pinned(party.repository).commit(f"refs/heads/{branch}")
        snapshot = self.snapshot(party, located, store, listed=listed, tip=tip)
        return reviewed.model_copy(
            update={
                "version": self.version(party, branch, tree),
                "files": snapshot.files([each.path for each in request.files]),
            }
        )

    def kept(self, store: Store, versions: list[str]) -> dict[str, bytes]:
        """Return the content of each of `versions` the worktree's store keeps, by git's id for it, read by one `git cat-file`; refused, naming them, where it keeps any not, as a version the page shows."""
        wanted = list(dict.fromkeys(versions))
        try:
            return dict(zip(wanted, store.snapshots().contents(wanted), strict=True))
        except GitError:
            lost = [each for each in wanted if store.object(each) is None]
            message = (
                f"the worktree's store keeps no {', '.join(lost)}, a version the "
                "page shows: read the drawer again"
            )
            raise InboxError(message) from None


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
