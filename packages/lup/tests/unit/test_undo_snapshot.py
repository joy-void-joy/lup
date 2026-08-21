"""The safety net the permission dispatcher takes before it lets a command run.

The whole case for relaxing a lattice is that a mistake can be put back, so
what is pinned here is the two ways this stops being true silently. It can
capture the wrong thing -- `git stash create` misses exactly the file `rm -rf`
destroys -- and it can stop the command it was protecting, which is worse than
not existing, because a net that breaks the working case is the first thing
somebody turns off.
"""

from pathlib import Path

from lup.devtools.utils import git
from lup.policy.assets.host import undo_namespace, undo_snapshot

import pytest


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A real repository with one commit, since this is git all the way down."""
    git("-C", str(tmp_path), "init", "-q", "-b", "main")
    git("-C", str(tmp_path), "config", "user.email", "test@example.invalid")
    git("-C", str(tmp_path), "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("original\n", encoding="utf-8")
    git("-C", str(tmp_path), "add", "-A")
    git("-C", str(tmp_path), "commit", "-qm", "first")
    return tmp_path


def held(checkout: Path, reference: str, path: str) -> str:
    """What one snapshot holds at a path, read back out of the object store."""
    return git.out("-C", str(checkout), "cat-file", "-p", f"{reference}:{path}").strip()


def test_a_file_written_and_not_yet_added_survives(checkout: Path) -> None:
    """The case `git stash create` misses, and the reason this exists at all.

    A file written thirty seconds ago and not staged is exactly what
    `rm -rf src/` destroys and exactly when somebody reaches for undo.
    """
    (checkout / "new.txt").write_text("just written\n", encoding="utf-8")
    assert held(checkout, undo_snapshot(checkout, "rm -rf ."), "new.txt") == (
        "just written"
    )


def test_the_snapshot_does_not_stage_what_it_captured(checkout: Path) -> None:
    """A net that quietly rewrote the index would break what it was protecting.

    The snapshot runs in front of a command a human may be in the middle of
    composing a commit for. Staging everything as a side effect would change
    what their next `git commit` records, which is a destruction of its own.
    """
    (checkout / "new.txt").write_text("just written\n", encoding="utf-8")
    undo_snapshot(checkout, "rm -rf .")
    assert git.out("-C", str(checkout), "diff", "--cached", "--name-only") == ""


def test_the_snapshot_leaves_the_working_tree_alone(checkout: Path) -> None:
    """The other half of the same promise, asked of the files rather than the index."""
    (checkout / "tracked.txt").write_text("edited\n", encoding="utf-8")
    undo_snapshot(checkout, "git reset --hard")
    assert (checkout / "tracked.txt").read_text() == "edited\n"


def test_an_ignored_file_is_left_out(checkout: Path) -> None:
    """A stated limit rather than a bug: capturing them measured 592 MB.

    Which is why `git clean -fdx` keeps asking. It is the one command whose
    purpose is destroying precisely what this does not hold, so the lattice
    cannot hand it the recoverability argument.
    """
    (checkout / "ignored").mkdir()
    (checkout / "ignored" / "big.bin").write_text("x", encoding="utf-8")
    reference = undo_snapshot(checkout, "git clean -fdx")
    listed = git.out("-C", str(checkout), "ls-tree", "-r", "--name-only", reference)
    assert "ignored/big.bin" not in listed


def test_the_snapshot_lands_outside_every_ref_a_human_reads(checkout: Path) -> None:
    """A branch listing, a push and a fetch must all stay unaware of these."""
    reference = undo_snapshot(checkout, "probe")
    assert reference.startswith(f"{undo_namespace()}/")
    assert git.out("-C", str(checkout), "branch", "--list").strip() == "* main"


def test_a_checkout_that_cannot_answer_yields_no_snapshot(tmp_path: Path) -> None:
    """Silence, not an exception. This runs in front of a command somebody asked for.

    A checkout mid-merge, a locked index and a directory that is not a
    repository are all reasons a snapshot cannot be taken, and none of them is
    a reason to stop the command it was standing in front of.
    """
    assert undo_snapshot(tmp_path / "not-a-repository", "probe") == ""


def test_no_root_yields_no_snapshot() -> None:
    """A hook is promised no working directory, so this has to be an answer."""
    assert undo_snapshot(None, "probe") == ""


def test_the_environment_the_snapshot_needs_does_not_replace_the_rest(
    checkout: Path,
) -> None:
    """Pointing GIT_INDEX_FILE elsewhere must not drop PATH and HOME with it.

    A replaced environment fails for a reason that has nothing to do with what
    was asked, and the failure is silent here by design -- so it would read as
    "this checkout cannot be snapshotted" forever.
    """
    (checkout / "new.txt").write_text("present\n", encoding="utf-8")
    assert undo_snapshot(checkout, "probe") != ""


def test_a_command_that_changed_nothing_leaves_no_new_snapshot(
    checkout: Path,
) -> None:
    """Why this can afford to run before *every* command rather than some.

    Git addresses content, so an unchanged tree writes a byte-identical tree
    object -- and naming the ref after that tree makes the second write an
    overwrite rather than an addition. Measured against the alternative: a
    trigger that fired on the classifier's verdict produced sixty refs in one
    session, fifty-seven of them in front of a `grep`.
    """
    (checkout / "new.txt").write_text("present\n", encoding="utf-8")
    undo_snapshot(checkout, "one")
    undo_snapshot(checkout, "two")
    assert len(git.lines("-C", str(checkout), "for-each-ref", undo_namespace())) == 1


def test_the_surviving_note_is_the_latest_thing_about_to_happen(
    checkout: Path,
) -> None:
    """What a reader looks for is the snapshot from before the thing that broke.

    Sixty reads between two edits collapse to one ref, and the note on it has
    to be the last command rather than the first, or the listing points at the
    wrong moment while holding the right tree.
    """
    (checkout / "new.txt").write_text("present\n", encoding="utf-8")
    undo_snapshot(checkout, "grep something")
    reference = undo_snapshot(checkout, "rm -rf src")
    subject = git.out("-C", str(checkout), "log", "-1", "--format=%s", reference)
    assert subject.strip() == "lup undo: rm -rf src"


def test_a_changed_tree_gets_a_snapshot_of_its_own(checkout: Path) -> None:
    """Dedup must not swallow a state worth returning to."""
    first = undo_snapshot(checkout, "before")
    (checkout / "new.txt").write_text("written since\n", encoding="utf-8")
    assert undo_snapshot(checkout, "after") != first


def test_an_earlier_state_survives_the_states_that_followed_it(
    checkout: Path,
) -> None:
    """The point of keeping one ref per state rather than only the newest."""
    (checkout / "new.txt").write_text("first\n", encoding="utf-8")
    reference = undo_snapshot(checkout, "before the edit")
    (checkout / "new.txt").write_text("second\n", encoding="utf-8")
    undo_snapshot(checkout, "after the edit")
    assert held(checkout, reference, "new.txt") == "first"
