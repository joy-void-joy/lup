"""The mounts one session gets over the repository it was opened on.

Worktrees of one repository share an object store and a branch set, so from
any of them `git -C ../other commit` writes to another's branch and
`cp x ../other/src/` overwrites another's file. Nothing separates them, and
this table does not try to: it hands a session the repository it works in,
every checkout of it writable.

**Why it does not separate them.** Holding siblings read-only was meant to
keep one session out of another's uncommitted work, which is the one thing
the reflog cannot restore. It did not protect that set. The table is
computed once, when a container starts, so it covers exactly the checkouts
that existed at that instant: one cut a minute later is outside it and
writable by everything in the session. Every worktree a resolver run leases
is cut after its operator started, so none of the checkouts with several
sessions touching them were ever covered -- while the branches an operator
is landing all predate it, and were. The protection reached the sessions
working alone and missed the ones working at once, which is the reverse of
what it was for, and a boundary that holds by an accident of timing teaches
a reader a rule that is not there.

So confining two workers from each other is a lease per worker, taken when
that worker starts against the tree it was given. What is left here is the
other question -- what one session may reach across its own repository --
and answering both from one table is what tied a worker's confinement to
whether its checkout predated somebody else's container.

**Where a boundary is wanted it stays a mount fact, not a judgement.** The
policy would have to decide, from a command's text, where it will act: that
is undecidable the moment a Makefile, an `xargs`, or a script that shells
out is involved, and `cd ../other && git commit` already walks past it. An OS
boundary does not predict. It observes the write and refuses it, whatever
route reached the syscall. Absolute paths stay identical on both sides --
forced rather than chosen, because a linked worktree's `.git` is a file
holding an absolute `gitdir:` pointer -- and only the modes vary.

**Siblings are still mounted, and that is load-bearing.** The obvious move
is to leave them out. It is wrong, and quietly so. `git gc` runs `git
worktree prune`, which deletes the admin directory of any worktree whose
`gitdir` target has gone missing. A session whose container could not see
its siblings would look around, find every one of their directories absent,
and delete their administrative state from the shared repository -- as
ordinary housekeeping, with no error anywhere. Two guards, where holding
each entry read-only would be a third: siblings are mounted so they exist,
and `gc.worktreePruneExpire` is set to never. The third is not missed,
because it only answers for a directory that is present anyway.

**`config` and `hooks/` are held read-only inside the writable share.** They
are the two places under there whose *contents* run on the host. `config`
names a program through `core.hooksPath`, `alias.*`, `credential.helper` and
the `merge.*.driver` family, each handing git a command line to execute at
the operator's next git command in any worktree of this repository; `hooks/`
holds the script itself, the same reach with no key in between -- a
`pre-commit` written there runs at the next commit in any worktree, and no
config key is involved. Both are writes that land in no diff and reach no
review. So the shared directory is mounted writable and each of them is bound
read-only back over it, which the engine supports because
`Sandbox.declared_mounts` emits parent before child.

Leaving them writable rests on the claim that a worker unable to write these
cannot cut a worktree. That was measured, and it is false: `git worktree add`
never opens `config`, and a guard armed in `hooks/` is inherited rather than
rewritten -- `git rev-parse --git-path hooks` in a linked worktree names
`<common>/hooks`, so a hook armed once covers every worktree of the clone,
whenever it is cut. Nothing else in the mandated workflow writes either --
committing, `pr push` with and without `--force`, base detection, reservation
reads, branch parsing and `worktree remove` were each run against a read-only
bind of both and none of them wrote one. Recording a base branch would have
written `config`, and does not: those facts live beside the branch instead.

Two writes are left, one per path, and both are host-side once-per-clone
acts. A clone registers the `merge.lup-ownership` driver once, because git
resolves a driver name from config alone and no repository can ship it; and a
clone arms its declared guards once, with `git hooks install`. Each has a
pre-flight in front of it that fires only where that write is outstanding, so
a clone that has made it cuts worktrees with both paths held, and one that
has not meets a refusal naming the act and the command before its first
worktree is half-made, rather than an errno about a busy device. The semantic
policy is what holds an approval question against those config keys by
name; the mount table is not the reason it has to.

**What this deliberately does not rail.** Commits landing on another branch.
The object store and refs have to be writable to commit at all, so branch
isolation would need a separate clone per worker -- and git already ships an
undo layer for refs in the reflog, where a mistaken commit is recoverable
completely. A sibling's *uncommitted* work is what the reflog cannot restore,
and it is the per-worker lease that covers it, not this table.

Boundary attribution is a prerequisite rather than a follow-on, and
:mod:`lup.sandbox.attribution` is it, reading the running mount table through
:mod:`lup.sandbox.observed` where the refusal is met from inside. A read-only
mount turns a stray write into `Read-only file system: .../src/foo.py`, and an
agent reading that debugs the filesystem instead of learning it holds a lease.
A rail without attribution is worse than no rail.
"""

