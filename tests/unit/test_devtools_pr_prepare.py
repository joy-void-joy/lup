"""A forge merges the prepared head without any per-clone merge driver."""

import json
from pathlib import Path

import pytest
import sh

from lup.devtools.git.prepare import prepare
from tests.unit.repos import initialized_repo, commit_file


def generated(root: Path) -> None:
    sources = {path.name: path.read_text() for path in root.glob("*.txt")}
    for runtime in (".claude", ".codex"):
        directory = root / runtime
        directory.mkdir(exist_ok=True)
        (directory / ".lup-ownership.json").write_text(json.dumps(sources))
        (directory / "policy.py").write_text(f"sources = {sources!r}\n")


@pytest.fixture
def divergent(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    git = initialized_repo(root, tmp_path / "no-hooks")
    commit_file(
        git,
        root,
        ".gitattributes",
        ".claude/** merge=lup-ownership\n.codex/** merge=lup-ownership\n",
        "base",
    )
    git("checkout", "-b", "feature")
    (root / "feature.txt").write_text("feature work")
    generated(root)
    git("add", "-A")
    git("commit", "-m", "feature")
    git("checkout", "main")
    (root / "base.txt").write_text("base work")
    generated(root)
    git("add", "-A")
    git("commit", "-m", "base advanced")
    git("checkout", "feature")
    return root


def test_prepared_head_merges_without_custom_drivers(divergent: Path) -> None:
    git = sh.Command("git").bake("-C", str(divergent))
    with pytest.raises(sh.ErrorReturnCode):
        git(
            "-c",
            "merge.lup-ownership.driver=false",
            "merge-tree",
            "--write-tree",
            "main",
            "feature",
        )
    result = prepare("main", divergent, lambda: generated(divergent))
    assert result.committed
    git("merge-base", "--is-ancestor", result.base_commit, result.head)
    git(
        "-c",
        "merge.lup-ownership.driver=false",
        "merge-tree",
        "--write-tree",
        "main",
        "feature",
    )
    for runtime in (".claude", ".codex"):
        proof = json.loads((divergent / runtime / ".lup-ownership.json").read_text())
        assert proof == {"base.txt": "base work", "feature.txt": "feature work"}
        compile((divergent / runtime / "policy.py").read_text(), "policy.py", "exec")
    assert not str(git("status", "--porcelain")).strip()
    assert not prepare("main", divergent, lambda: generated(divergent)).committed


def test_preparation_refuses_pending_work_before_merging(divergent: Path) -> None:
    (divergent / "unsaved.txt").write_text("keep this")
    with pytest.raises(RuntimeError, match="Commit pending"):
        prepare("main", divergent, lambda: generated(divergent))
    assert not (divergent / ".git/MERGE_HEAD").exists()
    assert (divergent / "unsaved.txt").read_text() == "keep this"


def test_generation_failure_keeps_uncommitted_merge_for_repair(divergent: Path) -> None:
    git = sh.Command("git").bake("-C", str(divergent))
    before = str(git("rev-parse", "HEAD"))

    def failed() -> None:
        raise RuntimeError("generator needs repair")

    with pytest.raises(RuntimeError, match="generator needs repair"):
        prepare("main", divergent, failed)
    assert str(git("rev-parse", "HEAD")) == before
    assert (divergent / ".git/MERGE_HEAD").exists()
    assert (divergent / "feature.txt").read_text() == "feature work"
    assert (divergent / "base.txt").read_text() == "base work"


def test_source_conflicts_remain_repairable_and_do_not_generate(
    divergent: Path,
) -> None:
    git = sh.Command("git").bake("-C", str(divergent))
    git("checkout", "main")
    (divergent / "feature.txt").write_text("conflicting base work")
    generated(divergent)
    git("add", "-A")
    git("commit", "-m", "conflicting source")
    git("checkout", "feature")

    def must_not_generate() -> None:
        pytest.fail("Unresolved source must not reach generation")

    with pytest.raises(RuntimeError, match="Base merge needs repair") as refusal:
        prepare("main", divergent, must_not_generate)
    # The refusal carries what git said, and this is where a reader needs it:
    # a merge that conflicted and a merge that never started both reach the
    # same exception, and only one of them leaves a file to repair. Asserting
    # the empty list alone reported `assert '' == 'feature.txt'` and left
    # nothing to act on.
    unmerged = str(git("diff", "--name-only", "--diff-filter=U")).strip()
    assert unmerged == "feature.txt", str(refusal.value)
    assert "<<<<<<<" in (divergent / "feature.txt").read_text()
    for runtime in (".claude", ".codex"):
        compile((divergent / runtime / "policy.py").read_text(), "policy.py", "exec")
