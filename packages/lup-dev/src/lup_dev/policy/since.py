"""Since the operator approved: what a conversation's branches changed since the version of each file they last saw, read as each worktree stands, each file a landing waits on held there, and marking files reviewed or declining their landing.

`docs/dashboard.md`, *The drawers*. A flagged write (`lup_dev.policy.flags`)
is no item of the review: the "since you approved" drawer under an agent's
banner shows each file their branches changed, from the version of it the
operator last saw on that branch, the one they marked reviewed or one kept
beside an item of it they settled (`Baseline`, `lup_dev.policy.landing`), or,
where they saw none, from where the branch left the integration branch, the
merge base of the two branches' tips (`Reader.base`), so what the integration
branch took in since is never shown as the branch undoing it; with the parts
the judge flagged marked by its reading. A file that stands as they last saw it
is said in a line, with nothing under it, so the drawer shows the whole branch.

**Every place the conversation wrote** is a place of the drawer's own
(`SincePlace`, `Reader.places`): each worktree their file tools wrote in, as the
judge's session index has it, else the one their launch started in, with the
branch it has checked out; then each branch holding flagged writes of theirs
still waiting that none of those has checked out, read in the worktree that
has it checked out, else at its tip, or, gone, its flags listed. Uncommitted
changes count: a worktree is read as it stands, snapshotted through the judge's
store of it (`Store`) by an index of this reader's own, so what git ignores is
left out and the judge's index is never waited on. The reply says the version
read (`Since.version`), each place's snapshot's tree, the baseline and the
landings waiting: the page asks again with the version it shows
(`ShowSince.seen`), and the places are left out where it's the one as it
stands.

**A file a landing waits on is held at landing there** (`SinceFile.held`;
`lup_dev.policy.waits`): shown at the version the landing's tip holds, what
merges, from the version the operator last saw, else from the gated branch's
tip on the remote, as `land` holds it. Marking files reviewed (`ReviewSince`),
as the review's Space `d` on one and on the drawer do, keeps for each the
version the page showed (`lup_dev.policy.reviewed`), whether or not anything
flagged it: what the drawer shows of it starts there from then on. It approves
the flagged writes on each file only where the file still stands at that
version, the landing's tip's for one held, so a write that came after the page
read it, which the operator never saw, waits: the file comes back with it, and
its landing waits on its flags (`docs/judging-writes.md`, *Landing a branch*).
Declining them (`ReviewSince.decline`), Space `x` on a file held at landing, or
a comment on one sent without Space `d`, marks each reviewed at the version
shown without approving its flags, and declines its landing, with the words the
operator sent on it: the call waiting answers not landed. Where the drawer
stood at the version the page shows as they were marked
(`ReviewSince.seen`), the answer carries its version after and each file
marked as the drawer shows it then, so the page takes them in without reading
the drawer again.

Each place's reading lists its snapshot's tree and its base once, and reads
every version it compares in one `git cat-file` of the store and one of the
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
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field, StringConstraints

from lup.types import Model, MutableModel
from lup_dev.git import Git, GitError, Tracked
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.inbox import store as inbox
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import (
    ChangedFile,
    Conversation,
    Flagged,
    InboxError,
    Item,
    Remark,
    Review,
    Withdrawn,
)
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
from lup_dev.policy.waits import Declined, Wait, Waits
from lup_dev.policy.worktrees import SessionIndex
from lup_dev.stored import read_model

if TYPE_CHECKING:
    from collections.abc import Iterator

type Version = Annotated[
    str, StringConstraints(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")
]
"""git's id for a file's content: 40 hexadecimal digits, or 64 in a repository
of SHA-256."""


class ShowSince(Request, reads=True):
    """Read what a conversation's branches changed since the operator last saw them, as their worktrees stand; with `seen`, the version the page shows, the places are left out where it's the one as it stands."""

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
    """Mark files of one of a conversation's places reviewed at the versions the page shows: what the drawer shows of each starts there, and the flagged writes on each still standing at it are approved; or, declining, their landing declined, their flags left waiting."""

    kind: Literal["policy-review-since"] = "policy-review-since"
    conversation: Conversation
    worktree: Path | None = None
    """The place's worktree (`SincePlace.worktree`); none for a branch read at
    its tip, or gone. With `branch` none too, the conversation's first place."""
    branch: str | None = None
    """The place's branch (`SincePlace.branch`)."""
    files: list[ViewedFile] = Field(min_length=1)
    seen: str | None = None
    """The drawer's version the page shows (`Since.version`): where the drawer
    stood at it as the files were marked, the answer says the drawer as it
    stands after (`SinceReviewed.version`)."""
    decline: bool = False
    """Whether it declines the landing waiting on each file: each marked
    reviewed at the version shown, its flags left waiting, and the landing
    told, with the words the operator sent on it."""