import posixpath
from pathlib import Path, PurePosixPath

import sh
from pydantic import BaseModel, Field, field_validator

from lup.execution.shell import git


class Lease(BaseModel, frozen=True):
    """One worker's confinement, as the mounts that produce it.

    Two mappings rather than one table because that is the shape
    :class:`~lup.sandbox.container.Sandbox` takes them in, and keeping the
    split here means a caller never re-derives which is which from a mode.
    """

    writable: dict[Path, str] = Field(
        default={},
        description="Host paths this worker may write, keyed to the same path inside",
    )
    read_only: dict[Path, str] = Field(
        default={},
        description="Host paths this worker may read and must not write",
    )
    pinned: dict[Path, str] = Field(
        default={},
        description=(
            "Host paths mounted writable even where an enclosing mount already "
            "carries them, so each is a mount point of its own: nothing inside "
            "can rename or remove it, which keeps a read-only hole beneath it "
            "at the path the host reads"
        ),
    )

    def mounted_writable(self) -> dict[Path, str]:
        """Every writable mount, pinned ones among them, as an engine takes them."""
        return {**self.writable, **self.pinned}

    def answers_from(self, path: Path) -> Path | None:
        """The mount whose mode this path takes, or ``None`` where none does.

        The deepest one containing it, which is how the boundary itself reads
        the same table: ``execution_write_refusal`` in
        :mod:`lup.policy.assets.host` collects every declared scope the path
        sits under and takes the mode of the longest. A read-only hole inside
        a writable share is exactly that reading, so asking it here rather
        than testing membership means a mount left out for being redundant
        answers the same as one spelled out.
        """
        enclosing = [
            root
            for root in [*self.writable, *self.pinned, *self.read_only]
            if path == root or root in path.parents
        ]
        return max(enclosing, key=lambda root: len(root.parts), default=None)

    def covers(self, path: Path) -> bool:
        """Whether this lease says anything at all about a path."""
        return self.answers_from(path) is not None

    def writable_at(self, path: Path) -> bool:
        """Whether this lease lets a path be written."""
        return self.answers_from(path) in self.mounted_writable()


class AccessibleRoot(BaseModel, frozen=True):
    """One checkout outside this repository a session is meant to reach.

    Declared rather than discovered, which is the whole of why this type
    exists instead of a directory scan. A `refs/` symlink lives inside the
    checkout and is writable from inside the boundary, so a mount table read
    off one would let the confined thing choose what confines it -- the same
    argument that keeps remotes, identity and credentials resolved on the
    host rather than in the container they describe.
    """

    path: Path
    writable: bool = Field(
        default=True,
        description="Whether this root may be written, or only read",
    )


