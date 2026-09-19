"""What a release does to the four files it touches, each checked on its own.

Every step here had been carried as prose in the bump skill, and three of them
had never run in this repository: the changelog's open section was never
closed, the published version never moved, and the declarations never emptied.
Prose does not fail a test, so these are what replaces it.
"""

import ast
import datetime as dt

import pytest

from lup.devtools.changelog import Changelog
from lup.devtools.dev.release import (
    cleared_declarations,
    is_level,
    next_version,
    released,
    with_version,
)

MANIFEST = """\
[project]
name = "thing"
# a comment somebody wrote
version = "1.4.2"
description = "a thing"
"""

MODULE = '''\
"""What this module is for, which outlives every release."""

from lup.devtools.dev.migrations import Migration


class Keep:
    """Nothing here is the list."""


DECLARED = [
    Migration(
        subjects=["gone"],
        # a bracket ] and a quote " inside prose, which is the point
        reason="a reason with ] and \\" in it",
        steps=[],
    ),
]


def also_keep() -> int:
    return 1
'''

DAY = dt.date(2026, 9, 19)


def test_each_level_moves_its_own_part() -> None:
    assert next_version("1.4.2", "patch") == "1.4.3"
    assert next_version("1.4.2", "minor") == "1.5.0"
    assert next_version("1.4.2", "major") == "2.0.0"


def test_a_level_that_is_not_one_is_refused() -> None:
    """Narrowed at the edge rather than trusted through the call."""
    assert is_level("minor")
    assert not is_level("Minor")
    assert not is_level("bump")
    with pytest.raises(ValueError):
        next_version("1.4.2", "sideways")  # pyright: ignore[reportArgumentType]


def test_a_version_that_is_not_one_is_refused() -> None:
    with pytest.raises(ValueError):
        next_version("stable", "patch")


def test_moving_a_version_leaves_the_rest_of_the_manifest_alone() -> None:
    """Through tomlkit, so a comment does not pay for a version bump."""
    moved = with_version(MANIFEST, "1.5.0")
    assert 'version = "1.5.0"' in moved
    assert "# a comment somebody wrote" in moved
    assert 'name = "thing"' in moved


def test_emptying_the_declarations_keeps_everything_that_is_not_the_list() -> None:
    """The window of unshipped breaks goes; the module explaining it stays."""
    emptied = cleared_declarations(MODULE)
    assert "DECLARED: list[Migration] = []" in emptied
    assert '"""What this module is for, which outlives every release."""' in emptied
    assert "class Keep:" in emptied
    assert "def also_keep()" in emptied
    assert "a reason with" not in emptied


def test_the_emptied_module_still_parses() -> None:
    """The one failure this cannot leave behind, whatever the prose contained.

    The fixture's reason holds a bracket and an escaped quote on purpose: a
    replacement that matched text rather than the tree would cut the span in
    the wrong place and leave a file that no longer imports.
    """
    assert ast.parse(cleared_declarations(MODULE)) is not None


def test_a_module_with_no_declarations_says_so() -> None:
    with pytest.raises(KeyError):
        cleared_declarations("value = 1\n")


def test_closing_the_open_section_renames_it_and_keeps_its_entries() -> None:
    log = Changelog.parse("# Changelog\n\n## Unreleased\n\n- something landed\n")
    closed = released(log, "0.3.0", DAY, migrations=[])
    rendered = closed.render()

    assert "## 0.3.0 — 2026-09-19" in rendered
    assert "## Unreleased" not in rendered
    assert "- something landed" in rendered
    assert [section.version for section in closed.sections] == ["0.3.0"]


def test_pending_migrations_are_folded_in_under_their_own_heading() -> None:
    """What a reader has to act on is not mixed in with what changed."""
    log = Changelog.parse("# Changelog\n\n## Unreleased\n\n- something landed\n")
    closed = released(log, "0.3.0", DAY, migrations=["call this instead"])
    rendered = closed.render()

    assert "### What this release asks of a caller" in rendered
    assert "- call this instead" in rendered
    assert rendered.index("- something landed") < rendered.index("- call this instead")


def test_a_document_nobody_is_releasing_round_trips() -> None:
    """The open section is put back where it was read, untouched."""
    text = (
        "# Changelog\n\n## Unreleased\n\n- pending\n\n## 0.1.0 — 2026-01-01\n\n- old\n"
    )
    assert Changelog.parse(text).render() == text


def test_a_hand_written_heading_is_read_as_a_release() -> None:
    """The format this repository's changelog was already written in.

    Read wider than it is written: a document whose every heading fails to
    parse comes back with no releases in it, and the next note written lands
    beneath the whole of it.
    """
    dashed = Changelog.parse("# C\n\n## 0.2.0 — 2026-07-23\n\n- old\n")
    parenthesised = Changelog.parse("# C\n\n## v0.2.0 (2026-07-23)\n\n- old\n")

    assert [section.version for section in dashed.sections] == ["0.2.0"]
    assert [section.version for section in parenthesised.sections] == ["0.2.0"]
    assert dashed.sections[0].date == dt.date(2026, 7, 23)


def test_a_prose_heading_is_not_a_release() -> None:
    """A document's own headings survive rather than becoming odd versions."""
    log = Changelog.parse("# C\n\n## Notes for readers\n\n- prose\n")
    assert log.sections == []
