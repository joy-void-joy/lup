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
each entry read-only used to be a third: siblings are mounted so they exist,
and `gc.worktreePruneExpire` is set to never. The third is not missed,
because it only ever answered for a directory that was present anyway.

**What the shared directory being writable costs.** It holds `config`, and a
worker that cannot write `config` cannot cut a worktree at all, so it is
mounted read-write and only `worktrees/` is held back. That is a deliberate
exposure and not a small one: `core.hooksPath`, `alias.*`,
`credential.helper` and the `merge.*.driver` family all name programs git
runs, and a worker that sets one has arranged to execute code on the host at
the operator's next git command in any worktree of this repository. Nothing
in the mount table stops that -- `hooks/` is writable too, and holding it
read-only would only move the same reach one key sideways. The guard is the
semantic policy, which holds an approval question against those keys by
name; this module is not the thing standing in the way, and should not be
read as though it were.

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

from pathlib import Path

import sh
from pydantic import BaseModel, Field

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

    def covers(self, path: Path) -> bool:
        """Whether this lease says anything at all about a path."""
        return any(
            path == root or root in path.parents
            for root in [*self.writable, *self.read_only]
        )


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


def resolved(writable: dict[Path, str], read_only: dict[Path, str]) -> Lease:
    """One path, one mode, settled toward writable.

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
    be applied in. Exact paths only: a read-only entry *inside* a writable
    one is the nesting this whole arrangement rests on, and survives.
    """
    return Lease(
        writable=writable,
        read_only={
            path: inside for path, inside in read_only.items() if path not in writable
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


def lease_for(worktree: Path, human_owned: list[Path] | None = None) -> Lease:
    """The mounts one session needs over the repository it works in.

    Every checkout of this repository writable, the shared administrative
    directory with them, and the paths the project declared its author owns
    held read-only inside. Siblings are mounted rather than left out for the
    reason the module docstring gives -- absent, they are what `git worktree
    prune` deletes the administrative state of -- and writable for the reason
    it gives beside that.

    ``human_owned`` are paths inside the checkout the project already
    declared its author owns; they come back read-only here rather than being
    listed a second time. That is the whole point of taking them: a path
    added to that declaration becomes unwritable inside a container without
    anybody remembering there was a second list to update.
    """
    layout = repository_layout(worktree)
    writable = [worktree, *sibling_worktrees(worktree)]
    read_only: list[Path] = []
    if layout.linked():
        # The shared directory is mounted writable as a whole, with nothing
        # punched back over it: every sibling's administrative entry stays
        # present, which is the guard that matters, and `worktree prune`
        # removes an entry for a directory that has gone rather than one it
        # can see. Holding each entry read-only bought the second half of
        # that and cost the ability to remove a worktree at all -- `git
        # worktree remove` unlinks the entry, so a read-only one refuses the
        # removal with an errno about a filesystem.
        #
        # Writable rather than read-only because `config` lives here, and a
        # worker that cannot write it cannot cut a worktree or record a base
        # branch: git takes a `config.lock` beside the file for every write,
        # so a read-only directory refuses the lock rather than the file, and
        # reports it as a lock it cannot take on a file nobody is holding.
        #
        # This is an accepted exposure, chosen rather than overlooked. A
        # writable `config` lets a worker set `core.hooksPath`, `alias.*`,
        # `credential.helper` or a `merge.*.driver`, every one of which runs
        # on the host at the operator's next git command in any worktree of
        # this repository; `hooks/` is writable alongside it for the same
        # reason, a read-only one moving that reach one key sideways rather
        # than closing it. What guards this is the semantic policy, which
        # holds an approval question against those keys by name -- so the
        # barrier here is a judgement, and the mount table is not pretending
        # to be one.
        writable += [
            layout.common,
            layout.private,
        ]
    else:
        writable.append(layout.common)
    read_only += [
        owned
        for owned in (worktree / path for path in human_owned or [])
        if owned.exists()
    ]
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
    return Lease(read_only={**lease.writable, **lease.read_only})


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
    human_owned: list[Path] | None = None,
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
    own = lease_for(worktree, human_owned)
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

    Once per repository rather than once per launch, because a lease now
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