def reached_through(path: Path, inside: str, mounts: dict[Path, str]) -> Path | None:
    """The deepest other mount that already lands this path where this one would.

    A mount reaches a path when it encloses it on the host *and* carries it to
    the same place inside, so the offset from root to path is equal on both
    sides. Anything else is a different directory at a similar spelling, and
    reading it as a substitute would move where the path resolves.

    The deepest, because that is the one the boundary answers from:
    ``execution_write_refusal`` in :mod:`lup.policy.assets.host` matches a
    write against every declared scope containing it and takes the mode of
    the longest. A reading that consulted any other enclosing mount would be
    answering a question the boundary never asks.
    """
    reaching = [
        root
        for root, target in mounts.items()
        if root in path.parents
        and posixpath.join(target, path.relative_to(root).as_posix()) == inside
    ]
    return max(reaching, key=lambda root: len(root.parts), default=None)


def resolved(
    writable: dict[Path, str],
    read_only: dict[Path, str],
    pinned: dict[Path, str] = {},
) -> Lease:
    """One path, one mode, settled toward writable, and stated once.

    Two ways to arrive at the same collision, and neither is hypothetical.
    `git worktree list` reports the main worktree, and in a bare layout that
    directory *is* the shared one -- so the shared directory arrives as its
    own sibling and would be declared read-only and read-write at once. Once
    more than one repository is leased, two registered worktrees of a single
    repository each hold the other read-only while both were named writable
    deliberately.

    Settled toward writable because the paths that reach here writable are
    the ones somebody named, and settled here rather than in the engine,
    where two mounts at one target resolve by whichever order they happen to
    be applied in.

    Then the same collision one directory further out. A mount whose deepest
    enclosing mount already carries it in the same mode changes nothing about
    what may be read or written, and costs something a lease cannot pay back:
    a mount point cannot be removed from inside its own namespace, so a
    checkout bound individually under a shared directory that is itself bound
    outlives `git worktree remove` as an empty directory no session can
    clear. One accumulated per landed branch.

    Same mode is the whole of the relaxation, and it is the *deepest*
    enclosing mount's mode that decides. A read-only entry inside a writable
    share keeps its own mount, which is the nesting this whole arrangement
    rests on; so does a writable checkout inside a read-only directory inside
    a writable share, which stays writable because the mount between them is
    the one that would otherwise answer for it.

    ``pinned`` is the one exception to stating a mount once, and on purpose:
    a pinned path is kept as its own mount however redundant its mode,
    because what it is for is being a mount point. It is writable, so a path
    named both ways is stated as pinned alone.
    """
    unpinned = {path: inside for path, inside in writable.items() if path not in pinned}
    settled = {
        path: inside
        for path, inside in read_only.items()
        if path not in writable and path not in pinned
    }
    every = {**unpinned, **pinned, **settled}

    def stated_once(mode: dict[Path, str], same: dict[Path, str]) -> dict[Path, str]:
        """This mode's mounts, less the ones an enclosing mount already makes."""
        return {
            path: inside
            for path, inside in mode.items()
            if reached_through(path, inside, every) not in same
        }

    return Lease(
        writable=stated_once(unpinned, {**unpinned, **pinned}),
        read_only=stated_once(settled, settled),
        pinned=dict(pinned),
    )


