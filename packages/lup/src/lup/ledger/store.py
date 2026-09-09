# lup: ignore[constant-declaration]
# The directory names here are where every worktree of one repository writes
# one DAG. Two processes that spelled them differently would keep two
# ledgers, so they are an identity of this layout rather than a caller's
# choice.
"""Where one repository's notes live, outside every worktree that writes them.

The whole of the answer to a ledger that forks. A store kept inside a
checkout is a store per branch: eight worktrees diverge for days, and
reconciling them afterwards is a script somebody writes once, races against
live sessions, and never re-runs — which is how a claim keeps a label its
evidence stopped supporting while the journal records that the evidence
landed.

So there is one store and no seam to get wrong. The address is the shared git
directory, which every worktree of one clone resolves to the same path and
which sits outside all of them: a branch cannot change what a reader sees, and
removing a worktree does not take the notes with it. :mod:`lup.coordination`
keeps its roster at the same address for the same reason.

The store is **untracked live state**. Notes accumulate as work happens and
nobody reviews a diff of them; ``dev ledger snapshot`` commits the tree to a
branch of its own when somebody wants it preserved, which keeps the record out
of the history of the code it is about.
"""

from pathlib import Path

from lup.workspace.edition import shared_git_directory

STORE_DIR = "lup"
LEDGER_DIR = "ledger"
JOURNAL_FILE = "journal.jsonl"
BLOBS_DIR = "blobs"


def ledger_root(root: Path) -> Path:
    """The one directory every worktree of *root*'s repository records into.

    Derived rather than configured, because a path a project could set is a
    path two of its worktrees can be set differently for — and the failure
    that produces is silence, with both sessions writing and neither reading
    what the other wrote.

    A path in no repository answers for itself through
    :func:`~lup.workspace.edition.shared_git_directory`, so a caller outside a
    clone gets somewhere to write rather than an exception about git.
    """
    return shared_git_directory(root) / STORE_DIR / LEDGER_DIR
