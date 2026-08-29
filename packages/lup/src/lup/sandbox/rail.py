"""Confining a worker to its own worktree, by mounting rather than by judging.

Worktrees of one repository share an object store and a branch set, so from
any of them `git -C ../other commit` writes to another's branch and
`cp x ../other/src/` overwrites another's file. Nothing separates them. The
guidance says to work in your own tree, and that holds because an agent reads
and complies -- which is prose, not a rail.

Every attempt to build the rail out of *judgement* runs into the same wall.
The policy would have to decide, from a command's text, where it will act:
that is undecidable the moment a Makefile, an `xargs`, or a script that shells
out is involved, and `cd ../other && git commit` already walks past it. An OS
boundary does not predict. It observes the write and refuses it, whatever
route reached the syscall.

So the lease is a mount fact. Absolute paths stay identical on both sides --
forced rather than chosen, because a linked worktree's `.git` is a file
holding an absolute `gitdir:` pointer -- and only the modes vary: this
worktree read-write, every sibling read-only, the shared admin directory
read-write with its `worktrees/` directory read-only inside it, and this
worktree's own entry read-write again within that.

**The trap that makes read-only siblings load-bearing.** The obvious move is
not to mount siblings at all. It is wrong, and quietly so. `git gc` runs
`git worktree prune`, which deletes the admin directory of any worktree whose
`gitdir` target has gone missing. A worker whose container could not see its
siblings would look around, find every one of their directories absent, and
delete their administrative state from the shared repository -- as ordinary
housekeeping, with no error anywhere. Hence three guards rather than one:
siblings are mounted so they exist, `worktrees/` is read-only so only this
worktree's own entry can be written, and `gc.worktreePruneExpire` is set to
never.

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
completely. What the reflog cannot restore is a sibling's *uncommitted* work,
which is exactly what this covers.

Boundary attribution is a prerequisite rather than a follow-on, and
:mod:`lup.sandbox.attribution` is it. A read-only sibling turns a stray write
into `Read-only file system: .../tree/dev/src/foo.py`, and an agent reading
that debugs the filesystem instead of learning it holds a lease. A rail
without attribution is worse than no rail.
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
    """The mounts that confine one worker to this worktree.

    Three nested modes rather than two flat ones: this worktree writable,
    every sibling read-only, and the shared administrative directory writable
    with `worktrees/` read-only inside it and this worktree's own entry
    writable again within that. The shared directory is writable so `config`
    can be written -- without which no worker can cut a worktree -- and the
    comment below records what that deliberately exposes.

    ``human_owned`` are paths inside the checkout the project already
    declared its author owns; they come back read-only here rather than being
    listed a second time. That is the whole point of taking them: a path
    added to that declaration becomes unwritable inside a container without
    anybody remembering there was a second list to update.
    """
    layout = repository_layout(worktree)
    writable = [worktree]
    read_only = list(sibling_worktrees(worktree))
    if layout.linked():
        # The shared directory is mounted writable as a whole, with
        # `worktrees/` punched read-only back over it and this worktree's own
        # entry writable again inside that -- so every sibling's
        # administrative entry stays present and unwritable, which is what
        # keeps `worktree prune` from removing it. That nesting is the whole
        # arrangement, and `Sandbox.declared_mounts` is what holds it up: it
        # emits mounts parent before child, so the read-only hole is applied
        # after the writable base it sits in instead of being shadowed by it.
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
        read_only.append(layout.common / "worktrees")
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
    # One path, one mode. `git worktree list` reports the main worktree, and
    # in a bare layout that directory *is* the shared one -- so the shared
    # directory arrives as its own sibling and would be declared read-only
    # and read-write at once. Both spellings were read-only before this
    # module made the shared directory writable, which is what kept the
    # collision invisible rather than absent. Resolved toward writable
    # because the paths that reach here writable are the ones named
    # deliberately, and toward it here rather than in the engine, where two
    # mounts at one target settle by whichever order they happen to be
    # applied in.
    kept = [path for path in read_only if path not in writable]
    return Lease(writable=same_path(writable), read_only=same_path(kept))


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
