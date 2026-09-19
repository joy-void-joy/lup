"""A bun workspace the new tree has no copy of is not a restore to attempt.

The workspaces a creation restores are read from the project the command was
run in, while `--base` cuts the tree from any branch — so the two can disagree
about the layout. Measured, not imagined: `worktree create -b dev`, run from a
checkout that vendors the library, cut a tree from a branch that obtains it as
a link instead, and the step went looking for `packages/lup/web` in a tree that
holds no `packages/` at all. `bun` was handed a working directory that does not
exist, which `sh` reports by raising on the `chdir` rather than on the command;
that is neither the failed exit `restore_dependencies` converts nor the
`RuntimeError` the step catches, so it escaped every handler and took down a
creation whose `required()` is already `False`. The worktree and its
environment were already on disk, so what the traceback interrupted was a
worktree that had nothing left to want.
"""

from pathlib import Path

from lup.devtools.dev.worktree import RestoredWorkspace


def test_a_workspace_absent_from_the_new_tree_is_nothing_to_restore(
    tmp_path: Path,
) -> None:
    """A declared workspace the tree does not hold leaves the step done.

    Not "done" as a convenience: there is no `package.json` and no lockfile
    there, so nothing describes dependencies that could be behind anything.
    """
    worktree = tmp_path / "tree"
    worktree.mkdir()
    step = RestoredWorkspace(worktree=worktree, workspace=Path("packages/lup/web"))
    assert step.satisfied()


def test_a_workspace_the_tree_holds_is_still_restored_when_behind(
    tmp_path: Path,
) -> None:
    """The step it exists for: a workspace present, its dependencies absent.

    Guards the fix against answering "satisfied" for every workspace, which
    would read the same on a creation that skipped the restore it owed.
    """
    worktree = tmp_path / "tree"
    workspace = worktree / "packages" / "lup" / "web"
    workspace.mkdir(parents=True)
    (workspace / "bun.lock").write_text("", encoding="utf-8")
    step = RestoredWorkspace(worktree=worktree, workspace=Path("packages/lup/web"))
    assert not step.satisfied()
