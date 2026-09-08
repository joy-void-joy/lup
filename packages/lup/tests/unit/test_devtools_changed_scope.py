"""Which files the narrow check answers about, and which it must not miss.

The scope is the whole of what makes a narrowed run trustworthy. Ruff and
Pyright each answer about the files they are handed, so the run is exactly as
honest as the list — and the two ways a list goes wrong pull in opposite
directions. Naming a file that is gone turns a narrowed run into an error
about its own arguments; *not* naming a file that changed reports "clean"
about code nobody read, which is the failure this whole lane exists to avoid
committing.
"""

from pathlib import Path

import pytest
import sh

from lup.devtools.dev.check import changed_python_files


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout with one commit, stood in as the working directory.

    The scope is read with git run against the current directory, the way the
    command reads it, rather than against a path passed in — so the fixture
    moves the process instead of parameterising the subject.
    """
    work = tmp_path / "repo"
    work.mkdir()
    git = sh.Command("git").bake("-C", str(work), _tty_out=False)
    git("init", "-b", "main")
    git("config", "user.email", "scope@example.com")
    git("config", "user.name", "scope")
    (work / "kept.py").write_text("kept = 1\n", encoding="utf-8")
    (work / "prose.md").write_text("prose\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    monkeypatch.chdir(work)
    return work


def test_a_file_written_and_never_added_is_still_checked(repo: Path) -> None:
    """The half `git diff` does not report, and the half most worth reading.

    A module written five minutes ago is what its author is asking about. A
    scope built from tracked changes alone would leave it out and answer
    "clean" over the one file in the tree nobody has read.
    """
    (repo / "fresh.py").write_text("fresh = 1\n", encoding="utf-8")

    assert changed_python_files("HEAD") == ["fresh.py"]


def test_a_changed_file_that_is_not_python_is_left_out(repo: Path) -> None:
    """Ruff and Pyright are asked about Python, so the scope is Python."""
    (repo / "prose.md").write_text("changed prose\n", encoding="utf-8")

    assert changed_python_files("HEAD") == []


def test_a_deleted_file_is_not_named_to_a_checker(repo: Path) -> None:
    """A path that is gone would fail the run on its own argument list.

    `git diff` reports a deletion as a change, which is right for a note gate
    reading history and wrong for a checker that has to open the file.
    """
    (repo / "kept.py").unlink()

    assert changed_python_files("HEAD") == []


def test_a_tracked_edit_and_a_new_file_are_both_in_scope(repo: Path) -> None:
    """The ordinary case: something edited, something added, both answered for."""
    (repo / "kept.py").write_text("kept = 2\n", encoding="utf-8")
    (repo / "fresh.py").write_text("fresh = 1\n", encoding="utf-8")

    assert changed_python_files("HEAD") == ["fresh.py", "kept.py"]


def test_a_tree_that_changed_nothing_scopes_nothing(repo: Path) -> None:
    """Empty is a real answer, and the caller reports it rather than checking all."""
    assert changed_python_files("HEAD") == []
