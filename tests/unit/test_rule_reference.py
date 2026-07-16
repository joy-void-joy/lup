"""Generated Lup rule reference tests."""

from pathlib import Path

from lup.codescan.antipatterns import PYTHON_ANTI_PATTERNS, TS_ANTI_PATTERNS
from lup_template.devtools.dev.rules import STRUCTURAL_RULES, render_rule_reference


def test_checked_in_rule_reference_matches_canonical_objects() -> None:
    rendered = render_rule_reference()

    assert Path("docs/rules.md").read_text(encoding="utf-8") == rendered
    for rule in [*PYTHON_ANTI_PATTERNS, *TS_ANTI_PATTERNS, *STRUCTURAL_RULES]:
        assert f"`{rule.id}`" in rendered