def rooted(lease: Lease) -> Lease:
    """This lease with every hold's path held in place, not only the hold itself.

    A read-only mount refuses writes to what it covers. It does not stop the
    directory *holding* it from being renamed, and a directory with mounts
    beneath it can be: measured, ``mv .lup .lup2`` succeeded with
    ``.lup/preflight`` held read-only inside, and nothing then stopped a new
    ``.lup/preflight`` being written where the host reads it. The same is
    true of a pinned directory's parent. So every directory between a hold
    and the writable mount enclosing it is pinned too — a mount point cannot
    be renamed or removed from inside — and each hold is then reachable only
    by the path the host reads it by.

    Nothing is pinned inside a read-only mount, where nothing can be renamed
    anyway, so this never makes a path writable that was not.
    """
    mounts = {**lease.mounted_writable(), **lease.read_only}
    writable = lease.mounted_writable()

    def between(held: Path) -> list[Path]:
        """The directories from the mount enclosing ``held`` down to its parent."""
        enclosing = max(
            (mount for mount in mounts if mount in held.parents),
            key=lambda mount: len(mount.parts),
            default=None,
        )
        if enclosing is None or enclosing not in writable:
            return []
        return [
            directory for directory in held.parents if enclosing in directory.parents
        ]

    return resolved(
        lease.writable,
        lease.read_only,
        {
            **lease.pinned,
            **same_path(
                [
                    directory
                    for held in [*lease.read_only, *lease.pinned]
                    for directory in between(held)
                ]
            ),
        },
    )


def merged(leases: list[Lease]) -> Lease:
    """Every lease as one, with collisions settled across all of them at once.

    Settling each lease alone and concatenating is not the same thing, and
    the difference is silent: a path one lease holds read-only and another
    holds writable stays read-only, which mounts a worker's own checkout
    unwritable because some other repository called it a sibling.
    """
    return resolved(
        {path: inside for lease in leases for path, inside in lease.writable.items()},
        {path: inside for lease in leases for path, inside in lease.read_only.items()},
        {path: inside for lease in leases for path, inside in lease.pinned.items()},
    )


class RepositoryLayout(BaseModel, frozen=True):
    """The two git directories a linked worktree lives between.

    ``common`` is shared by every worktree of the repository -- objects, refs,
    config, and the `worktrees/` directory holding each one's administrative
    state. ``private`` is this worktree's own entry inside it, holding the
    HEAD, index and logs that are its alone. The two are equal in a plain
    checkout, which is what makes a lease there degenerate rather than broken.
    """

    common: Path
    private: Path

    def linked(self) -> bool:
        """Whether this is a linked worktree rather than a plain checkout."""
        return self.common != self.private

    def name(self) -> str:
        """What to call the repository, identically from any of its worktrees.

        The shared directory is the one thing every worktree of a repository
        has in common, so its name is the one string they all agree on --
        which is what anything wanting to be per *repository* rather than per
        checkout has to key on. A worktree directory's own name is the branch
        somebody made it for.

        Two spellings collapse into it. A bare repository conventionally ends
        in `.git` and says nothing by it, and a plain checkout's shared
        directory *is* `.git`, whose name is the convention rather than the
        project.
        """
        return (
            self.common.parent.name
            if self.common.name == ".git"
            else self.common.name.removesuffix(".git")
        )


def same_path(roots: list[Path]) -> dict[Path, str]:
    """Mount each host path at the identical path inside the container.

    Not a convenience. A linked worktree's `.git` is a file whose contents are
    an absolute `gitdir:` pointer into the shared administrative directory, so
    a container mounting the tree anywhere else would hold a checkout pointing
    at a path that does not exist there. One spelling is the only spelling
    that works.

    Deduplicated by construction, since a dict is what comes back: the shared
    directory and a path beneath it can both be named without the second
    silently becoming a second mount of the first.

    Whether a host can actually do this is not assumed. It is a declared
    requirement, exercised by ``same_path_mount_requirement`` -- because a
    rail whose mounts silently do not happen is not a loosened rail, it is an
    absent one reporting success, and nothing else in this module would
    notice.

    How that probe has to be written was learned the hard way. Asking
    ``test -d`` about the mounted directory reported *false* on rootless
    podman for every worktree this rail leases, which reads exactly like an
    absent mount and is not one: reading a file through the same mount in the
    same container succeeded. The mount was there; `stat` on the mount point
    itself was not answerable under that user-namespace mapping. So the probe
    reads a file across the boundary rather than asking whether a directory
    is present, and the general lesson is the one this whole design keeps
    relearning -- a presence check answers a different question than the one
    being asked, and its wrong answer is shaped like a real finding.
    """
    return {root: root.as_posix() for root in roots}


