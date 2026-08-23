"""Deleting a worktree must not take the only copy of its sessions with it.

The notes directory is ignored unless a repository opts into committing session
data, so a worktree normally holds the sole copy of what its sessions did. That
makes the loss invisible after the fact -- a later reader cannot tell destroyed
evidence from sessions that never ran -- which is why the archive is wired into
the deletion path rather than offered as a step, and why these run the real
deletion instead of mocking it.
"""

from pathlib import Path

import pytest
import typer

from lup.devtools.dev import branches, traces
from tests.unit.repos import commit_file, initialized_repo


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with one linked worktree that has traces to lose."""
    work = tmp_path / "repo"
    git = initialized_repo(work, tmp_path / "no-hooks")
    commit_file(git, work, "file.txt", "base\n", "chore: base")
    git("worktree", "add", "-q", str(tmp_path / "feature"), "-b", "feature")
    monkeypatch.chdir(work)
    monkeypatch.setattr(traces, "notes_path", lambda: work / "notes")
    monkeypatch.setattr(traces, "project_root", lambda: work)
    return work


def record(tmp_path: Path, relative: str, text: str) -> Path:
    """Write one session record inside the linked worktree's notes directory."""
    path = tmp_path / "feature" / "notes" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def trace(tmp_path: Path, relative: str, text: str) -> Path:
    """Write one trace inside the linked worktree's trace store."""
    return record(tmp_path, f"traces/{relative}", text)


def archived(repo: Path, relative: str) -> Path:
    """Where a given trace should land once archived."""
    return traces.archive_root() / "feature" / "traces" / relative


def test_the_archive_is_beyond_the_worktree_it_outlives(repo: Path) -> None:
    assert not traces.archive_root().is_relative_to(repo.parent / "feature")


def test_the_archive_is_where_no_commit_reaches_it(repo: Path) -> None:
    """Inside the common directory, so `git add` can never stage it."""
    assert traces.archive_root().is_relative_to(repo / ".git")


def test_deleting_a_worktree_keeps_its_traces(repo: Path, tmp_path: Path) -> None:
    trace(tmp_path, "0.3.0/logs/run/events.jsonl", "one event\n")

    branches.delete_branch("feature", dry_run=False, force=True)

    kept = archived(repo, "0.3.0/logs/run/events.jsonl")
    assert kept.read_text(encoding="utf-8") == "one event\n"


def test_the_worktree_really_is_gone_afterwards(repo: Path, tmp_path: Path) -> None:
    """The archive is not a substitute for deleting; both have to happen."""
    trace(tmp_path, "0.3.0/logs/run/events.jsonl", "one event\n")

    branches.delete_branch("feature", dry_run=False, force=True)

    assert not (tmp_path / "feature" / "notes").exists()


def test_a_dry_run_says_what_it_would_keep(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trace(tmp_path, "0.3.0/logs/run/events.jsonl", "one event\n")

    branches.delete_branch("feature", dry_run=True, force=False)

    assert "would copy 1 file" in capsys.readouterr().out
    assert not archived(repo, "0.3.0/logs/run/events.jsonl").exists()


def test_a_refused_deletion_leaves_the_traces_where_they_were(
    repo: Path, tmp_path: Path
) -> None:
    """A blocked plan changes nothing, so it must not archive either."""
    trace(tmp_path, "0.3.0/logs/run/events.jsonl", "one event\n")
    (tmp_path / "feature" / "file.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(typer.Exit):
        branches.delete_branch("feature", dry_run=False, force=False)

    assert (tmp_path / "feature" / "notes").exists()
    assert not archived(repo, "0.3.0/logs/run/events.jsonl").exists()


def test_a_worktree_with_no_traces_deletes_without_complaint(
    repo: Path, tmp_path: Path
) -> None:
    branches.delete_branch("feature", dry_run=False, force=True)

    assert not (tmp_path / "feature").exists()


def test_a_second_pass_copies_nothing_again(repo: Path, tmp_path: Path) -> None:
    trace(tmp_path, "0.3.0/logs/run/events.jsonl", "one event\n")
    traces.archive("feature", dry_run=False)

    second = traces.archive("feature", dry_run=False)

    assert second.copied == 0
    assert second.present == 1


def test_an_archived_trace_is_never_overwritten(repo: Path, tmp_path: Path) -> None:
    trace(tmp_path, "0.3.0/logs/run/events.jsonl", "the original\n")
    traces.archive("feature", dry_run=False)
    trace(tmp_path, "0.3.0/logs/run/events.jsonl", "truncated afterwards\n")

    traces.archive("feature", dry_run=False)

    kept = archived(repo, "0.3.0/logs/run/events.jsonl")
    assert kept.read_text(encoding="utf-8") == "the original\n"


def test_the_harness_mirror_is_kept_as_well(repo: Path, tmp_path: Path) -> None:
    """What it mirrors can be inside the worktree too, so both copies go at once.

    The mirror reads as a derived artifact, and one whose source is safe would
    not need keeping. That source is a native CLI's configuration home, and a
    project profile puts it at ``.lup/profiles/`` within the checkout being
    deleted -- which leaves the mirror the only copy that anything keeps.
    """
    record(tmp_path, "harness/claude/run/observable.jsonl", "a launch record\n")

    traces.archive("feature", dry_run=False)

    kept = traces.archive_root() / "feature" / "harness/claude/run/observable.jsonl"
    assert kept.read_text(encoding="utf-8") == "a launch record\n"


def test_a_store_nobody_named_is_kept_by_sitting_where_the_others_do(
    repo: Path, tmp_path: Path
) -> None:
    """Whatever the notes directory grows next is archived without an edit here."""
    record(tmp_path, "feedback_loop/round.md", "a round of analysis\n")

    traces.archive("feature", dry_run=False)

    kept = traces.archive_root() / "feature" / "feedback_loop/round.md"
    assert kept.read_text(encoding="utf-8") == "a round of analysis\n"


def test_a_branch_with_no_worktree_reports_nothing(repo: Path) -> None:
    result = traces.archive("main", dry_run=False)

    assert result.copied == 0
