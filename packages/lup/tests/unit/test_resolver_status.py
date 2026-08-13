"""Answering a run's liveness from its directory, where /proc cannot be read."""

from pathlib import Path

from pydantic import TypeAdapter

from lup.channels.stream import Stream
from lup.resolver.state import ResolverStateRepository
from lup.resolver.status import run_status


def test_an_unheld_run_reads_as_not_running(tmp_path: Path) -> None:
    repository = ResolverStateRepository(tmp_path, "quiet")
    repository.root.mkdir(parents=True)
    (repository.root / ".run.lock").write_text("", encoding="utf-8")

    assert not repository.held()


def test_a_held_run_reads_as_running(tmp_path: Path) -> None:
    """The lock is the liveness answer, and it answers across processes.

    `ps` and `pgrep` cannot: under a sandbox `/proc` is PID-isolated, so
    they list nothing outside the current shell and a healthy long-running
    run is indistinguishable from one that died.
    """
    repository = ResolverStateRepository(tmp_path, "busy")

    with repository.exclusive():
        # A second reader of the same run directory, which is what a status
        # command is. Same process here; the flock is what a separate one
        # would meet too.
        assert ResolverStateRepository(tmp_path, "busy").held()

    assert not ResolverStateRepository(tmp_path, "busy").held()


def test_a_run_that_does_not_exist_says_so_rather_than_answering(
    tmp_path: Path,
) -> None:
    """Silence and "no such run" were indistinguishable, and one is wrong.

    A session in a worktree with no `.lup` read an empty listing as "zero
    pending, so my answer promoted", and reported that. It happened to be
    true; nothing in the output supported it.
    """
    status = run_status(ResolverStateRepository(tmp_path, "absent"), "absent")

    assert not status.exists
    assert "no such run" in status.verdict()


def test_a_log_s_last_record_is_read_without_its_whole_length(tmp_path: Path) -> None:
    """A resolver journal reaches tens of megabytes inside a single run."""
    adapter: TypeAdapter[dict[str, int]] = TypeAdapter(dict[str, int])
    stream = Stream(tmp_path / "log.jsonl", adapter)
    for index in range(500):
        stream.append({"seq": index})

    assert stream.last() == {"seq": 499}
    assert stream.last(window=64) == {"seq": 499}


def test_an_empty_log_has_no_last_record(tmp_path: Path) -> None:
    adapter: TypeAdapter[dict[str, int]] = TypeAdapter(dict[str, int])

    assert Stream(tmp_path / "missing.jsonl", adapter).last() is None