def repository_layout(worktree: Path) -> RepositoryLayout:
    """Where this checkout keeps its own admin directory and the shared one."""
    asked = ["rev-parse", "--path-format=absolute"]
    return RepositoryLayout(
        common=Path(git.out("-C", str(worktree), *asked, "--git-common-dir").strip()),
        private=Path(git.out("-C", str(worktree), *asked, "--git-dir").strip()),
    )


def sibling_worktrees(worktree: Path) -> list[Path]:
    """Every other checkout of this repository, as absolute paths.

    Listed from git rather than by scanning the parent directory: where
    sibling checkouts live is a repository's own arrangement, and a scan
    would sweep in whatever else happens to sit beside them.
    """
    listed = git.lines("-C", str(worktree), "worktree", "list", "--porcelain")
    found = [
        Path(line.removeprefix("worktree "))
        for line in listed
        if line.startswith("worktree ")
    ]
    return [path for path in found if path != worktree and path.is_dir()]


def lease_for(worktree: Path) -> Lease:
    """The mounts one session needs over the repository it works in.

    Every checkout of this repository writable, the shared administrative
    directory with them, and two things held read-only inside: the shared
    `config` and the shared `hooks/`. Siblings are mounted rather than left
    out for the reason the module docstring gives -- absent, they are what
    `git worktree prune` deletes the administrative state of -- and writable
    for the reason it gives beside that.

    A path the project declared its author owns is not among the read-only
    mounts. Held read-only, `README.md` refuses the fast-forward
    that lands a branch touching it: git replaces a file by unlinking it,
    a mount point refuses that, and the merge is the user's from a host
    terminal every time. What such a mount protects is protected by the
    policy: an edit or a shell write to a human-owned path asks, and the
    approval is the author's answer, which a mount can neither ask for nor
    honour.
    """
    layout = repository_layout(worktree)
    writable = [worktree, *sibling_worktrees(worktree)]
    # Read-only in every layout, linked or plain: these are the two places
    # under the shared directory whose contents name a program the host will
    # run. `config` names one through `core.hooksPath`, `alias.*`,
    # `credential.helper` and `merge.*.driver`; `hooks/` holds the script
    # itself, with no key in between. Both execute at the operator's next git
    # command in any worktree, from a write that lands in no diff. Nothing in
    # the mandated workflow writes either -- cutting a worktree, committing,
    # pushing, base detection and removal were each measured against a
    # read-only bind of both. What is left is one once-per-clone act each,
    # made on the host: the `merge.lup-ownership` registration and arming the
    # guards. Each has a pre-flight refusing by name where it is outstanding.
    read_only: list[Path] = [layout.common / "config", layout.common / "hooks"]
    if layout.linked():
        # The shared directory is mounted writable as a whole, with no
        # administrative entry punched back over it: every sibling's stays
        # present, which is the guard that matters, and `worktree prune`
        # removes an entry for a directory that has gone rather than one it
        # can see. Holding each entry read-only bought the second half of
        # that and cost the ability to remove a worktree at all -- `git
        # worktree remove` unlinks the entry, so a read-only one refuses the
        # removal with an errno about a filesystem.
        #
        # `config`, punched read-only over it above, is the one exception,
        # and `Sandbox.declared_mounts` is what holds that hole up: it emits
        # mounts parent before child, so a read-only entry inside a writable
        # base is applied after it rather than shadowed by it.
        writable += [
            layout.common,
            layout.private,
        ]
    else:
        writable.append(layout.common)
    return resolved(same_path(writable), same_path(read_only))


