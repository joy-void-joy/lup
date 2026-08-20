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

from lup.devtools.harness.content.docs.library import LIBRARY, Roster, RosterEntry
from lup.workspace.paths import project_root


def library_at(root: Path, *names: str) -> Path:
    """A throwaway library tree carrying one module per name."""
    subtree = root / Roster(entries=[]).subtree
    subtree.mkdir(parents=True)
    for name in names:
        (subtree / f"{name}.py").write_text('"""A module."""\n', encoding="utf-8")
    return subtree


def test_the_shipped_roster_describes_every_entry_the_library_carries() -> None:
    described = [entry.package for entry in LIBRARY.entries]

    assert sorted(described) == sorted(LIBRARY.owed(project_root()))


def test_the_roster_renders_one_row_per_described_package() -> None:
    table = LIBRARY.table(project_root())

    assert len(table.rows) == len(LIBRARY.entries)
    assert table.headers == ["Package", "Solves"]


def test_a_package_no_row_describes_fails_generation(tmp_path: Path) -> None:
    library_at(tmp_path, "described", "forgotten")
    roster = Roster(
        entries=[RosterEntry(package="described", solves="The one that is written.")]
    )

    with pytest.raises(ValueError, match="forgotten"):
        roster.table(tmp_path)


def test_a_row_describing_a_deleted_package_fails_generation(tmp_path: Path) -> None:
    library_at(tmp_path, "surviving")
    roster = Roster(
        entries=[
            RosterEntry(package="surviving", solves="Still here."),
            RosterEntry(package="removed", solves="Deleted last week."),
        ]
    )

    with pytest.raises(ValueError, match="removed"):
        roster.table(tmp_path)


def test_a_tiered_package_is_not_owed_a_roster_row(tmp_path: Path) -> None:
    empty = Roster(entries=[])
    tiered = [entry.package for entry in empty.tiered]
    library_at(tmp_path, *tiered, "ordinary")
    roster = Roster(
        entries=[RosterEntry(package="ordinary", solves="The only row owed.")]
    )

    assert len(roster.table(tmp_path).rows) == 1
