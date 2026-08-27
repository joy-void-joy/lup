"""What the content walks count as part of a tree, and what sits beside it.

Both walks read the filesystem rather than git, deliberately — the whole point
is that the set a page describes is the tree's to decide rather than prose's to
promise. The cost is that everything a tool leaves in a checkout is visible to
them, and neither a diagram of what a reader imports nor a roster of packages
has room for any of it.

These are the two shapes that reached generation from a real checkout: an agent
scratch directory under the library, which stopped the roster outright, and the
orphaned bytecode of sub-apps that had moved into the library, which drew seven
phantom packages into the layout diagram.
"""

from pathlib import Path

from lup.devtools.harness.content.tree import annotated_tree, top_level_entries


def package_at(root: Path, name: str) -> Path:
    """A directory holding one importable module, so it is a real package."""
    package = root / name
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""A package."""\n', encoding="utf-8")
    return package


def test_the_layout_skips_a_dotted_directory(tmp_path: Path) -> None:
    package_at(tmp_path, "real")
    (tmp_path / ".claude" / ".cc-writes").mkdir(parents=True)
    (tmp_path / ".venv" / "lib").mkdir(parents=True)

    rendered = annotated_tree(tmp_path.parent, tmp_path.name)

    assert "real/" in rendered
    assert ".claude" not in rendered
    assert ".venv" not in rendered


def test_the_layout_skips_a_directory_whose_source_has_gone(tmp_path: Path) -> None:
    """Orphaned bytecode is where a package was, not a package.

    A sub-app moved into the library leaves its `__pycache__` behind, because
    git does not track directories and has nothing to remove. The walk already
    skips `__pycache__` itself, so the husk rendered as a package holding
    nothing — which reads as a package that exists and is empty.
    """
    package_at(tmp_path, "real")
    (tmp_path / "moved_away" / "__pycache__").mkdir(parents=True)
    (tmp_path / "moved_away" / "__pycache__" / "app.cpython-314.pyc").write_bytes(b"")

    rendered = annotated_tree(tmp_path.parent, tmp_path.name)

    assert "real/" in rendered
    assert "moved_away" not in rendered


def test_the_layout_keeps_a_package_whose_source_is_nested(tmp_path: Path) -> None:
    """Sourceless means sourceless throughout, not sourceless at the top."""
    nested = tmp_path / "outer" / "inner"
    nested.mkdir(parents=True)
    (nested / "module.py").write_text('"""A module."""\n', encoding="utf-8")

    rendered = annotated_tree(tmp_path.parent, tmp_path.name)

    assert "outer/" in rendered
    assert "inner/" in rendered
    assert "module.py" in rendered


def test_the_roster_walk_skips_a_dotted_directory(tmp_path: Path) -> None:
    package_at(tmp_path, "real")
    (tmp_path / ".claude").mkdir()

    walked = top_level_entries(tmp_path.parent, tmp_path.name)

    assert [entry.name for entry in walked] == ["real"]


def test_the_roster_walk_skips_a_directory_holding_no_initializer(
    tmp_path: Path,
) -> None:
    """Deleting a package leaves its directory wherever an untracked file sits.

    The roster asked such a directory what it solved and opened an
    ``__init__.py`` the deletion had taken, which is a crash rather than a
    diagnostic. A directory Python cannot import is not an entry to describe.
    """
    package_at(tmp_path, "real")
    (tmp_path / "emptied" / "__pycache__").mkdir(parents=True)
    (tmp_path / "emptied" / "__pycache__" / "gone.pyc").write_bytes(b"")

    walked = top_level_entries(tmp_path.parent, tmp_path.name)

    assert [entry.name for entry in walked] == ["real"]


def test_a_walked_entry_carries_the_source_that_made_it_importable(
    tmp_path: Path,
) -> None:
    """The file comes from the walk, so it is one the walk actually found."""
    package_at(tmp_path, "packaged")
    (tmp_path / "module.py").write_text('"""A module."""\n', encoding="utf-8")

    walked = {
        entry.name: entry.source
        for entry in top_level_entries(tmp_path.parent, tmp_path.name)
    }

    assert walked["packaged"] == tmp_path / "packaged" / "__init__.py"
    assert walked["module"] == tmp_path / "module.py"
    assert all(source.is_file() for source in walked.values())