class NestedRepository(BaseModel, frozen=True):
    """A repository kept inside the checkout, whose git state the host still runs.

    The checkout's own ``config`` and ``hooks/`` are held because the host's
    next git command runs what they name. A repository inside the checkout —
    a directory of generated work with its own history, say — has the same
    two files under the checkout's writable mount, and the operator runs git
    there too, so it is held the same way.

    Declared rather than found by scanning, for three reasons. A scan reads
    a tree the session writes, so the session would choose what its next
    launch mounts: a thousand planted ``.git`` directories is a launch that
    cannot start, the argument that makes :class:`AccessibleRoot` a
    declaration. A scan holds a repository from the launch *after* it
    appears, so the session that made it wrote its configuration unheld and
    the next launch protects whatever that session left there; a declared
    one is created by the host first when ``create`` asks, and its
    configuration is the host's from the first session on. And a scan walks
    every ignored directory — environments, package caches — at every launch,
    for an answer the project already has.
    """

    path: PurePosixPath = Field(description="Where it sits, relative to the checkout")
    create: bool = Field(
        default=False,
        description=(
            "Initialize it on the host when a launch finds it absent, so no "
            "session is ever the one that wrote its configuration"
        ),
    )

    @field_validator("path")
    @classmethod
    def inside_the_checkout(cls, value: PurePosixPath) -> PurePosixPath:
        """Refuse a path that would name the checkout itself or reach outside it."""
        if value.is_absolute() or ".." in value.parts or value == PurePosixPath("."):
            raise ValueError(
                f"nested repository {value.as_posix()!r} must name a directory "
                "inside the checkout, relative to its root"
            )
        return value


def held_repository(checkout: Path) -> Lease:
    """The mounts that keep one checkout's git configuration where git reads it.

    Holding ``config`` and ``hooks/`` read-only answers for the files. It
    does not answer for where git looks for them, and a session can move
    that — each of these was measured, with a planted alias running on the
    next git command:

    - renaming the git directory, which is allowed while mounts sit beneath
      it, then making a new one with a configuration of the session's own;
    - planting ``commondir`` in the git directory, which git follows to
      read ``config`` from wherever it names;
    - rewriting a linked worktree's ``.git`` pointer, or its administrative
      ``commondir``, to the same end.

    So ``commondir`` is held read-only too, as a file naming the directory
    itself: ``.``, which git reads as no redirection at all. Measured neutral
    for status, add, commit, log, ``worktree add``, ``list`` and ``remove``,
    ``gc`` and ``fsck``, in a plain repository, a bare one, and from a linked
    worktree of each. :func:`anchored` makes the file on the host before any
    mount names it, and :func:`rooted` pins every directory between these
    holds and the mount enclosing them, the git directory among them, so
    none of them can be moved from under the host.

    A linked worktree's pointer and administrative files are held with them,
    which costs one thing: ``git worktree remove``, ``move`` and ``repair``
    of *this* checkout from inside the session, since each rewrites or
    unlinks a file held here. Its siblings keep theirs writable — removing a
    sibling from inside is ordinary work — and that is the residual: a
    sibling's pointer rewritten from here is a configuration the host reads
    at its next git command in that sibling.
    """
    layout = repository_layout(checkout)
    anchors = [
        layout.common / "config",
        layout.common / "hooks",
        layout.common / "commondir",
    ]
    pointers = (
        [layout.private / "commondir", layout.private / "gitdir", checkout / ".git"]
        if layout.linked()
        else []
    )
    return Lease(read_only=same_path([*anchors, *pointers]))


