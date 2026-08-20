"""A snapshot taken before a destructive command, so it stops being one.

The permission lattice asks about a great deal, and the argument for asking
about everything unjudged is an observability argument that logging serves
without interrupting anybody. What makes that trade safe is not a better
classifier -- it is being able to put the tree back. So before a command that
can destroy work, the tree is written into the object store under a ref of its
own, and `rm -rf`, `git reset --hard` and a mistaken edit stop being
irreversible.

**What is captured, exactly.** Tracked content *and* untracked files, through
a throwaway index rather than through `git stash create`. That distinction is
the whole of why this module exists: `git stash create` captures only tracked
files that were modified, so the file you wrote thirty seconds ago and have
not added yet -- precisely what `rm -rf src/` destroys, and precisely when you
reach for undo -- is not in it. Measured rather than assumed: against a tree
holding one new file and two modified ones, `stash create` produced a commit
containing the two. `git stash create -u` does not help; `create` takes an
optional *message*, so the `-u` is swallowed as one and the commit comes back
titled `-u` with the untracked file still absent.

**What is not captured.** Ignored files. `.gitignore` is honoured, so caches,
virtual environments and build output stay out -- and so do `.env.local` and
the resolver's state, which are ignored without being disposable. That is a
real limit, stated rather than papered over: on the checkout this was built
in, ignored-but-precious content came to 592 MB against a 21 MB object store,
so capturing it would write twenty-eight times the repository's whole history
before every mutating command. `git clean -fdx` therefore keeps asking,
because it is the one command whose whole purpose is destroying what this
cannot restore. A secret belongs outside the checkout instead.

**What it costs**, measured on that same checkout: about 7 ms per snapshot
once the index is warm, and nothing at all in the object store when nothing
changed, because git addresses content rather than time. Six worktrees
snapshotting at once took 38 ms in total and added zero bytes; two of them
produced the identical tree object between them. A snapshot of a tree with one
line edited costs about 10 KB, which is why they expire.
"""

from datetime import UTC, datetime
from pathlib import Path

import sh
from pydantic import BaseModel, Field

from lup.devtools.utils import git

UNDO_NAMESPACE = "refs/lup/undo"
"""Where snapshots live: a ref namespace of this project's own.

Under `refs/` rather than in a stash so nothing a human does to their stash
disturbs them, and outside `refs/heads` so no branch listing, push, or fetch
treats them as work anybody meant to publish.
"""

DEFAULT_RETENTION_DAYS = 7
"""How long a snapshot is worth keeping, absent a caller's own answer.

A default rather than a constant: how long ago a mistake is still worth
undoing is a judgement about how somebody works, not a fact about git. Long
enough to cover a week of sessions, short enough that a snapshot per mutating
command does not accumulate without bound -- at roughly 10 KB each, a week is
a few megabytes.
"""

# lup: ignore[library-default] — the format this asks git for and the fields
# the parser reads back are two halves of one protocol and must spell alike;
# a caller free to change one would silently break the other
REF_FIELDS = ("%(refname)", "%(objectname)", "%(creatordate:iso-strict)", "%(subject)")
"""What each listed snapshot reports, in order, joined by a tab.

Not a judgement offered to a caller. It is read straight back by
:meth:`UndoPoint.parse`, positionally, and its length is what that method
checks a line against -- so the two are one decision written once rather than
a default anybody is invited to differ on.
"""


class UndoPoint(BaseModel, frozen=True):
    """One snapshot: what the tree held, when, and what was about to happen."""

    ref: str
    commit: str
    taken_at: datetime
    reason: str = Field(
        description=(
            "The command this was taken before. Recorded because a list of "
            "timestamps is not something anybody can choose from -- what a "
            "reader looks for is the snapshot from before the thing that "
            "went wrong"
        )
    )

    def restore_command(self) -> str:
        """How a human puts this tree back, printed rather than run.

        Printed because restoring overwrites present work with past work,
        which is the same class of act as the destruction it undoes. This
        module makes the recovery *possible* and leaves performing it to
        somebody who can see what is currently there.
        """
        return f"git restore --source {self.commit} --worktree ."

    @classmethod
    def parse(cls, line: str) -> "UndoPoint | None":
        """One `for-each-ref` line, or nothing when it is not one of ours.

        The delimiter is a tab this module asked for, and git offers no
        machine format for `for-each-ref` beyond choosing one. Bounded at
        three splits so a subject carrying a tab stays whole rather than
        overflowing into a field that is not there.
        """
        # lup: ignore[string-split] — git emits the separator this call chose
        # and ships no parser for it; the bound is what keeps a tab in the
        # subject from being read as a fifth field
        fields = line.split("\t", 3)
        if len(fields) != len(REF_FIELDS):
            return None
        return cls(
            ref=fields[0],
            commit=fields[1],
            taken_at=datetime.fromisoformat(fields[2]),
            reason=fields[3].removeprefix("lup undo: "),
        )


