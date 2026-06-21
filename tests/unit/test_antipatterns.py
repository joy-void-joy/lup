# claude: ignore
"""The anti-pattern set is single-sourced, and the auditor agrees with the hook.

`lup.antipatterns` is the importable source of truth; the edit hook mirrors it
inline because it cannot import on its hot path. These tests pin that the two
copies stay byte-identical (so they cannot drift) and that the auditor flags the
two classes the hook cannot catch after the fact: a match with no marker, and a
marker guarding nothing.
"""

import importlib.util
import re
from pathlib import Path

from lup.antipatterns import (
    PYTHON_ANTI_PATTERNS,
    TS_ANTI_PATTERNS,
    AntiPattern,
    audit_text,
)

HOOK_PATH = (
    Path(__file__).parents[2]
    / ".claude"
    / "plugins"
    / "lup"
    / "hooks"
    / "scripts"
    / "auto_allow_edits.py"
)

spec = importlib.util.spec_from_file_location("auto_allow_edits", HOOK_PATH)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def lib_rows(patterns: list[AntiPattern]) -> list[tuple[str, str]]:
    return [(ap.pattern.pattern, ap.message) for ap in patterns]


def hook_rows(table: list[tuple[re.Pattern[str], str]]) -> list[tuple[str, str]]:
    return [(pattern.pattern, message) for pattern, message in table]


def test_python_table_matches_hook() -> None:
    """The library Python table is identical to the hook's inline copy."""
    hook_table: list[tuple[re.Pattern[str], str]] = hook.ANTI_PATTERNS
    assert lib_rows(PYTHON_ANTI_PATTERNS) == hook_rows(hook_table)


def test_ts_table_matches_hook() -> None:
    """The library TS table is identical to the hook's inline copy."""
    hook_table: list[tuple[re.Pattern[str], str]] = hook.TS_ANTI_PATTERNS
    assert lib_rows(TS_ANTI_PATTERNS) == hook_rows(hook_table)


def test_audit_flags_unguarded_match() -> None:
    findings = audit_text("x: Any = 1\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]
    assert findings[0].line == 1


def test_audit_accepts_guarded_match() -> None:
    findings = audit_text("x: Any = 1  # claude: ignore\n", PYTHON_ANTI_PATTERNS)
    assert findings == []


def test_audit_flags_spurious_marker() -> None:
    findings = audit_text("x: int = 1  # claude: ignore\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["spurious"]


def test_audit_skips_file_level_ignore() -> None:
    findings = audit_text("# claude: ignore\nx: Any = 1\n", PYTHON_ANTI_PATTERNS)
    assert findings == []


def test_audit_skips_plain_comment_lines() -> None:
    findings = audit_text("# a comment mentioning Any in prose\n", PYTHON_ANTI_PATTERNS)
    assert findings == []
