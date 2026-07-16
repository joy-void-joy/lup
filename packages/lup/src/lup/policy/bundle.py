# lup: ignore[tuple-shape]
# Runtime assembly serializes the kernel's deliberately primitive row contracts.
"""Assemble dependency-free policy kernel and application-owned data files."""

import pprint
import urllib.parse
from pathlib import Path

from lup.codescan.antipatterns import PYTHON_ANTI_PATTERNS, TS_ANTI_PATTERNS
import lup.policy.kernel as kernel
from lup.policy.kernel import (
    AntiPatternRow,
    PathRuleRow,
    UrlScopeRow,
)


def policy_kernel_source() -> str:
    """Read the canonical kernel verbatim for generated runtime assembly."""
    path = Path(kernel.__file__)
    return path.read_text(encoding="utf-8")


def bundled_antipattern_rows() -> dict[str, list[AntiPatternRow]]:
    """Compile primitive runtime rows directly from canonical rule objects."""
    python_rows = [
        (rule.id, rule.pattern.pattern, rule.message) for rule in PYTHON_ANTI_PATTERNS
    ]
    typescript_rows = [
        (rule.id, rule.pattern.pattern, rule.message) for rule in TS_ANTI_PATTERNS
    ]
    return {
        ".py": python_rows,
        ".pyi": python_rows,
        ".ts": typescript_rows,
        ".tsx": typescript_rows,
        ".js": typescript_rows,
        ".jsx": typescript_rows,
        ".vue": typescript_rows,
        ".svelte": typescript_rows,
    }


def runtime_url_scope(origin: str, path_prefix: str, reason: str = "") -> UrlScopeRow:
    """Normalize one validated hook scope into a primitive runtime row."""
    parsed = urllib.parse.urlsplit(origin)
    if parsed.hostname is None:
        raise ValueError("validated hook URL scope has no hostname")
    return parsed.scheme, parsed.hostname, parsed.port, path_prefix, reason


def runtime_path_rules(protected_roots: list[str]) -> list[PathRuleRow]:
    """Compile application roots plus invariant edit guardrails."""
    configured = [
        (
            "contains_part" if root == "tmp" else "subtree",
            root,
            "scratch path requires approval"
            if root == "tmp"
            else "protected path requires approval",
            root != "tmp",
        )
        for root in protected_roots
    ]
    return [
        *configured,
        ("name_prefix", ".env", "protected path requires approval", True),
        ("new_devtools", "src", "new devtools module requires approval", False),
    ]


def python_literal(value: object) -> str:
    """Render deterministic dependency-free Python data."""
    return pprint.pformat(value, width=88, sort_dicts=True)


def render_policy_data(
    *,
    allowed_fetch_scopes: list[UrlScopeRow],
    denied_fetch_scopes: list[UrlScopeRow],
    protected_roots: list[str],
    autonomous_agent_identities: list[str],
) -> str:
    """Render one plugin's canonical policy rows without executable logic."""
    assignments = (
        ("ALLOWED_FETCH_SCOPES", allowed_fetch_scopes),
        ("DENIED_FETCH_SCOPES", denied_fetch_scopes),
        ("PATH_RULES", runtime_path_rules(protected_roots)),
        ("ANTI_PATTERN_ROWS", bundled_antipattern_rows()),
        ("AUTONOMOUS_AGENT_IDENTITIES", autonomous_agent_identities),
        ("MAXIMUM_ADDED_LINES", 3),
    )
    body = "\n\n".join(
        f"{name} = {python_literal(value)}" for name, value in assignments
    )
    return '"""Generated application-owned policy data."""\n\n' + body + "\n"
