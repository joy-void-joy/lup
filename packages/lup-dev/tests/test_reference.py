"""`docs/rules.md` is compiled from the engine's rule table, and kept so by the gate."""

from datetime import timedelta
from pathlib import Path

from lup_dev.codescan.engine import EngineChecker
from lup_dev.codescan.reference import reference
from lup_dev.layout import CheckoutLayout, Layout

REPOSITORY = Path(__file__).resolve().parents[3]


def test_the_committed_reference_is_what_the_table_compiles_to() -> None:
    engine = EngineChecker(layout=Layout(state=Path("/nowhere")), idle=timedelta(0))
    committed = CheckoutLayout(root=REPOSITORY).rules_reference.read_text()
    assert committed == reference(engine.rules()), (
        "docs/rules.md is stale: compile it again with `uv run lup-dev rules docs`"
    )


def test_the_reference_says_it_is_generated_and_from_where() -> None:
    committed = CheckoutLayout(root=REPOSITORY).rules_reference.read_text()
    first = committed.splitlines()[0]
    assert "packages/lup-dev/src/lup_dev/catalog/rules.ts" in first
    assert "Edit the table" in first
