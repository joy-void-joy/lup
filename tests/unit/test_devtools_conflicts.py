"""Behavior tests for `lup-devtools dev conflict` during a real rebase.

Builds a throwaway git repo with a genuine rebase conflict and pins that
the conflict commands use REBASE_HEAD (MERGE_HEAD and CHERRY_PICK_HEAD do
not exist during a rebase): status must list both sides' commits and audit
must diff the theirs side without reporting a partial result.
"""

import json
from pathlib import Path

import pytest
import sh

from lup_template.devtools.dev import conflicts
from tests.unit.repos import commit_file, initialized_repo


@pytest.fixture
def rebase_conflict_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    git = initialized_repo(repo, tmp_path / "no-hooks")

    def commit_conflicting(content: str, message: str) -> None:
        commit_file(git, repo, "file.txt", content, message)

    commit_conflicting("base\n", "chore: base")
    git("checkout", "-b", "feature")
    commit_conflicting("feature\n", "feat: feature change")
    git("checkout", "main")
    commit_conflicting("main\n", "fix: main change")
    git("checkout", "feature")
    try:
        git("rebase", "main")
    except sh.ErrorReturnCode:
        pass

    return repo


def test_detects_rebase_state(
    rebase_conflict_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(rebase_conflict_repo)
    assert conflicts.detect_conflict_state() == "rebase"


def test_status_uses_rebase_head_and_lists_both_sides(
    rebase_conflict_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(rebase_conflict_repo)

    conflicts.conflict_status(as_json=True)

    data = json.loads(capsys.readouterr().out)
    assert data["operation"] == "rebase"
    assert data["theirs_ref"] == "REBASE_HEAD"
    assert data["conflicted_files"] == ["file.txt"]
    assert any("feature change" in line for line in data["theirs_commits"])
    assert any("main change" in line for line in data["ours_commits"])


def test_audit_diffs_theirs_side_during_rebase(
    rebase_conflict_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(rebase_conflict_repo)

    conflicts.conflict_audit(["file.txt"], as_json=True)

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["files"][0]["partial"] is False
    assert "partial" not in captured.err
