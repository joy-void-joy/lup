"""Behavior tests for `lup-devtools dev delete`.

Deletion is preflighted: every precondition is evaluated before anything is
touched, so a dry run reports what the real path went on to check, and a run
that cannot finish changes nothing. These pin both halves — that a blocked
step is named as blocked rather than annotated with the flag that was passed,
that a refusal leaves the checkout standing without having attempted its
removal, and that a worktree stranded by an earlier failure is pruned rather
than left for the caller to discover.
"""

import shutil
from pathlib import Path

import pytest
import sh
import typer

from lup.devtools.dev import branches
from tests.unit.repos import commit_file, initialized_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    git("worktree", "add", str(tmp_path / "feature"), "-b", "feature")
    (tmp_path / "feature" / "file.txt").write_text("dirty\n", encoding="utf-8")
    return work


def branch_names(work: Path) -> list[str]:
    out = sh.Command("git")(
        "-C", str(work), "branch", "--format=%(refname:short)", _tty_out=False
    )
    return str(out).split()


def test_force_removes_a_worktree_holding_changes(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    branches.delete_branch("feature", dry_run=False, force=True)

    assert "feature" not in branch_names(repo)
    assert not (repo.parent / "feature").exists()


def test_without_force_a_dirty_worktree_survives(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    with pytest.raises(typer.Exit):
        branches.delete_branch("feature", dry_run=False, force=False)

    assert "feature" in branch_names(repo)
    survivor = repo.parent / "feature" / "file.txt"
    assert survivor.read_text(encoding="utf-8") == "dirty\n"

    # The refusal precedes the removal rather than reporting it after the fact:
    # the destructive step is never attempted, so there is nothing to warn about.
    err = capsys.readouterr().err
    assert "Refusing to delete feature" in err
    assert "worktree removal failed" not in err


def test_dry_run_reports_a_dirty_worktree_as_blocked(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    branches.delete_branch("feature", dry_run=True, force=False)

    out = capsys.readouterr().out
    assert "Remove worktree" in out
    assert "blocked: holds 1 modified, 0 untracked" in out
    assert "feature" in branch_names(repo)


def test_dry_run_under_force_says_what_it_would_discard(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    branches.delete_branch("feature", dry_run=True, force=True)

    assert "force: discards 1 modified, 0 untracked" in capsys.readouterr().out
    assert "feature" in branch_names(repo)


def test_dry_run_reports_an_unmerged_branch_as_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    git("checkout", "-b", "solo")
    commit_file(git, work, "extra.txt", "extra\n", "feat: extra")
    git("checkout", "main")
    monkeypatch.chdir(work)

    branches.delete_branch("solo", dry_run=True, force=False)

    assert "blocked: branch is unmerged" in capsys.readouterr().out
    assert "solo" in branch_names(work)


def test_a_stranded_worktree_is_pruned_and_the_branch_deleted(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The state an interrupted removal leaves behind: the checkout is gone but
    # git still registers it, which by itself makes the branch undeletable.
    shutil.rmtree(repo.parent / "feature")
    monkeypatch.chdir(repo)

    branches.delete_branch("feature", dry_run=False, force=False)

    assert "Pruned stranded worktree" in capsys.readouterr().out
    assert "feature" not in branch_names(repo)
