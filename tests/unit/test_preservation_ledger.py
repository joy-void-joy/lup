"""The checked-in ledger, resolved against the tree that is actually here.

This is the test the whole fixture exists for: it turns "no capability
disappeared" from a claim a plan makes into one a run either passes or does
not. It reads the composed CLI and the working tree, never a second fixture,
so the only way to make it pass over a real removal is to capture again — and
that leaves the removal in a diff, which is the point.
"""

import pytest

from lup.devtools.dev.commands import CommandEntry
from lup.devtools.dev.preservation import (
    LEDGER_FILE,
    Divergence,
    Ledger,
    capture,
    compare,
)
from lup_template.devtools.harness.catalog import dev_project
from lup_template.devtools.main import app


@pytest.fixture(scope="module")
def divergence() -> Divergence:
    """What the tree still answers for the capture, walked once for the module."""
    live = capture(CommandEntry.served_by(app), dev_project())
    return compare(Ledger.read(LEDGER_FILE), live)


def test_the_ledger_is_checked_in_where_the_commands_look_for_it() -> None:
    """A fixture nothing can find is a promise nothing keeps."""
    assert LEDGER_FILE.exists()


def test_no_captured_capability_has_disappeared(divergence: Divergence) -> None:
    """The one failure this exists to find, named row by row when it happens."""
    assert [row.spelled() for row in divergence.disappeared] == []


def test_the_capture_covers_both_published_roots() -> None:
    """A root left out is a surface nothing is watching."""
    assert Ledger.read(LEDGER_FILE).roots == ["lup", "lup_template"]


def test_the_capture_holds_the_operations_a_reader_types(
    divergence: Divergence,
) -> None:
    """The operation catalog is half of what the ledger is for."""
    captured = {*Ledger.read(LEDGER_FILE).commands}

    assert {"dev check", "dev relocate", "harness generate", "py search"} <= captured
