"""Behavior tests for `lup-devtools dev delete`.

A branch's worktree is removed before the branch itself, and git refuses to
remove one holding modified or untracked files. These pin that --force reaches
that removal too, so the flag disposes of a branch whatever its worktree holds,
and that without it a dirty worktree is left standing.
"""

from pathlib import Path

import pytest
import sh
import typer

from lup_template.devtools.dev import branches
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
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    with pytest.raises(typer.Exit):
        branches.delete_branch("feature", dry_run=False, force=False)

    assert "feature" in branch_names(repo)
    survivor = repo.parent / "feature" / "file.txt"
    assert survivor.read_text(encoding="utf-8") == "dirty\n"


def test_dry_run_names_the_worktree_disposition(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    branches.delete_branch("feature", dry_run=True, force=True)

    assert "Remove worktree" in capsys.readouterr().out
    assert "feature" in branch_names(repo)