def index_path(root: Path, session: str) -> Path:
    """Where the throwaway index for one session's snapshots lives.

    Inside the git directory rather than a temporary one, so it survives
    between snapshots in the same checkout: a warm index is what makes a
    snapshot cost milliseconds instead of re-hashing every file, and a fresh
    one on each call would pay the cold cost every time.

    Per session, because two sessions sharing one index file would each
    invalidate the other's cached stat data and both would run cold.
    """
    named = Path(git.out("-C", str(root), "rev-parse", "--git-dir").strip())
    directory = named if named.is_absolute() else root / named
    return directory / f"lup-undo-{session}.index"


def snapshot(
    root: Path,
    reason: str,
    session: str = "default",
    namespace: str = UNDO_NAMESPACE,
) -> UndoPoint:
    """Write the working tree into the object store and name it.

    Through a private index so neither the real index nor the working tree is
    touched: a snapshot must not stage anything, and one taken before every
    command would otherwise quietly rewrite the state a human was in the
    middle of composing.
    """
    taken = datetime.now(UTC)
    private = {"GIT_INDEX_FILE": str(index_path(root, session))}
    git("-C", str(root), "add", "-A", _env=private)
    tree = git.out("-C", str(root), "write-tree", _env=private).strip()
    commit = git.out(
        "-C", str(root), "commit-tree", tree, "-m", f"lup undo: {reason}"
    ).strip()
    ref = f"{namespace}/{taken:%Y%m%dT%H%M%S%f}-{commit[:8]}"
    git("-C", str(root), "update-ref", ref, commit)
    return UndoPoint(ref=ref, commit=commit, taken_at=taken, reason=reason)


def points(root: Path, namespace: str = UNDO_NAMESPACE) -> list[UndoPoint]:
    """Every snapshot this checkout still holds, newest first.

    Ordered by ref name rather than by creation date, which sounds like the
    wrong key and is the right one. Git records a ref's date from the commit,
    whose resolution is one second, so two snapshots taken in the same second
    tie -- and a tie means `latest` can hand back the older of the two, which
    is the worst possible moment for a safety net to be approximate. The name
    carries a microsecond stamp in a fixed-width field, so sorting it as text
    is exact.
    """
    listed = git.lines(
        "-C",
        str(root),
        "for-each-ref",
        "--sort=-refname",
        f"--format={'%09'.join(REF_FIELDS)}",
        namespace,
        _ok_code=[0, 1],
    )
    return [
        parsed
        for line in listed
        if line
        for parsed in [UndoPoint.parse(line)]
        if parsed
    ]


def expire(
    root: Path,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    namespace: str = UNDO_NAMESPACE,
    now: datetime | None = None,
) -> list[UndoPoint]:
    """Drop snapshots older than the retention window; report what went.

    Without this the layer grows without bound -- one snapshot per mutating
    command, none ever removed -- and a safety net that fills a disk is a
    different kind of hazard. Deleting the ref is all that is needed: the
    objects it held become unreachable, and git's own housekeeping reclaims
    them.
    """
    cutoff = (now or datetime.now(UTC)).timestamp() - keep_days * 86400
    stale = [
        item for item in points(root, namespace) if item.taken_at.timestamp() < cutoff
    ]
    for item in stale:
        git("-C", str(root), "update-ref", "-d", item.ref)
    return stale


def latest(root: Path, namespace: str = UNDO_NAMESPACE) -> UndoPoint | None:
    """The most recent snapshot, or nothing where none was ever taken."""
    found = points(root, namespace)
    return found[0] if found else None


def snapshot_quietly(root: Path, reason: str, session: str = "default") -> str:
    """Take a snapshot, reporting a failure rather than raising it.

    A safety net that stops the thing it was protecting is worse than no net:
    a checkout mid-merge, a locked index, and a repository this process cannot
    write to are all reasons a snapshot cannot be taken, and none of them is a
    reason to refuse the command. Returns the ref on success and an
    explanation on failure, so a caller can say which happened without having
    to decide what to do about it.
    """
    try:
        return snapshot(root, reason, session).ref
    except (sh.ErrorReturnCode, OSError, ValueError) as failure:
        return f"no snapshot taken ({failure})"
