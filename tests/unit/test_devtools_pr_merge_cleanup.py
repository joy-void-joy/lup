"""Behavior tests for the branch cleanup `lup-devtools dev pr merge` performs.

`gh pr merge --delete-branch` runs a plain `git branch -d`, which refuses while
any worktree holds the branch. In a tree of worktrees that is every branch, so
each merge reported a cleanup failure and left both the branch and its checkout
behind for the caller to clear by hand. These pin that the merge now cleans up
through the deletion path that removes the worktree first, and that a cleanup
which cannot finish is still reported rather than raised — the merge already
happened, and re-running it would fail against a PR GitHub already closed.
"""

from pathlib import Path

import pytest
import sh

from lup.devtools.dev import pr
from tests.unit.repos import git_in, initialized_repo


@pytest.fixture
def merged(tmp_path: Path) -> Path:
    """A repo whose merged branch still has the worktree that built it."""
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    (work / "file.txt").write_text("base\n", encoding="utf-8")
    git("add", "file.txt")
    git("commit", "-m", "chore: base")

    git("worktree", "add", str(tmp_path / "feature"), "-b", "feature")
    feature = git_in(tmp_path / "feature", tmp_path / "no-hooks")
    (tmp_path / "feature" / "extra.txt").write_text("extra\n", encoding="utf-8")
    feature("add", "extra.txt")
    feature("commit", "-m", "feat: extra")

    git("merge", "--no-edit", "feature")
    return work


def branch_names(work: Path) -> list[str]:
    out = sh.Command("git")(
        "-C", str(work), "branch", "--format=%(refname:short)", _tty_out=False
    )
    return str(out).split()


def test_a_merged_branch_goes_even_though_a_worktree_holds_it(
    merged: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(merged)

    pr.cleanup_merged_branch("feature")

    assert "feature" not in branch_names(merged)
    assert not (tmp_path / "feature").exists()


def test_the_plain_delete_gh_runs_would_have_refused(
    merged: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The precondition the fix exists for, so the test above cannot pass idly."""
    monkeypatch.chdir(merged)

    with pytest.raises(sh.ErrorReturnCode):
        sh.Command("git")("-C", str(merged), "branch", "-d", "feature", _tty_out=False)


def test_a_branch_that_is_already_gone_is_left_alone(
    merged: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(merged)

    pr.cleanup_merged_branch("never-existed")

    assert "feature" in branch_names(merged)


def test_a_cleanup_that_cannot_finish_reports_instead_of_raising(
    merged: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting the branch you are standing on is refused, and stays refused.

    Raising here would report a merge that happened as a command that failed,
    which is the confusion the whole cleanup path is arranged to avoid.
    """
    monkeypatch.chdir(merged.parent / "feature")

    pr.cleanup_merged_branch("feature")

    assert "feature" in branch_names(merged)
    assert "still here" in capsys.readouterr().err
