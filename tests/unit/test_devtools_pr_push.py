"""Behavior tests for how `dev pr push` gives a branch its remote.

`git push -u` records the relationship by writing `branch.<name>.remote` and
`branch.<name>.merge` into the repository's shared config. Where that file
cannot be written the flag fails without saying so: the push happens, git
prints `set up to track`, and the command exits 0 having recorded nothing —
so everything downstream reads a branch that was published as one that never
was, and whatever retries on that reading retries forever.

The destination is stated as a refspec instead, which needs no config write
at all, and what `-u` was for is recorded beside the branch's other facts.
"""

from pathlib import Path

import pytest
import sh

from lup.devtools.dev import branches, pr, records
from lup.harness.process import LocalProcessLauncher
from tests.unit.repos import commit_file, initialized_repo


class SilentGh:
    """A `gh` that answers no pull requests, so no forge is reached.

    The push is the subject here; whether a PR happens to exist is a second
    question this must not depend on the network to answer.
    """

    def out(self, *args: str) -> str:
        del args
        return "[]"


@pytest.fixture
def published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout on a topic branch with work to send, and a remote to send it to."""
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    sh.Command("git")("init", "--bare", str(tmp_path / "origin.git"), _tty_out=False)
    git("remote", "add", "origin", str(tmp_path / "origin.git"))
    git("push", "origin", "main")
    git("checkout", "-q", "-b", "topic")
    commit_file(git, work, "mine.txt", "mine\n", "feat: mine")
    monkeypatch.setattr(pr, "gh", SilentGh())
    monkeypatch.chdir(work)
    return work


def shared_config(repo: Path) -> str:
    """The file whose keys name programs git runs on the host."""
    return (repo / ".git" / "config").read_text(encoding="utf-8")


def test_a_push_records_the_remote_it_sent_to(published: Path) -> None:
    """What `-u` claimed to write, written where lup can read it back."""
    pr.push(force=False, as_json=True)

    assert records.recorded_upstream("topic", published) == "origin/topic"


def test_a_push_leaves_the_shared_config_exactly_as_it_was(published: Path) -> None:
    """The whole point: publishing a branch stops needing a writable config.

    Compared as text rather than by asking for the two tracking keys, because
    a push that wrote anything at all into this file is a push that needed it
    writable, whichever key it chose.
    """
    before = shared_config(published)

    pr.push(force=False, as_json=True)

    assert shared_config(published) == before


def test_a_forced_push_records_the_remote_too(published: Path) -> None:
    """Both spellings reach the same recording, since either may be the first."""
    before = shared_config(published)

    pr.push(force=True, as_json=True)

    assert records.recorded_upstream("topic", published) == "origin/topic"
    assert shared_config(published) == before


def test_the_branch_actually_lands_on_the_remote(published: Path) -> None:
    """A refspec that records nothing would be no better than the flag.

    The remote-tracking ref is asked for as well as the remote's own branch,
    because everything that measures freshness counts against
    `refs/remotes/origin/<name>` and a push that moved only the far side
    leaves that count unanswerable.
    """
    pr.push(force=False, as_json=True)

    git = sh.Command("git").bake("-C", str(published), _tty_out=False)
    assert "refs/heads/topic" in str(git("ls-remote", "--heads", "origin", "topic"))
    assert str(git("rev-parse", "refs/remotes/origin/topic")).strip()


def test_the_recorded_remote_answers_where_git_tracks_nothing(
    published: Path,
) -> None:
    """The reader that used to ask `branch.<name>.merge` and now asks the record.

    Freshness is measured against the remote a branch answers to. Asked of
    git's tracking configuration alone, a branch published by a refspec
    answers nothing, and a checkout that is behind its own remote reports
    itself level with it.
    """
    pr.push(force=False, as_json=True)

    remotes = branches.tracked_remotes(LocalProcessLauncher(), published)

    assert remotes.upstream == "origin/topic"


def test_a_branch_nobody_pushed_still_answers_to_nothing(published: Path) -> None:
    """The case that must not change: no push is still no remote."""
    remotes = branches.tracked_remotes(LocalProcessLauncher(), published)

    assert remotes.upstream == ""
