"""Tracing a symbol in a checkout that snapshots itself before every command.

The snapshots are parentless commits holding the whole tree, so the pickaxe
reads every file in one as an addition and matches every symbol the checkout
holds. What is pinned here is that the trace answers with the commits that
actually touched the symbol, that it keeps answering across unmerged
branches, and that every snapshot still holds everything it recorded.
"""

from pathlib import Path

import pytest

from lup.devtools.dev.history import SNAPSHOT_REFS, commits_matching
from lup.execution.shell import git
from lup.policy.assets.host import undo_snapshot


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A repository whose history mentions one symbol exactly once."""
    git("-C", str(tmp_path), "init", "-q", "-b", "main")
    git("-C", str(tmp_path), "config", "user.email", "test@example.invalid")
    git("-C", str(tmp_path), "config", "user.name", "Test")
    (tmp_path / "shelf.py").write_text("def unmistakable() -> int:\n    return 1\n")
    git("-C", str(tmp_path), "add", "-A")
    git("-C", str(tmp_path), "commit", "-qm", "carry the symbol")
    return tmp_path


def pickaxe(checkout: Path, text: str) -> list[str]:
    """What the hand-typed search answers, snapshots and all."""
    return git.lines(
        "-C", str(checkout), "log", "--all", "--format=%H", f"-S{text}", _ok_code=[0, 1]
    )


def test_snapshots_do_not_bury_the_commit_that_matched(checkout: Path) -> None:
    """The trace answers with the one commit; the raw search answers with all."""
    for reason in ("ls", "rm -rf .", "grep unmistakable shelf.py"):
        (checkout / "scratch.txt").write_text(reason, encoding="utf-8")
        undo_snapshot(checkout, reason)
    found = commits_matching(checkout, "unmistakable")
    assert [hit.subject for hit in found] == ["carry the symbol"]
    assert len(pickaxe(checkout, "unmistakable")) == 4


def test_every_snapshot_keeps_what_it_recorded(checkout: Path) -> None:
    """Excluding a ref from a traversal takes nothing out of it."""
    reference = undo_snapshot(checkout, "rm -rf .")
    commits_matching(checkout, "unmistakable")
    subject = git.out("-C", str(checkout), "log", "-1", "--format=%s", reference)
    assert subject.strip() == "lup undo: rm -rf ."


def test_an_unmerged_branch_is_still_traced(checkout: Path) -> None:
    """Every ref but the snapshots, which is what `--all` was reached for."""
    git("-C", str(checkout), "checkout", "-q", "-b", "sidetrack")
    (checkout / "other.py").write_text("unmistakable = 2\n", encoding="utf-8")
    git("-C", str(checkout), "add", "-A")
    git("-C", str(checkout), "commit", "-qm", "mention it elsewhere")
    git("-C", str(checkout), "checkout", "-q", "main")
    found = commits_matching(checkout, "unmistakable")
    assert {hit.subject for hit in found} == {
        "carry the symbol",
        "mention it elsewhere",
    }


def test_a_path_narrows_the_trace(checkout: Path) -> None:
    """A pathspec answers about one part of the tree."""
    assert commits_matching(checkout, "unmistakable", paths=[Path("shelf.py")])
    assert not commits_matching(checkout, "unmistakable", paths=[Path("absent.py")])


def test_a_regex_reads_the_text_as_a_pattern(checkout: Path) -> None:
    """`--regex` asks where a shape was touched rather than a literal."""
    assert commits_matching(checkout, "unmis.akable", regex=True)
    assert not commits_matching(checkout, "unmis.akable")


def test_the_excluded_pattern_follows_the_writer() -> None:
    """The namespace is derived, so an exclusion cannot stop excluding."""
    assert SNAPSHOT_REFS == "refs/lup/undo/*"
