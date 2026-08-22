"""The library page's package roster must match the package it describes.

The roster used to promise "every remaining top-level entry" while omitting
six of them — `actors` among them, four commits after it was added — because
a prose table is a claim about the tree that nothing reads the tree to check.
These tests are the other half of the fix: `roster_table` walks the tree, and
here is the proof that it refuses both directions of drift rather than only
happening to agree today.
"""

from pathlib import Path

import pytest

from lup.devtools.harness.content.docs.library import (
    LIBRARY,
    LIBRARY_PACKAGE,
    Roster,
    RosterEntry,
)


def library_at(root: Path, *names: str) -> Path:
    """A throwaway library tree carrying one module per name."""
    subtree = root / LIBRARY_PACKAGE.name
    subtree.mkdir(parents=True)
    for name in names:
        (subtree / f"{name}.py").write_text('"""A module."""\n', encoding="utf-8")
    return subtree


def test_the_shipped_roster_describes_every_entry_the_library_carries() -> None:
    described = [entry.package for entry in LIBRARY.entries]

    assert sorted(described) == sorted(LIBRARY.owed())


def test_the_roster_walks_the_package_it_was_imported_from() -> None:
    """The tree read is the reader's own copy, not a path under their checkout.

    What made the page unusable downstream: a project taking lup as a
    dependency has no `packages/lup/src/lup` beneath its root, so a walk
    resolved against the checkout failed generation outright rather than
    describing the library that project actually runs.
    """
    assert LIBRARY.source == LIBRARY_PACKAGE
    assert (LIBRARY.source / "actors").is_dir()


def test_the_roster_renders_one_row_per_described_package() -> None:
    table = LIBRARY.table()

    assert len(table.rows) == len(LIBRARY.entries)
    assert table.headers == ["Package", "Solves"]


def test_a_package_no_row_describes_fails_generation(tmp_path: Path) -> None:
    source = library_at(tmp_path, "described", "forgotten")
    roster = Roster(
        source=source,
        entries=[RosterEntry(package="described", solves="The one that is written.")],
    )

    with pytest.raises(ValueError, match="forgotten"):
        roster.table()


def test_a_row_describing_a_deleted_package_fails_generation(tmp_path: Path) -> None:
    source = library_at(tmp_path, "surviving")
    roster = Roster(
        source=source,
        entries=[
            RosterEntry(package="surviving", solves="Still here."),
            RosterEntry(package="removed", solves="Deleted last week."),
        ],
    )

    with pytest.raises(ValueError, match="removed"):
        roster.table()


def test_a_tiered_package_is_not_owed_a_roster_row(tmp_path: Path) -> None:
    empty = Roster(entries=[])
    tiered = [entry.package for entry in empty.tiered]
    source = library_at(tmp_path, *tiered, "ordinary")
    roster = Roster(
        source=source,
        entries=[RosterEntry(package="ordinary", solves="The only row owed.")],
    )

    assert len(roster.table().rows) == 1


def test_a_dotted_directory_is_owed_no_row(tmp_path: Path) -> None:
    """A tool's scratch directory beside the source is not a package.

    The roster walks the filesystem rather than git, so anything left beside
    the library is visible to it — and a checkout that has run an agent
    carries `.claude` there, gitignored and untracked. Python cannot import a
    dotted name, so no roster could ever owe it a row; generation failing to
    ask what an editor's scratch directory solves is the bug this pins.
    """
    source = library_at(tmp_path, "ordinary")
    (source / ".claude" / ".cc-writes").mkdir(parents=True)
    (source / ".venv").mkdir()
    roster = Roster(
        source=source,
        entries=[RosterEntry(package="ordinary", solves="The only row owed.")],
    )

    assert roster.owed() == ["ordinary"]
    assert len(roster.table().rows) == 1
