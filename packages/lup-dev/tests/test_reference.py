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


PROSE = ["match", "layers"]
"""Code spans in lower case under *Enforced by:* that name no rule: Python's `match`
statement, the `layers` import contract."""


def enforced() -> list[str]:
    """Return the rule ids the conventions name under *Enforced by:*.

    A rule id is a code span in lower case and hyphens, outside parentheses and
    not in `PROSE`: the spans inside parentheses describe the rule (`object`,
    `frozen`), and ruff's and pyright's rules are spelled otherwise (`N818`,
    `reportAbstractUsage`).
    """
    conventions = (REPOSITORY / "docs" / "conventions.md").read_text()
    named: list[str] = []
    for line in conventions.splitlines():
        if not line.startswith("**Enforced by:**"):
            continue
        depth = 0
        for index, part in enumerate(line.split("`")):
            if index % 2 == 0:
                depth += part.count("(") - part.count(")")
                continue
            rule_shaped = part.islower() and part.replace("-", "").isalpha()
            if depth == 0 and rule_shaped and part not in PROSE:
                named.append(part)
    return named


def test_every_rule_the_conventions_say_enforces_them_is_in_the_table() -> None:
    engine = EngineChecker(layout=Layout(state=Path("/nowhere")), idle=timedelta(0))
    table = {rule.id for rule in engine.rules()}
    named = enforced()
    assert len(named) > len(table) / 2, "the conventions' *Enforced by:* lines moved"
    unknown = sorted(set(named) - table)
    assert unknown == [], (
        f"the conventions name {unknown} under *Enforced by:*, which the table lacks; "
        "rename the rule there, or add a code span that names no rule to `PROSE`"
    )
