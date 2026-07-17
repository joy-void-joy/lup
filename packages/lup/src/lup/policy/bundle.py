"""Assemble dependency-free policy kernel and application-owned data files."""
#lup: Yeah, the files under this folder don't allow me to form a good idea of what is happening, what's the main concern being tackled

import json
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


def tuple_rows_literal(rows: list[list[str]]) -> str:
    """Render already-escaped tuple rows in Ruff-stable multiline form."""
    if not rows:
        return "()"
    blocks = [
        "    (\n" + "".join(f"        {value},\n" for value in row) + "    ),"
        for row in rows
    ]
    return "[\n" + "\n".join(blocks) + "\n]"


def url_scope_rows_literal(rows: list[UrlScopeRow]) -> str:
    """Render normalized URL scopes as primitive tuples."""
    return tuple_rows_literal(
        [
            [
                json.dumps(scheme),
                json.dumps(host),
                "None" if port is None else str(port),
                json.dumps(path_prefix),
                json.dumps(reason),
            ]
            for scheme, host, port, path_prefix, reason in rows
        ]
    )


def path_rule_rows_literal(rows: list[PathRuleRow]) -> str:
    """Render protected-path rows as primitive tuples."""
    return tuple_rows_literal(
        [
            [
                json.dumps(kind),
                json.dumps(value),
                json.dumps(reason),
                str(autonomous),
            ]
            for kind, value, reason, autonomous in rows
        ]
    )


def antipattern_rows_literal(rows: dict[str, list[AntiPatternRow]]) -> str:
    """Render suffix-keyed anti-pattern rows in Ruff-stable form."""
    lines = ["{"]
    for suffix, patterns in sorted(rows.items()):
        lines.append(f"    {json.dumps(suffix)}: [")
        for rule_id, pattern, message in patterns:
            block = (
                "        (\n"
                f"            {json.dumps(rule_id)},\n"
                f"            {json.dumps(pattern)},\n"
                f"            {json.dumps(message)},\n"
                "        ),"
            )
            lines.append(block)
        lines.append("    ],")
    lines.append("}")
    return "\n".join(lines)


def string_rows_literal(rows: list[str]) -> str:
    """Render a sequence of generated string identities."""
    if not rows:
        return "()"
    return "[\n" + "".join(f"    {json.dumps(row)},\n" for row in rows) + "]"


def render_policy_data(
    *,
    allowed_fetch_scopes: list[UrlScopeRow],
    denied_fetch_scopes: list[UrlScopeRow],
    protected_roots: list[str],
    autonomous_agent_identities: list[str],
) -> str:
    """Render one plugin's canonical policy rows without executable logic."""
    body = "\n\n".join(
        [
            "ALLOWED_FETCH_SCOPES = " + url_scope_rows_literal(allowed_fetch_scopes),
            "DENIED_FETCH_SCOPES = " + url_scope_rows_literal(denied_fetch_scopes),
            "PATH_RULES = "
            + path_rule_rows_literal(runtime_path_rules(protected_roots)),
            "ANTI_PATTERN_ROWS = "
            + antipattern_rows_literal(bundled_antipattern_rows()),
            "AUTONOMOUS_AGENT_IDENTITIES = "
            + string_rows_literal(autonomous_agent_identities),
            "MAXIMUM_ADDED_LINES = 3",
        ]
    )
    return '"""Generated application-owned policy data."""\n\n' + body + "\n"