def anchored(checkout: Path) -> None:
    """Make on the host what :func:`held_repository` mounts, or refuse a redirected one.

    A bind whose source is missing refuses the whole container, so the
    ``commondir`` naming the directory itself is written here when absent,
    and a ``hooks/`` directory made where ``git init`` was told not to make
    one. A ``commondir`` naming anywhere else in a repository's own git
    directory is the redirection itself, left by a session that was not held
    at the time, and holding it read-only would keep it: refused, with the
    file named, for the operator to remove on the host. So is a linked
    worktree whose administrative directory is not among its repository's
    worktrees, which is the other shape the same redirection takes.
    """
    layout = repository_layout(checkout)
    if layout.linked() and layout.private.parent != layout.common / "worktrees":
        raise ValueError(
            f"{checkout} reads its git configuration from {layout.common}, "
            f"which does not list {layout.private} among its worktrees. A "
            f"`commondir` or `.git` pointer was rewritten; repair it on the "
            "host with `git worktree repair`, or remove a planted "
            "`commondir`, and launch again."
        )
    commondir = layout.common / "commondir"
    if commondir.exists() and commondir.read_text(encoding="utf-8").splitlines() != [
        "."
    ]:
        raise ValueError(
            f"{commondir} points this repository's git configuration somewhere "
            "else. A repository's own git directory names itself there or has "
            "no such file; remove it on the host and launch again."
        )
    if not commondir.exists():
        commondir.write_text(".\n", encoding="utf-8")
    (layout.common / "hooks").mkdir(exist_ok=True)


def worker_lease(worktree: Path) -> Lease:
    """The mounts that confine one worker to the tree it was given.

    The arrangement :func:`lease_for` carries, at the level it is
    actually true at. Taken when a worker starts rather than when a session
    does, it covers the checkouts that exist by then -- which is every
    worktree a run leases, the population a launch-time table misses
    entirely. Nothing about the shape differs; only when it is computed, and
    for whom.

    Three nested modes rather than two flat ones: this worktree writable,
    every sibling read-only, and the shared administrative directory writable
    with each sibling's own entry read-only inside it, alongside the shared
    `config` and `hooks/`. The directory is writable so a new worktree's entry
    can be created beside the others -- without which no worker can cut a
    worktree -- and those two are not carried along with it because a worker
    needs the directory to admit a new child, never that file rewritten or
    that hook armed. A human-owned path is not held either, for the reason
    :func:`lease_for` gives: the policy asks about a write to one, and a
    mount cannot.
    """
    layout = repository_layout(worktree)
    writable = [worktree]
    # Read-only in every layout, for the reason :func:`lease_for` records at
    # the same line: `config` names programs the host runs and `hooks/` holds
    # them, and no step of the mandated workflow writes either.
    read_only = [
        layout.common / "config",
        layout.common / "hooks",
        *sibling_worktrees(worktree),
    ]
    if layout.linked():
        # The shared directory is mounted writable as a whole, with each
        # sibling's administrative entry punched read-only back over it -- so
        # every one stays present and unwritable, which is what keeps
        # `worktree prune` from removing it. Each entry rather than the
        # `worktrees/` directory holding them, because a read-only directory
        # refuses two different acts and only one of them was the subject:
        # rewriting an entry that is already there endangers a sibling, and
        # creating a new one beside them endangers nobody. Held read-only,
        # the second goes with the first and no worker in a container can
        # cut a worktree at all. That nesting is the whole arrangement, and
        # `Sandbox.declared_mounts` is what holds it up: it emits mounts
        # parent before child, so a read-only hole is applied after the
        # writable base it sits in instead of being shadowed by it.
        #
        # `config` above is a hole of exactly that kind, and the one that
        # matters most: the rest of these entries protect a sibling's
        # bookkeeping, while that one protects the host's shell.
        read_only += [
            entry
            for entry in sorted((layout.common / "worktrees").iterdir())
            if entry != layout.private
        ]
        writable += [
            layout.common,
            layout.private,
        ]
    else:
        writable.append(layout.common)
    return resolved(same_path(writable), same_path(read_only))


def in_repository(path: Path) -> bool:
    """Whether git answers for this directory at all.

    Asked rather than assumed, because not everything worth reaching is a
    checkout: a directory of reference material registered for access is a
    plain bind, and putting it through the worktree arrangement would only
    ask git about a place git knows nothing of.
    """
    try:
        repository_layout(path)
    except sh.ErrorReturnCode:
        return False
    return True


