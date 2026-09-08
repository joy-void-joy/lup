# lup: ignore[constant-declaration]
# The directory names here are where every worktree of one repository meets.
# Two processes that spelled them differently would coordinate with nobody, so
# they are an identity of this layout rather than a choice a caller can make.
"""Where one repository's peers find each other, whichever worktree they are in.

A cohort a process opens lives wherever that process put it, which is right
for a population one run assembled and wrong for the population that is
*everybody working on this repository*. Those peers were never assembled: they
are sessions in different worktrees, started by different people at different
times, and the only thing they share is the repository.

So the repository is the meeting place, and the address of the meeting place
is the shared git directory. Every worktree of one clone resolves it to the
same path — that is what makes it shared — and it sits outside all of them, so
a branch cannot change what a peer reads and a worktree being removed does not
take the roster with it. lup already keeps ``edition.json`` and ``branches``
there for the same reason.

Different repositories are structurally disjoint, which is the property this
buys: there is no global registry to collide in, no daemon to elect, and no
way for a session in one project to appear on another project's roster.
"""

from pathlib import Path

from lup.workspace.edition import shared_git_directory

STORE_DIR = "lup"
COORDINATION_DIR = "coordination"


def coordination_root(root: Path) -> Path:
    """The one directory every worktree of *root*'s repository coordinates in.

    Derived rather than configured. A path a project could set is a path two
    of its worktrees can be configured differently for, and the failure that
    produces is silence: both sessions work, neither is on the other's roster,
    and nothing anywhere reports a mismatch.

    A path in no repository answers for itself, through
    :func:`~lup.workspace.edition.shared_git_directory` — a caller outside a
    clone gets somewhere to write rather than an exception about git.
    """
    return shared_git_directory(root) / STORE_DIR / COORDINATION_DIR
