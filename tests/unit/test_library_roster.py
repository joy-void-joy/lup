"""The library page's package roster is read from the package it describes.

The roster used to promise "every remaining top-level entry" while omitting six
of them — `actors` among them, four commits after it was added — because a prose
table is a claim about the tree that nothing reads the tree to check. Walking
the tree fixed the *names*; everything said about them stayed authored, in a
second file, and drifted anyway: the `channels` row named six consumers where
the import graph counts eleven.

So the prose moved to each entry's own docstring and the row is derived from it.
One description of one subject, beside the thing it describes. What that leaves
worth pinning is a walk that reads the wrong tree, and an entry with nothing to
say about itself.
"""

import ast
from pathlib import Path

import pytest

from lup.devtools.harness.content.docs.library import (
    LIBRARY,
    LIBRARY_PACKAGE,
    Roster,
)

DESCRIBED = '"""A summary line.\n\nWhat it solves, at length.\n"""\n'


def library_at(root: Path, *names: str) -> Path:
    """A throwaway library tree carrying one described module per name."""
    subtree = root / LIBRARY_PACKAGE.name
    subtree.mkdir(parents=True)
    for name in names:
        (subtree / f"{name}.py").write_text(DESCRIBED, encoding="utf-8")
    return subtree


def test_every_entry_the_tree_carries_gets_a_row() -> None:
    """Nothing left to keep in step: the rows are the walk."""
    rows = LIBRARY.table().rows

    assert [cell.text for cell, _ in rows] == LIBRARY.owed()


def test_a_row_opens_with_the_entry_s_own_summary_line() -> None:
    """The row is the docstring, not a paraphrase somebody has to maintain."""
    for name in LIBRARY.owed():
        source = LIBRARY.entry_source(name)
        docstring = ast.get_docstring(ast.parse(source.read_text(encoding="utf-8")))
        assert docstring is not None
        summary = docstring.splitlines()[0]

        assert LIBRARY.solves(name).startswith(summary), name


def test_the_roster_walks_the_package_it_was_imported_from() -> None:
    """The tree read is the reader's own copy, not a path under their checkout.

    What made the page unusable downstream: a project taking lup as a
    dependency has no `packages/lup/src/lup` beneath its root, so a walk
    resolved against the checkout failed generation outright rather than
    describing the library that project actually runs.
    """
    assert LIBRARY.source == LIBRARY_PACKAGE
    assert (LIBRARY.source / "actors").is_dir()


def test_an_entry_added_to_the_tree_appears_without_being_declared(
    tmp_path: Path,
) -> None:
    """The property the derivation is for.

    Under the authored roster this raised until somebody wrote a row — which
    is how `client` announced itself. Now the entry describes itself, and the
    page follows the tree by construction.
    """
    roster = Roster(source=library_at(tmp_path, "arrived"))

    rows = roster.table().rows

    assert [cell.text for cell, _ in rows] == ["arrived"]
    assert rows[0][1].text == "A summary line. What it solves, at length."


def test_an_entry_with_no_docstring_fails_generation(tmp_path: Path) -> None:
    """Loudly, for the reason the authored roster failed loudly.

    A page that quietly drops a package reads exactly like a complete one, so
    an entry with nothing to say has to stop the build rather than shorten the
    table. The message names the file and what to write in it.
    """
    source = library_at(tmp_path, "described")
    (source / "silent.py").write_text("value = 1\n", encoding="utf-8")
    roster = Roster(source=source)

    with pytest.raises(ValueError) as raised:
        roster.table()

    assert "silent.py" in str(raised.value)
    assert "docstring" in str(raised.value)


def test_a_tiered_package_is_not_owed_a_row(tmp_path: Path) -> None:
    """A section above the table describes it at length instead."""
    tiered = [entry.package for entry in Roster().tiered]
    roster = Roster(source=library_at(tmp_path, *tiered, "ordinary"))

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
    roster = Roster(source=source)

    assert roster.owed() == ["ordinary"]
    assert len(roster.table().rows) == 1