def demoted(lease: Lease) -> Lease:
    """This lease with nothing writable, for a root declared read-only.

    Its shared git directory goes read-only along with the rest, which costs
    the commands that take a lockfile beside the file they write -- `git
    config`, an index refresh -- and that is what read-only means here rather
    than an oversight. A root nobody may write is one whose repository state
    nobody may move either, and the alternative is a mode that refuses the
    file while admitting the thing that rewrites it.
    """
    return Lease(read_only={**lease.writable, **lease.pinned, **lease.read_only})


def accessible_lease(root: AccessibleRoot) -> Lease:
    """The mounts one declared root needs, whatever kind of directory it is.

    A checkout gets the whole arrangement :func:`lease_for` builds, and the
    reason is the same one that forces same-path mounting: a linked
    worktree's `.git` is a file holding an absolute `gitdir:` pointer, so a
    bind of the working copy alone hands the session a checkout pointing at a
    path that is not there. That is a broken repository rather than a
    boundary, and it is debugged as one.

    The siblings matter here more than they do at home, not less. `git gc`
    runs `git worktree prune`, which deletes the administrative state of any
    worktree whose directory has gone missing -- so a session that could see
    one checkout of somebody else's repository and none of the others would
    remove their entries as ordinary housekeeping, in a repository nobody in
    this session owns.
    """
    lease = (
        lease_for(root.path)
        if in_repository(root.path)
        else Lease(writable=same_path([root.path]))
    )
    return lease if root.writable else demoted(lease)


def fleet_lease(
    worktree: Path,
    accessible: list[AccessibleRoot] | None = None,
) -> Lease:
    """This worktree's lease, plus every root the project declared reachable.

    A root already covered by this worktree's own lease is dropped rather
    than mounted twice: a registration naming a sibling of this repository,
    or a checkout kept inside it, is already leased, and saying so again
    hands the engine two mounts at one target for it to settle by order.

    A root that is not there is skipped rather than declared. A bind mount
    whose source does not exist is one the engine refuses the whole container
    for, so a registration somebody moved would take the session down instead
    of costing its own reachability -- which is the only thing it should
    cost.
    """
    own = lease_for(worktree)
    return merged(
        [
            own,
            *[
                accessible_lease(root)
                for root in accessible or []
                if root.path.exists() and not own.covers(root.path)
            ],
        ]
    )


def hold_worktree_pruning(worktree: Path) -> bool:
    """Stop `git gc` deleting the administrative state of unseen worktrees.

    The third guard, and the one that does not depend on getting the mounts
    exactly right. `gc.worktreePruneExpire` decides how long a worktree whose
    directory has gone missing keeps its entry; set to never, a worker that
    somehow cannot see a sibling still cannot cause its removal.

    Written to the shared configuration, so it protects every worktree of the
    repository rather than only the one that set it. Reports whether it took:
    a repository nobody here may configure is a reason to say so, not a
    reason to fail a launch that is otherwise fine.
    """
    try:
        git("-C", str(worktree), "config", "gc.worktreePruneExpire", "never")
        return True
    except sh.ErrorReturnCode:
        return False


def hold_pruning_across(worktrees: list[Path]) -> list[Path]:
    """Arm the prune guard in every repository given, and name the refusals.

    Once per repository rather than once per launch, because a lease
    spans repositories nobody in this session owns: a `git gc` inside the
    boundary reaches their administrative state through the same shared
    directory it reaches this one's, and the mount guards only hold while the
    mounts are exactly right. This one holds when they are not.

    A path git does not answer for is neither armed nor reported. Nothing
    there has administrative state to lose, and listing it would make a
    directory of reference material read as a repository this failed on.
    """
    return [
        worktree
        for worktree in worktrees
        if in_repository(worktree) and not hold_worktree_pruning(worktree)
    ]