class HeldAt(Model):
    """The landing waiting on a file, as the drawer shows it held there: which, who lands it, what, where to, and whether the operator declined the file."""

    key: str
    """The landing's, among those waiting (`Wait.key`)."""
    lander: Conversation
    named: str
    """What lands where, in a line's words (`Wait.named`)."""
    tip: str
    declined: bool = False


class SinceFile(Model):
    """One file a branch changed, as the drawer shows it: whole, from the version the operator last saw, or none where it stands as that; with the judge's reading of its latest flag, which flags cover it, the version it stands at, where they saw it, and the landing waiting on it."""

    path: Path
    """From the worktree's root."""
    file: ChangedFile | None = None
    """Whole on each side, from the version they last saw to the file as it
    stands, or as the landing's tip holds it where one waits on it; none where
    it stands as they saw it, which the drawer says in a line."""
    version: str | None = None
    """git's id for the file's content as it's shown, which a comment on it
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
    held: HeldAt | None = None
    """The landing waiting on it, where one does: it's shown as the landing's
    tip holds it, and answered by marking it reviewed or declining it."""


class SincePlace(Model):
    """One place a conversation worked, as the drawer shows it: a worktree with the branch it has checked out, a branch alone, read at its tip, or a branch gone; and each file changed there."""

    worktree: Path | None = None
    """Where it's read as it stands; none for a branch no worktree has checked
    out, read at its tip, or gone."""
    branch: str | None = None
    """The branch read; none on a detached `HEAD`, where nothing is flagged or
    marked by branch."""
    gone: bool = False
    """Whether the branch is gone, its flags still waiting listed alone."""
    files: list[SinceFile] = []


class Since(Reply):
    """What a conversation's branches changed since the operator last saw them, each place they worked as it stands."""

    kind: Literal["policy-since"] = "policy-since"
    version: str
    """Each place as it stands and the baseline it's read from: the tree of
    each worktree's snapshot or each branch's tip, how many flagged writes on
    the branches are approved, the marks on them and the landings waiting on
    them, so it changes as any does; what the page asks again with
    (`ShowSince.seen`)."""
    same: bool = False
    """Whether the version is the one the page said it shows, its places left out."""
    places: list[SincePlace] = []


class SinceReviewed(Reply):
    """The files marked reviewed, the flagged writes approved with them or the files whose landing was declined, and the files that changed since the version shown, whose flags wait."""

    kind: Literal["policy-reviewed"] = "policy-reviewed"
    reviewed: list[Path]
    approved: list[int] = []
    declined: list[Path] = []
    """The files whose landing was declined, a landing waiting on each."""
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


class Marking(Model):
    """What marking files did: the reply, and the landings waiting on their branch, each to wake to look again at what it waits on."""

    reviewed: SinceReviewed
    woken: list[Wait]


class Snapshotting(MutableModel, arbitrary_types_allowed=True):
    """One snapshot at a time of each worktree through the reader's own index, which git locks while it writes it: the lock of each worktree, made the first time one's asked for."""

    locks: dict[Path, threading.Lock] = {}

    def of(self, root: Path) -> threading.Lock:
        """Return the lock of the worktree at `root`."""
        return self.locks.setdefault(root, threading.Lock())


class Located(Model):
    """One place a conversation's work stands: a worktree, with the branch it has checked out; or a branch alone, no worktree of theirs having it checked out, or gone."""

    root: Path | None
    branch: str | None
    gone: bool = False


def blobs(listed: list[Tracked]) -> dict[Path, str]:
    """Return git's id for each file's content of `listed`, by its path: its blobs, a directory and a submodule's commit left out."""
    return {Path(each.path): each.object for each in listed if each.kind == "blob"}


class Landed(Model):
    """A file a landing waits on, as the drawer reads it: its path, the landing, and git's id for the file at its tip and at the gated branch's tip on the remote, which it's shown from where the operator saw none of it."""

    path: Path
    at: HeldAt
    version: str | None
    old: str | None


