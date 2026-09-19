"""The runtime sandbox's mount targets stay out of `git status`.

The runtime's own sandbox binds an empty file read-only over each dotfile a
command could plant persistence in, and where the file is absent bubblewrap
creates the target itself on the host: zero bytes, mode 0444, untracked, and
matched by no ignore rule. They were found mid-sweep in both worktrees of a
repository, one `git add -A` away from a commit over harness-owned paths.

Nothing here writes them, so nothing here can stop them; what a launch can do
is take away the harm, and `info/exclude` is where -- per clone, unversioned,
read by every worktree. The signature is what the tests pin: a placeholder is
told from a file somebody meant by being untracked, empty, and exactly the
mode bubblewrap gives a target it created.
"""

from pathlib import Path

import pytest
import sh

from lup.devtools.harness.preflight import exclude_sandbox_placeholders
from tests.unit.repos import commit_file, initialized_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    return work


def placeholder(work: Path, name: str) -> None:
    """One target as bubblewrap leaves it: empty, and readable by everyone only."""
    target = work / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    target.chmod(0o444)


def status(work: Path) -> list[str]:
    reported = sh.Command("git")(
        "-C", str(work), "status", "--porcelain", _tty_out=False
    )
    return str(reported).splitlines()


def test_a_placeholder_is_excluded_and_an_ordinary_file_is_not(repo: Path) -> None:
    placeholder(repo, ".bashrc")
    placeholder(repo, ".claude/agents")
    (repo / "notes.md").write_text("mine\n", encoding="utf-8")

    added = exclude_sandbox_placeholders(repo)

    assert added == [".bashrc", ".claude/agents"]
    assert status(repo) == ["?? notes.md"]


def test_a_second_launch_adds_nothing(repo: Path) -> None:
    """Said once, so a line that changes no decision is not repeated."""
    placeholder(repo, ".gitconfig")
    exclude_sandbox_placeholders(repo)

    assert exclude_sandbox_placeholders(repo) == []
    assert status(repo) == []


def test_an_empty_file_somebody_can_write_is_not_a_placeholder(repo: Path) -> None:
    """The mode is the signature: an empty file of one's own keeps its report."""
    (repo / "empty.txt").touch()

    assert exclude_sandbox_placeholders(repo) == []
    assert status(repo) == ["?? empty.txt"]
