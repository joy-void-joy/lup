"""Putting a copy of the local half of the store somewhere git will keep it.

The local half is untracked on purpose. Notes accumulate as work happens,
nobody reviews a diff of them, and a note per turn in the history of the code
would make the history of the code unreadable. So preservation is a
deliberate act somebody asks for, not something that happens on every write.
The committed half is already in git and is not copied.

It goes to a branch of its own, sharing no history with the code it is about,
and it is written with plumbing rather than ``git add``: the store sits inside
the git directory, which is in no worktree, so there is nothing for a working
tree to be relative to. A temporary index solves that without disturbing the
index a person may be in the middle of composing.
"""

from pathlib import Path

from lup.execution.shell import git


def snapshot(store: Path, git_dir: Path, branch: str, message: str) -> str:
    """Commit the store's current bytes to *branch*, and return the commit.

    Each snapshot's parent is whatever that branch already pointed at, so the
    branch is a history of the record rather than a series of unrelated
    commits — a reader can ask what the ledger held last week.

    The index is a scratch file that goes away with the call. Writing to the
    repository's own index would stage a person's uncommitted work into a
    commit they did not make, which is the one failure a convenience like this
    must not have.
    """
    index = store.parent / "snapshot.index"
    environment = {"GIT_INDEX_FILE": str(index), "GIT_WORK_TREE": str(store)}
    try:
        git("--git-dir", str(git_dir), "add", "-A", "--", ".", _env=environment)
        tree = str(
            git("--git-dir", str(git_dir), "write-tree", _env=environment)
        ).strip()
    finally:
        index.unlink(missing_ok=True)
    reference = f"refs/heads/{branch}"
    parent = existing_commit(git_dir, reference)
    lineage = ["-p", parent] if parent else []
    commit = str(
        git("--git-dir", str(git_dir), "commit-tree", tree, *lineage, "-m", message)
    ).strip()
    git("--git-dir", str(git_dir), "update-ref", reference, commit)
    return commit


def existing_commit(git_dir: Path, reference: str) -> str:
    """What a ref points at, or the empty string where it points at nothing.

    Empty rather than an exception, because the first snapshot is the case
    with no parent and it is the ordinary one — a branch that does not exist
    yet is what every repository starts from.
    """
    try:
        return str(
            git("--git-dir", str(git_dir), "rev-parse", "--verify", reference)
        ).strip()
    except Exception:
        return ""