class Snapshot(Model, arbitrary_types_allowed=True):
    """A place as it stands and where its branch left the integration branch, each listed once, what the operator saw, and the files a landing waits on: every file of the place read from them together."""

    baseline: Baseline
    standing_git: Git
    """Where the content of each file as it stands is read: the worktree's
    store, or the repository for a branch read at its tip."""
    git: Git
    """The repository."""
    standing: dict[Path, str]
    """git's id for each file's content in the worktree's snapshot or at the
    branch's tip, by its path (`blobs`)."""
    base: str | None
    """The commit the branch left the integration branch at (`Reader.base`),
    which a file the operator saw none of is shown from."""
    based: dict[Path, str]
    """git's id for each file's content at `base`, by its path."""
    held: dict[Path, Landed] = {}
    """Each file a landing waits on, by its path: shown as its tip holds it."""
    branches: list[str]
    roles: Roles | None
    """The role of each path, by the repository's declaration the judge last
    loaded; none where it has loaded none, and an unflagged file has no role."""

    def shown(self, path: Path) -> str | None:
        """Return git's id for the file at `path` as it's shown: at the tip of the landing waiting on it, else as it stands."""
        held = self.held.get(path)
        return self.standing.get(path) if held is None else held.version

    def files(self, paths: list[Path]) -> list[SinceFile]:
        """Return each file of `paths` as the drawer shows it, in order: as it stands in the snapshot, or at the tip of the landing waiting on it, from the version the operator last saw on the branches, else from `base`, or the gated branch's remote tip for one held; with no `file` where it stands as they saw it, and left out where they saw none and it stands as at `base`.

        Every version compared is read in one `git cat-file` of where it
        stands and one of the repository; one known by its id to stand as its
        diff starts (`same`), never.
        """
        saws = {path: self.baseline.saw(path, self.branches) for path in paths}
        known = {path: self.same(path, saws[path]) for path in paths}
        compared = [path for path in paths if known[path] is not True]
        standing = [path for path in compared if path not in self.held]
        landed = {
            path: version
            for path, held in self.held.items()
            if (version := held.version) is not None
        }
        olds = {
            path: old
            for path, held in self.held.items()
            if (old := held.old) is not None
        }
        unseen = [path for path in compared if saws[path] is None]
        after = {
            **self.read(self.standing_git, self.standing, standing),
            **self.read(
                self.git, landed, [path for path in compared if path in self.held]
            ),
        }
        # A file held is shown from the gated branch's remote tip, as `land` holds it, whatever the base holds.
        starts = {
            **{
                path: each for path, each in self.based.items() if path not in self.held
            },
            **olds,
        }
        based = self.read(self.git, starts, unseen)

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
        """Say whether the file at `path` stands as its diff starts, by git's ids where both are known: against the version at `base` where the operator saw none (`saw`), or the gated branch's remote tip for one held, or the version they marked reviewed; none where its bytes are to be compared, as with a version kept beside an item."""
        held = self.held.get(path)
        if saw is None:
            start = self.based.get(path) if held is None else held.old
            return self.shown(path) == start
        if saw.reviewed is not None:
            return saw.reviewed.version == self.shown(path)
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
        """Return the file at `path` as the drawer shows it, from `before`, what the operator last saw (`saw`) or the version at `base`, to `after`, as it stands or as the landing waiting on it holds it, unless it stands as its diff starts (`same`), where it's a line; none where they saw none, it stands as at `base` and no landing waits on it."""
        flags = self.baseline.flags(self.branches, path)
        held = self.held.get(path)
        shown = SinceFile(
            path=path,
            version=self.shown(path),
            flags=[each.number for each in flags],
            since=None if saw is None else saw.item,
            reviewed=None if saw is None or saw.reviewed is None else saw.reviewed.at,
            held=None if held is None else held.at,
        )
        if same:
            return None if saw is None and held is None else shown
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
    """Reads what a conversation's branches changed since the operator last saw them, marks their files reviewed and declines their landing, over the inbox, the landings waiting and lup's state on the host."""

    delivery: Delivery
    layout: Layout
    """lup's state on the host: the judge's session index and stores, and the
    files marked reviewed."""
    integration: str
    """The integration branch's name, where the branch left which is the
    baseline where the operator saw none of a file (`base`)."""
    waits: Waits = Field(default_factory=Waits)
    """The landings waiting on the operator, the service's, which hold each
    file they wait on in its writer's drawer."""
    remote: str = "origin"
    """The remote whose copy of the integration branch is read, as `land`
    lands on it; the local branch where there's none."""
    snapshotting: Snapshotting = Field(default_factory=Snapshotting)
    """Held while a worktree is snapshotted: a read at an agent's hook, one as
    its drawer opens and a marking may come at once."""

    def places(self, party: Conversation) -> list[Located]:
        """Return where `party` works, each place once: each worktree their file tools wrote in, as the judge's session index has it, else the one their launch started in, with the branch it has checked out; then each branch holding their flagged writes still waiting that none of those has checked out, in the worktree that has it checked out, else alone, or gone.

        Raise `InboxError` where lup never heard the conversation.
        """
        place = self.delivery.inbox.whereabouts.get(party.key())
        if place is None:
            message = "lup's inbox has never heard of the conversation"
            raise InboxError(message)
        held = SessionIndex(layout=self.layout).read(party.session)
        wrote = [] if held is None else held.works(party.agent or "")
        git = Git.pinned(party.repository)
        listed = worktrees(git)
        checked = {
            each.root: None if each.branch is None else short(each.branch)
            for each in listed
        }
        # A worktree removed since is no place to read; one git names otherwise is read, its branch unknown.
        roots = [
            root
            for root in wrote or [place.worktree]
            if root in checked or root.is_dir()
        ]
        found = [Located(root=root, branch=checked.get(root)) for root in roots]
        have = [each.branch for each in found]
        flagged = dict.fromkeys(
            item.reason.branch
            for item in self.delivery.inbox.about(party.repository)
            if isinstance(item.reason, Flagged)
            and item.sender == party
            and not approved(item)
            and not isinstance(item.state, Withdrawn)
            and item.reason.branch is not None
            and item.reason.branch not in have
        )

        def apart(branch: str | None) -> Located:
            root = next(
                (root for root, named in checked.items() if named == branch), None
            )
            gone = root is None and git.commit(f"refs/heads/{branch}") is None
            return Located(root=root, branch=branch, gone=gone)

        return [*found, *(apart(branch) for branch in flagged)]

    @staticmethod
    def chosen(
        found: list[Located], worktree: Path | None, branch: str | None
    ) -> Located:
        """Return the place of `found` the page names by `worktree` and `branch`, the first where it names neither; refused where it's none of them."""
        if worktree is None and branch is None:
            if not found:
                message = (
                    "the conversation works in no worktree there is, and holds no flag"
                )
                raise InboxError(message)
            return found[0]
        named = next(
            (each for each in found if each.root == worktree and each.branch == branch),
            None,
        )
        if named is None:
            where = branch if worktree is None else worktree
            message = f"{where} is no place the conversation worked"
            raise InboxError(message)
        return named

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

    def waiting(self, party: Conversation, branch: str | None) -> list[Wait]:
        """Return the landings of `party`'s repository waiting on files of `branch`."""
        return [
            each
            for each in self.waits.of(party.repository)
            if branch is not None and branch in each.branches
        ]

    def version(self, party: Conversation, located: Located, tree: str) -> str:
        """Say the version of a place read: `tree`, the place as it stands, then the baseline, how many flagged writes on its branch are approved and the marks on it, and the landings waiting on its files, each with the files the operator declined."""
        branch = located.branch
        settled = [each for each in self.flagged(party, branch) if approved(each)]
        reviews = self.baseline(party).reviews
        marked = "-" if branch is None else reviews.stamp(branch)
        landings = ",".join(
            f"{each.key}:{'+'.join(str(file.path) for file in each.files if file.declined)}"
            for each in self.waiting(party, branch)
        )
        return f"{tree} {len(settled)} {marked} {landings or '-'}"

    def read(self, request: ShowSince) -> Since:
        """Read what the conversation's branches changed since the operator last saw them, each place as it stands (`Since`)."""
        party = request.conversation
        read = [self.standing(party, each) for each in self.places(party)]
        version = " | ".join(each.version for each in read)
        if request.seen == version:
            return Since(version=version, same=True)
        return Since(version=version, places=[each.place() for each in read])

    def standing(self, party: Conversation, located: Located) -> Standing:
        """Return the place `located` as it stands: its tree, snapshotted where it's a worktree, its tip's where it's a branch alone, none where it's gone; and its version."""
        git = Git.pinned(party.repository)
        branch = located.branch
        tip = None if branch is None else git.commit(f"refs/heads/{branch}")
        if located.root is None:
            tree = "gone" if tip is None else git.text("rev-parse", f"{tip}^{{tree}}")
            return Standing(
                reader=self,
                party=party,
                located=located,
                tip=tip,
                tree=None if tip is None else tree,
                version=self.version(party, located, tree),
            )
        store = self.store(party, located.root)
        with self.snapshotting.of(located.root):
            tree = store.snapshot()
        return Standing(
            reader=self,
            party=party,
            located=located,
            tip=tip,
            tree=tree,
            store=store,
            version=self.version(party, located, tree),
        )

    def snapshot(
        self,
        party: Conversation,
        located: Located,
        standing_git: Git,
        *,
        listed: list[Tracked],
        tip: str | None,
    ) -> Snapshot:
        """Return a place's snapshot as `listed` lists its tree, read through `standing_git`, with where the branch at `tip` left the integration branch, listed too, what the operator saw of `party`'s repository, and the files a landing waits on, each read at its tip."""
        git = Git.pinned(party.repository)
        base = self.base(git, self.old(git), tip)
        return Snapshot(
            baseline=self.baseline(party, once=True),
            standing_git=standing_git,
            git=git,
            standing=blobs(listed),
            base=base,
            based={} if base is None else blobs(git.tracked(base)),
            held=self.held(git, located.branch, self.waiting(party, located.branch)),
            branches=[] if located.branch is None else [located.branch],
            roles=self.roles(party, located.root),
        )

    @staticmethod
    def held(git: Git, branch: str | None, waiting: list[Wait]) -> dict[Path, Landed]:
        """Return each file of `branch` a landing of `waiting` waits on, by its path, read at the landing's tip and the gated branch's tip on the remote: the earliest landing's, where several wait on one file."""
        if branch is None:
            return {}

        def landed(wait: Wait) -> Iterator[Landed]:
            tip = blobs(git.tracked(wait.tip))
            old = {} if wait.old is None else blobs(git.tracked(wait.old))
            for each in wait.files:
                at = HeldAt(
                    key=wait.key,
                    lander=wait.lander,
                    named=wait.named,
                    tip=wait.tip,
                    declined=each.declined is not None,
                )
                yield Landed(
                    path=each.path,
                    at=at,
                    version=tip.get(each.path),
                    old=old.get(each.path),
                )

        # The earliest landing's, read first, is the one kept.
        found = [each for wait in waiting for each in landed(wait)]
        return {each.path: each for each in reversed(found)}

    def roles(self, party: Conversation, root: Path | None) -> Roles | None:
        """Return the role of each path in the worktree at `root`, or the repository's main one for a branch alone, by the last of `party`'s repository's declarations the judge loaded (`LastDeclaration`): read from lup's state, never loaded here, which would run the declaration at each reading; none where the judge has loaded none."""
        last = read_model(self.layout.declaration(party.repository), LastDeclaration)
        if last is None:
            return None
        where = root or Git.pinned(party.repository).main_worktree()
        return Roles(root=where, declaration=last.declaration)

    def reviewed(self, request: ReviewSince) -> SinceReviewed:
        """Mark each file of `request` reviewed, or decline its landing (`marked`), and wake each landing waiting on them, which looks again at what it waits on."""
        marking = self.marked(request)
        self.woke(marking.woken)
        return marking.reviewed

    def woke(self, waiting: list[Wait]) -> None:
        """Tell each of `waiting`, landings whose files were marked or declined, to the page watching them and to the call waiting on each: on the service's loop, where there's one."""
        for wait in waiting:
            self.waits.told(self.waits.waits.get(wait.key, wait))
            self.delivery.arrive(wait.lander)

    def marked(self, request: ReviewSince) -> Marking:
        """Mark each file of `request` reviewed at the version shown, approving the flagged writes on those still standing at it, or, declining, declining the landing waiting on each, its flags left waiting; and say which, with the drawer's version after and the files as it shows them where it stood at the version the page shows (`ReviewSince.seen`); with the landings waiting on its branch, to wake.

        Refused on a detached `HEAD`, where nothing is marked by branch, and
        where a version shown isn't kept where the place stands or in the
        repository. A file of a branch gone is marked nothing: its flags are
        approved, or its landing declined.
        """
        party = request.conversation
        places = self.places(party)
        located = self.chosen(places, request.worktree, request.branch)
        branch = located.branch
        if branch is None:
            message = (
                f"{located.root} has no branch checked out, and a file is marked "
                "reviewed on its branch"
            )
            raise InboxError(message)
        git = Git.pinned(party.repository)
        # Each place as it stands before the marking, every one where the page says the drawer it shows.
        standings = {
            (each.root, each.branch): self.standing(party, each)
            for each in places
            if request.seen is not None or each == located
        }
        before = standings[located.root, located.branch]
        waiting = self.waiting(party, branch)
        held = self.held(git, branch, waiting)
        standing = {
            **blobs(before.listed()),
            **{path: each.version for path, each in held.items() if each.version},
        }
        moved = [
            each.path
            for each in request.files
            if not located.gone and standing.get(each.path) != each.version
        ]
        baseline = self.baseline(party)
        flags = (
            []
            if request.decline
            else [
                flag
                for each in request.files
                if each.path not in moved
                for flag in baseline.flags([branch], each.path)
            ]
        )
        for flag in flags:
            self.delivery.flag_approved(flag.number)
        declined = (
            self.declined(party, branch, [each.path for each in request.files])
            if request.decline
            else []
        )
        if not located.gone:
            contents = self.kept(
                before,
                [each.version for each in request.files if each.version is not None],
                [
                    held[each.path].version
                    for each in request.files
                    if each.path in held
                ],
            )
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
            declined=declined,
            moved=moved,
        )
        shown = " | ".join(
            standings[each.root, each.branch].version
            for each in places
            if (each.root, each.branch) in standings
        )
        if request.seen is None or request.seen != shown:
            return Marking(reviewed=reviewed, woken=waiting)
        after = self.standing(party, located)
        drawer = " | ".join(
            after.version
            if each == located
            else standings[each.root, each.branch].version
            for each in places
        )
        return Marking(
            reviewed=reviewed.model_copy(
                update={
                    "version": drawer,
                    "files": after.files([each.path for each in request.files]),
                }
            ),
            woken=waiting,
        )

    def declined(
        self, party: Conversation, branch: str, paths: list[Path]
    ) -> list[Path]:
        """Decline the landing waiting on each of `paths` on `branch`, with the words the operator sent on it to `party` since that landing began; return those a landing waited on."""

        def declining(path: Path) -> bool:
            waiting = self.waits.on(party.repository, branch, path)
            if not waiting:
                return False
            began = min(each.began for each in waiting)
            words = self.said(party, path, began)
            declined = Declined(at=self.delivery.clock.now(), words=words)
            self.waits.declined(party.repository, branch, path, declined)
            return True

        return [path for path in paths if declining(path)]

    def said(self, party: Conversation, path: Path, since: datetime) -> str:
        """Return what the operator said on the file at `path` in `party`'s drawer since `since`: each remark on its lines they sent, its quote then their words."""

        def on(remark: Remark) -> bool:
            block = remark.quote.block
            return remark.to == party and (
                (remark.code is not None and remark.code.path == path)
                or block.endswith(f" file {path}")
                or f" file {path} on " in block
            )

        remarks = [
            remark
            for item in self.delivery.inbox.about(party.repository)
            if isinstance(item.reason, Review) and item.made >= since
            for remark in item.reason.remarks
            if on(remark) and remark.text.strip()
        ]
        return "\n".join(
            f"{remark.quote.text}\n{remark.text.strip()}" for remark in remarks
        )

    def kept(
        self, standing: Standing, versions: list[str], landed: list[str | None]
    ) -> dict[str, bytes]:
        """Return the content of each of `versions`, by git's id for it: those of `landed`, at a landing's tip, and every one of a branch alone, from the repository, the rest from the worktree's store, each read by one `git cat-file`; refused, naming them, where it keeps any not, as a version the page shows."""
        wanted = list(dict.fromkeys(versions))
        from_git = (
            wanted
            if standing.store is None
            else [each for each in wanted if each in landed]
        )
        from_store = [each for each in wanted if each not in from_git]
        git = Git.pinned(standing.party.repository)
        try:
            found = dict(zip(from_git, git.contents(from_git), strict=True))
            if standing.store is not None:
                found |= dict(
                    zip(
                        from_store,
                        standing.store.snapshots().contents(from_store),
                        strict=True,
                    )
                )
        except GitError:
            store = standing.store
            lost = [
                each
                for each in wanted
                if store is None or each in from_git or store.object(each) is None
            ]
            where = "the repository" if store is None else "the worktree's store"
            message = (
                f"{where} keeps no {', '.join(lost)}, a version the page shows: "
                "read the drawer again"
            )
            raise InboxError(message) from None
        return found


