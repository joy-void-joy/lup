"""A harness run is findable by id, in the default root and in a declared one.

A launch mode names where its records are kept, so a run id alone does not say
which root holds it. These pin that the tree this package writes is the tree it
reads: the ``<provider>/<run_id>`` shape stays here rather than in every caller
that wants a run back from its id.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from lup.workspace.history import iter_run_dirs
from lup.workspace.paths import configure, harness_runs_path, project_root

ORIGINAL_ROOT = project_root()

RUN_ID = "20260825_023457_898418_claude_15f67aad"


@pytest.fixture
def isolated_root(tmp_path: Path) -> Iterator[Path]:
    configure(root=tmp_path, version="1.2.3")
    yield tmp_path
    configure(root=ORIGINAL_ROOT)


def record(root: Path, provider: str, run_id: str) -> Path:
    """Mint the directory a launch writes, without starting one."""
    run = root / provider / run_id
    run.mkdir(parents=True, exist_ok=True)
    (run / "observable.jsonl").write_text("", encoding="utf-8")
    return run


class TestRunDirReader:
    def test_a_run_in_the_default_root_is_found(self, isolated_root: Path) -> None:
        del isolated_root
        expected = record(harness_runs_path(), "claude", RUN_ID)

        assert list(iter_run_dirs(RUN_ID)) == [expected]

    def test_a_run_under_a_declared_root_is_found(self, isolated_root: Path) -> None:
        declared = isolated_root / "notes" / "research" / "sessions"
        expected = record(declared, "claude", RUN_ID)

        assert list(iter_run_dirs(RUN_ID, roots=[declared])) == [expected]

    def test_declared_roots_replace_the_default_rather_than_extend_it(
        self, isolated_root: Path
    ) -> None:
        """Which roots hold runs is the adopter's to state, including by omission.

        Prepending the default would read as a courtesy and behave as a rule:
        a caller could add a root but never decline one.
        """
        declared = isolated_root / "notes" / "research" / "sessions"
        record(harness_runs_path(), "claude", RUN_ID)
        declared_run = record(declared, "codex", RUN_ID)

        assert list(iter_run_dirs(RUN_ID, roots=[declared])) == [declared_run]

    def test_the_default_is_taken_by_naming_it(self, isolated_root: Path) -> None:
        """Composing with the default stays available — it is just not implied."""
        declared = isolated_root / "notes" / "research" / "sessions"
        default_run = record(harness_runs_path(), "claude", RUN_ID)
        declared_run = record(declared, "codex", RUN_ID)

        found = list(iter_run_dirs(RUN_ID, roots=[harness_runs_path(), declared]))

        assert found == [default_run, declared_run]

    def test_the_provider_level_is_searched_rather_than_assumed(
        self, isolated_root: Path
    ) -> None:
        """The same run id reaches a reader from whichever runtime opened it."""
        del isolated_root
        expected = record(harness_runs_path(), "codex", RUN_ID)

        assert list(iter_run_dirs(RUN_ID)) == [expected]

    def test_an_absent_run_yields_nothing(self, isolated_root: Path) -> None:
        del isolated_root
        record(harness_runs_path(), "claude", "some-other-run")

        assert list(iter_run_dirs(RUN_ID)) == []

    def test_every_run_is_listed_when_no_id_is_given(self, isolated_root: Path) -> None:
        del isolated_root
        first = record(harness_runs_path(), "claude", "run-a")
        second = record(harness_runs_path(), "codex", "run-b")

        assert sorted(iter_run_dirs()) == sorted([first, second])

    def test_a_missing_root_is_not_an_error(self, isolated_root: Path) -> None:
        assert list(iter_run_dirs(RUN_ID, roots=[isolated_root / "nowhere"])) == []

    def test_a_root_named_twice_yields_its_run_once(self, isolated_root: Path) -> None:
        """A caller counting results decides whether one id names one run.

        Repetition read as ambiguity refuses the run that was found, so the
        same tree named twice has to answer the way naming it once does.
        """
        del isolated_root
        expected = record(harness_runs_path(), "claude", RUN_ID)
        twice = [harness_runs_path(), harness_runs_path()]

        assert list(iter_run_dirs(RUN_ID, roots=twice)) == [expected]

    def test_a_root_reached_by_another_spelling_yields_its_run_once(
        self, isolated_root: Path
    ) -> None:
        """Identity is the resolved path, not the spelling that reached it."""
        del isolated_root
        expected = record(harness_runs_path(), "claude", RUN_ID)
        spelled = harness_runs_path() / "claude" / ".." / ".."

        assert list(iter_run_dirs(RUN_ID, roots=[harness_runs_path(), spelled])) == [
            expected
        ]

    def test_a_run_under_a_symlinked_root_is_yielded_once(
        self, isolated_root: Path
    ) -> None:
        """A symlink is a second name for one directory, not a second run."""
        expected = record(harness_runs_path(), "claude", RUN_ID)
        linked = isolated_root / "linked-runs"
        linked.symlink_to(harness_runs_path(), target_is_directory=True)

        assert list(iter_run_dirs(RUN_ID, roots=[harness_runs_path(), linked])) == [
            expected
        ]

    def test_listing_every_run_yields_each_one_once(self, isolated_root: Path) -> None:
        del isolated_root
        first = record(harness_runs_path(), "claude", "run-a")
        second = record(harness_runs_path(), "codex", "run-b")
        twice = [harness_runs_path(), harness_runs_path()]

        assert sorted(iter_run_dirs(roots=twice)) == sorted([first, second])
