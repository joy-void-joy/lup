"""Generated Lup rule reference tests."""

from pathlib import Path

from lup.codescan.antipatterns import PYTHON_ANTI_PATTERNS, TS_ANTI_PATTERNS
from lup.codescan.registry import STRUCTURAL_RULES, all_rules
from lup_template.devtools.dev.rules import render_rule_reference


def test_checked_in_rule_reference_matches_canonical_objects() -> None:
    rendered = render_rule_reference()

    assert Path("docs/rules.md").read_text(encoding="utf-8") == rendered
    for rule in [*PYTHON_ANTI_PATTERNS, *TS_ANTI_PATTERNS, *STRUCTURAL_RULES]:
        assert f"`{rule.id}`" in rendered


def test_registry_covers_every_family_with_unique_ids_and_homes() -> None:
    rules = all_rules()

    ids = [rule.id for rule in rules]
    assert len(ids) == len(set(ids))
    assert {rule.family for rule in rules} == {
        "anti-pattern",
        "boundary",
        "spelling",
        "architecture",
    }
    assert all(rule.defined_in.startswith("lup.codescan.") for rule in rules)
