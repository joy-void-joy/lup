"""The migrations gate reads its base where a clone has one, and says when it has none.

Measured on every push since the gate was written: a CI clone holds the one
branch it checks out, the base detector exits the process on finding no other
local branch, and that exit took the whole report with it -- the log held one
line and an exit code, naming no check. The gate now judges the integration
branch from the release branch, a feature branch from its own base, reads the
remote's copy where only the remote carries it, and reports a checkout with no
base at all as skipped.
"""

from pathlib import Path

import pytest
import sh

from lup.devtools.dev.migrations import gate_base
from tests.unit.repos import commit_file, initialized_repo


def out(work: Path, *arguments: str) -> str:
    return str(sh.Command("git")("-C", str(work), *arguments, _tty_out=False)).strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`main` with one commit, `dev` one commit ahead of it, standing on `dev`."""
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "base.txt", "base\n", "chore: base")
    git("checkout", "-q", "-b", "dev")
    commit_file(git, work, "more.txt", "more\n", "feat: more")
    monkeypatch.chdir(work)
    return work


def test_the_integration_branch_is_judged_from_the_release_branch(repo: Path) -> None:
    assert gate_base("dev") == out(repo, "rev-parse", "main")


def test_a_feature_branch_is_judged_from_its_own_base(repo: Path) -> None:
    sh.Command("git")("-C", str(repo), "checkout", "-q", "-b", "topic", _tty_out=False)
    commit_file(
        initialized_repo(repo, repo.parent / "no-hooks"),
        repo,
        "t.txt",
        "t\n",
        "feat: t",
    )

    assert gate_base("dev") == out(repo, "rev-parse", "dev")


def test_a_clone_holding_one_branch_reads_the_remote_copy_of_its_base(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What a CI checkout is: one branch, and the base only as `origin/main`."""
    clone = tmp_path / "clone"
    sh.Command("git")(
        "clone", "-q", "--branch", "dev", str(repo), str(clone), _tty_out=False
    )
    monkeypatch.chdir(clone)

    assert out(clone, "branch", "--format=%(refname:short)") == "dev"
    assert gate_base("dev") == out(repo, "rev-parse", "main")


def test_no_base_at_all_is_a_reading_rather_than_an_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "alone"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "only.txt", "only\n", "chore: only")
    monkeypatch.chdir(work)

    assert gate_base("dev") is None
