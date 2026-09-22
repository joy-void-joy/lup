"""The cut git logged, and everything it cannot answer for.

lup's own base record is written by lup's own worktree command and by nothing
else, so a branch made with plain git carried no base at all: detection fell
through to topology, and for one task two siblings tied there and the quality
gate refused to run on an ordinary branch.

Git logs the cut itself, in the branch's first reflog entry, and every command
that makes a branch writes it. That is what this reads. It is evidence and not
authority, so what is pinned here is both halves: the answer where git has one,
and an empty answer — unremarkable, never an error — in each of the ways it
has none.
"""

from pathlib import Path

import pytest

from lup.devtools.dev.branches import created_from
from lup.harness.process import LaunchRequest, LocalProcessLauncher


def run_git(cwd: Path, *arguments: str) -> None:
    """Run one git command for a fixture repository, failing on its own stderr.

    Identity per invocation, never `git config` — a persisted setting lands
    in the shared config every worktree of a real repository inherits.
    """
    who = ("-c", "user.email=cut@example.test", "-c", "user.name=Cut Test")
    status = LocalProcessLauncher().launch(
        LaunchRequest(arguments=["git", *who, *arguments], cwd=cwd)
    )
    if status.code != 0:
        raise AssertionError(status.stderr)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A checkout on `dev` with one commit, and a remote holding a copy of it.

    The remote is part of the fixture because a remote-tracking ref is one of
    the spellings a creation entry can carry, and a repository with no remote
    cannot tell that reading from a reading that never had one to try.
    """
    work = tmp_path / "work"
    run_git(tmp_path, "init", "-q", "-b", "dev", str(work))
    run_git(work, "commit", "-q", "--allow-empty", "-m", "base")
    run_git(tmp_path, "init", "-q", "--bare", str(tmp_path / "origin.git"))
    run_git(work, "remote", "add", "origin", str(tmp_path / "origin.git"))
    run_git(work, "push", "-q", "origin", "dev")
    return work


def test_a_branch_switched_into_being_names_what_it_was_cut_from(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_git(repo, "switch", "-q", "-c", "topic", "dev")
    monkeypatch.chdir(repo)

    assert created_from("topic") == "dev"


def test_a_branch_a_worktree_was_cut_for_names_it_too(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command from the report, which wrote no base record of its own.

    `git worktree add -b` is how a branch is made without going through lup,
    and it logs the cut exactly as `git branch` and `git switch -c` do — which
    is what makes a base stop depending on which command cut the branch.
    """
    run_git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "topic", "dev")
    monkeypatch.chdir(repo)

    assert created_from("topic") == "dev"


def test_a_remote_tracking_ref_answers_as_the_branch_it_tracks(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`origin/dev` is somebody's copy of `dev`, and `dev` is the usable name.

    A base is fetched and merged by name, so the answer has to be a branch
    this clone carries. The remote's own prefix is stripped from the list of
    remotes rather than at the first slash: `feat/x` is one branch name.
    """
    run_git(repo, "switch", "-q", "-c", "topic", "origin/dev")
    monkeypatch.chdir(repo)

    assert created_from("topic") == "dev"


def test_a_branch_cut_where_nothing_logged_it_answers_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case that makes this evidence rather than authority.

    `core.logAllRefUpdates` is false without a working tree, so a bare clone
    — which is how a machine holds one project as a git directory with
    worktrees beside it — logs no creation for a branch cut against the git
    directory itself. Measured here by turning the setting off, which is the
    same condition by the same switch.
    """
    run_git(repo, "-c", "core.logAllRefUpdates=false", "branch", "topic", "dev")
    monkeypatch.chdir(repo)

    assert created_from("topic") == ""


def test_a_cut_from_head_names_nothing_a_later_reader_can_measure(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git switch -c topic` logs `Created from HEAD`, which is not a base.

    HEAD named wherever the creating checkout stood, and that is exactly the
    fact a base record exists to preserve — so an entry carrying it is no
    answer and topology is asked instead.
    """
    run_git(repo, "switch", "-q", "-c", "topic")
    monkeypatch.chdir(repo)

    assert created_from("topic") == ""


def test_a_cut_from_a_bare_commit_is_no_base_either(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit is a point, and `pr sync-base` fetches and merges a branch."""
    tip = LocalProcessLauncher().launch(
        LaunchRequest(arguments=["git", "rev-parse", "dev"], cwd=repo)
    )
    run_git(repo, "branch", "topic", tip.stdout.strip())
    monkeypatch.chdir(repo)

    assert created_from("topic") == ""