class Standing(Model, arbitrary_types_allowed=True):
    """One place of a conversation's as it stands, read once: its tree and the version it says."""

    reader: Reader
    party: Conversation
    located: Located
    tip: str | None
    """The branch's tip; none on a detached `HEAD`, or where it's gone."""
    tree: str | None
    """The worktree's snapshot's tree, or the tip's for a branch alone; none
    where it's gone."""
    store: Store | None = None
    """The worktree's store, where it's a worktree."""
    version: str

    def listed(self) -> list[Tracked]:
        """List the place's tree: its snapshot's, its tip's, or nothing where it's gone."""
        if self.tree is None:
            return []
        if self.store is not None:
            return self.store.snapshots().tracked(self.tree)
        return Git.pinned(self.party.repository).tracked(self.tree)

    def snapshot(self) -> Snapshot:
        """Return the place's snapshot, as it stands, what the operator saw and the files a landing waits on."""
        git = Git.pinned(self.party.repository)
        return self.reader.snapshot(
            self.party,
            self.located,
            git if self.store is None else self.store.snapshots(),
            listed=self.listed(),
            tip=self.tip,
        )

    def files(self, paths: list[Path]) -> list[SinceFile]:
        """Return each file of `paths` as the drawer shows it, the place as it stands."""
        return self.snapshot().files(paths)

    def place(self) -> SincePlace:
        """Return the place as the drawer shows it: each file its branch changed since the operator last saw it, those a landing waits on among them; for a branch gone, each file with flags still waiting, a line."""
        located = self.located
        if located.gone:
            baseline = self.reader.baseline(self.party, once=True)
            branches = [] if located.branch is None else [located.branch]
            paths = list(
                dict.fromkeys(each.flagged.path for each in baseline.flags(branches))
            )
            return SincePlace(
                branch=located.branch,
                gone=True,
                files=[
                    SinceFile(
                        path=path,
                        flags=[each.number for each in baseline.flags(branches, path)],
                    )
                    for path in paths
                ],
            )
        git = Git.pinned(self.party.repository)
        snapshot = self.snapshot()
        tip = self.tip
        committed = [] if tip is None else changed_files(git, snapshot.base, tip)
        at_tip = {} if tip is None else blobs(git.tracked(tip))
        standing = snapshot.standing
        uncommitted = [
            path
            for path in dict.fromkeys([*at_tip, *standing])
            if at_tip.get(path) != standing.get(path)
        ]
        paths = sorted(dict.fromkeys([*committed, *uncommitted, *snapshot.held]))
        return SincePlace(
            worktree=located.root,
            branch=located.branch,
            files=snapshot.files(paths),
        )


class SinceShowing(Model, Reading[ShowSince], arbitrary_types_allowed=True):
    """Answers `ShowSince`: what the branches changed since the operator last saw them, read off the event loop; for a room, of a conversation of its repository alone."""

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
    """Answers `ReviewSince`: the files marked reviewed or their landing declined, one marking at a time, since each replaces its branch's marks whole; a room never reaches it."""

    reader: Reader
    turns: asyncio.Lock = Field(default_factory=asyncio.Lock)

    @override
    def request(self) -> type[ReviewSince]:
        return ReviewSince

    @override
    async def answer(self, request: ReviewSince) -> Reply:
        async with self.turns:
            marking = await asyncio.to_thread(self.reader.marked, request)
        self.reader.woke(marking.woken)
        return marking.reviewed


def routes(
    delivery: Delivery, layout: Layout, integration: str, waits: Waits
) -> list[Route]:
    """Route the kinds the drawer asks to their handlers, over `delivery`, lup's state at `layout`, the integration branch `integration`, and the landings waiting, `waits`."""
    reader = Reader(
        delivery=delivery, layout=layout, integration=integration, waits=waits
    )
    return [
        Route.reading(SinceShowing(reader=reader)),
        Route.to(SinceReviewing(reader=reader)),
    ]
