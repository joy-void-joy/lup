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
    """With no tag to read, the branch is where the last release got to."""
    assert gate_base("dev") == out(repo, "rev-parse", "main")


def test_a_release_cut_and_not_yet_landed_is_judged_from_its_tag(repo: Path) -> None:
    """The window the release itself opens, between the tag and the branch.

    Cutting a release tags the integration branch and empties the declared
    breaks into the changelog; the release branch only moves once that lands.
    Read from the branch in between, every break the release had just shipped
    came back undeclared — against a list that is empty exactly then, by
    design. The tag is the release, so the tag is what the window is measured
    from.
    """
    sh.Command("git")(
        "-C", str(repo), "tag", "-a", "v0.4.0", "-m", "0.4.0", _tty_out=False
    )
    commit_file(
        initialized_repo(repo, repo.parent / "no-hooks"),
        repo,
        "after.txt",
        "after\n",
        "feat: after the release",
    )

    assert gate_base("dev") == out(repo, "rev-parse", "v0.4.0^{commit}")
    assert gate_base("dev") != out(repo, "rev-parse", "main")


def test_a_tag_that_is_not_a_release_is_not_read_as_one(repo: Path) -> None:
    """The prefix is the project's, so another tagging convention is left alone."""
    sh.Command("git")(
        "-C", str(repo), "tag", "-a", "nightly-7", "-m", "nightly", _tty_out=False
    )

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
