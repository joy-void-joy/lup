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

from lup.devtools.harness.content.tree import annotated_tree, top_level_names


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

    assert top_level_names(tmp_path.parent, tmp_path.name) == ["real"]
