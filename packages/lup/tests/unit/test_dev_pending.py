"""The pending-change reader: porcelain framing and masked-path exclusion."""

import os
from pathlib import Path

import lup.devtools.dev.pending as pending


def test_parses_index_and_worktree_columns() -> None:
    entries = pending.parse_porcelain(
        "?? notes/mock/run/\0 M packages/lup/src/lup/app.py\0"
    )

    assert [
        (entry.index_status, entry.worktree_status, entry.path) for entry in entries
    ] == [
        ("?", "?", "notes/mock/run/"),
        (" ", "M", "packages/lup/src/lup/app.py"),
    ]


def test_staged_reflects_the_index_column() -> None:
    entries = pending.parse_porcelain("A  added.py\0 M unstaged.py\0?? new.py\0")

    assert [entry.staged for entry in entries] == [True, False, False]


def test_rename_origin_is_not_a_separate_change() -> None:
    entries = pending.parse_porcelain("R  dest.py\0origin.py\0 M other.py\0")

    assert [entry.path for entry in entries] == ["dest.py", "other.py"]


def test_paths_with_spaces_survive_nul_framing() -> None:
    entries = pending.parse_porcelain("?? notes/a file with spaces.json\0")

    assert [entry.path for entry in entries] == ["notes/a file with spaces.json"]


def test_regular_files_and_directories_are_not_masked(tmp_path: Path) -> None:
    regular = tmp_path / "regular.py"
    regular.write_text("x = 1")

    assert not pending.is_masked(regular)
    assert not pending.is_masked(tmp_path)


def test_special_files_are_masked(tmp_path: Path) -> None:
    fifo = tmp_path / "masked.rc"
    os.mkfifo(fifo)

    assert pending.is_masked(fifo)


def test_deleted_paths_stay_reported(tmp_path: Path) -> None:
    assert not pending.is_masked(tmp_path / "deleted.py")


def test_masked_path_is_dropped_but_real_work_survives(tmp_path: Path) -> None:
    """The sandbox case: a masked dotfile reported beside genuine pending work."""
    (tmp_path / "real.py").write_text("x = 1")
    os.mkfifo(tmp_path / ".zshrc")

    result = pending.exclude_masked(
        pending.parse_porcelain("?? .zshrc\0?? real.py\0"),
        tmp_path,
        "feature",
    )

    assert [entry.path for entry in result.entries] == ["real.py"]
    assert result.masked == [".zshrc"]
