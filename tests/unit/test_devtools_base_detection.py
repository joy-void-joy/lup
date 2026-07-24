"""Behavior tests for base-branch recording and detection.

Worktree creation records its base in ``branch.<name>.lup-base``; detection
prefers that record over topological guessing. Topology alone cannot recover
the creation point — once branches share tips or the parent merges on, every
candidate looks alike and the nearest one wins regardless of where the branch
was really cut.
"""

from pathlib import Path

import pytest
import sh
import typer

from lup_template.devtools.dev import branches, worktree


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    work.mkdir()
    hooks = tmp_path / "no-hooks"
    hooks.mkdir()
    git = sh.Command("git").bake(
        "-C",
        str(work),
        "-c",
        "commit.gpgsign=false",
        "-c",
        f"core.hooksPath={hooks}",
        _tty_out=False,
    )
    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (work / "file.txt").write_text("base\n", encoding="utf-8")
    git("add", "file.txt")
    git("commit", "-m", "chore: base")
    return work


def repo_git(work: Path) -> sh.Command:
    return sh.Command("git").bake("-C", str(work), _tty_out=False)


def commit_file(work: Path, name: str) -> None:
    git = repo_git(work)
    (work / name).write_text(name, encoding="utf-8")
    git("add", name)
    git("commit", "-m", f"feat: {name}")


def test_recorded_base_resolves_what_topology_cannot(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = repo_git(repo)
    git("branch", "feature")
    git("switch", "-c", "topic", "feature")
    git("config", "branch.topic.lup-base", "feature")
    commit_file(repo, "t1.txt")

    monkeypatch.chdir(repo)
    candidate = branches.detect_base_branch("topic")
    assert candidate.name == "feature"
    assert candidate.source == "recorded"


def test_topology_tie_stays_ambiguous_without_a_record(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = repo_git(repo)
    git("branch", "feature")
    git("switch", "-c", "topic", "feature")
    commit_file(repo, "t1.txt")

    monkeypatch.chdir(repo)
    with pytest.raises(typer.Exit):
        branches.detect_base_branch("topic")


def test_stale_record_falls_back_to_guessing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = repo_git(repo)
    git("switch", "-c", "feature")
    commit_file(repo, "f1.txt")
    git("switch", "-c", "topic")
    git("config", "branch.topic.lup-base", "gone")
    commit_file(repo, "t1.txt")

    monkeypatch.chdir(repo)
    candidate = branches.detect_base_branch("topic")
    assert candidate.name == "feature"
    assert candidate.source == "guessed"


def test_worktree_create_records_the_base(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree_dir = tmp_path / "tree"
    tree_dir.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.setattr(worktree, "get_tree_dir", lambda: tree_dir)

    worktree.create("wt-topic", no_sync=True, no_copy_data=True, base_branch=None)

    recorded = repo_git(repo)("config", "--get", "branch.wt-topic.lup-base")
    assert str(recorded).strip() == "main"
    candidate = branches.detect_base_branch("wt-topic")
    assert candidate.name == "main"
    assert candidate.source == "recorded"
