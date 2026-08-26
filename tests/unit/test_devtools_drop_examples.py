"""What an adopting domain inherits from the scaffold and never wanted.

`examples/` composes lup's own runtime against lup's own README, so a project
built *on* lup inherits demonstrations of the thing it is merely a consumer
of. Removing them is mechanical and always right, which is why it is a command
rather than a judgement in the interview — and why what it reports afterwards
matters more than what it deletes: the lines still naming a directory that has
gone are the part somebody has to repair by hand.
"""

from pathlib import Path

import pytest

from lup_template.devtools.dev.init import (
    SCAFFOLD_DEMONSTRATIONS,
    drop_scaffold_demonstrations,
    mention_pattern,
    surviving_mentions,
)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A tree holding what the scaffold ships, and prose naming it."""
    for path in SCAFFOLD_DEMONSTRATIONS:
        target = tmp_path / path
        if path.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("from examples.one_shot import main\n", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "one_shot.py").write_text(
                "from examples.common import Summary\n", encoding="utf-8"
            )
    (tmp_path / "README.md").write_text(
        "See [runtime examples](examples/README.md), which run end to end.\n"
        "This paragraph merely mentions examples. It names no path.\n",
        encoding="utf-8",
    )
    (tmp_path / "catalog.py").write_text('composition = ["examples/"]\n', "utf-8")
    return tmp_path


def test_a_dry_run_reports_what_it_would_remove_and_removes_nothing(
    checkout: Path,
) -> None:
    removed = drop_scaffold_demonstrations(checkout, dry_run=True)

    assert len(removed) == len(SCAFFOLD_DEMONSTRATIONS)
    for path in SCAFFOLD_DEMONSTRATIONS:
        assert (checkout / path).exists()


def test_what_is_absent_already_is_not_reported_as_removed(tmp_path: Path) -> None:
    """Running twice, or on a domain that pruned by hand, says so rather than fails."""
    assert drop_scaffold_demonstrations(tmp_path, dry_run=False) == []


def test_a_path_reference_is_reported_and_a_bare_word_is_not(checkout: Path) -> None:
    """The name is an ordinary English word; only the separator makes it a path."""
    mentions = surviving_mentions(checkout, SCAFFOLD_DEMONSTRATIONS)

    assert any("README.md:1" in line for line in mentions)
    assert not any("README.md:2" in line for line in mentions)


def test_the_composition_root_that_goes_dead_is_reported(checkout: Path) -> None:
    """`"examples/"` is a sanctioned root, and sanctioning a gone tree is dead."""
    assert any(
        "catalog.py" in line
        for line in surviving_mentions(checkout, SCAFFOLD_DEMONSTRATIONS)
    )


def test_a_file_inside_what_is_going_is_not_reported(checkout: Path) -> None:
    """It names its siblings constantly and leaves with them."""
    mentions = surviving_mentions(checkout, SCAFFOLD_DEMONSTRATIONS)

    assert not any("examples/one_shot.py" in line for line in mentions)


@pytest.mark.parametrize(
    ("line", "named"),
    [
        ("[runtime examples](examples/README.md)", True),
        ("uv run -m examples.one_shot", True),
        ("from examples.common import Summary", True),
        ("updating examples.", False),
        ("a paragraph about examples", False),
        ("these examples, and others", False),
    ],
)
def test_the_module_spelling_needs_a_name_after_its_dot(line: str, named: bool) -> None:
    """A sentence ending in "examples." is prose, not a reference to the package."""
    assert bool(mention_pattern(Path("examples")).search(line)) is named
