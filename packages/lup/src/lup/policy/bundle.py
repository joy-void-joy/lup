"""Assembly for generated dispatchers: kernel source plus policy data rows.

Generated native plugins must decide without lup installed, so the adapters'
hook renderers call this module to read :mod:`lup.policy.kernel` verbatim and
to erase validated application inputs — hook URL scopes, protected roots, the
canonical anti-pattern set — into primitive rows rendered as one generated
data file per plugin. No decision logic lives here; the kernel decides.
"""

import json
import urllib.parse
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from lup.codescan.antipatterns import PYTHON_ANTI_PATTERNS, TS_ANTI_PATTERNS
import lup.policy.kernel as kernel
from lup.policy.kernel.rows import (
    AntiPatternRow,
    PathRuleRow,
    ShellRuleRow,
    UrlScopeRow,
)
from lup.policy.shell_rules import (
    BASE_SHELL_RULES,
    ShellCommandRule,
    erase_shell_rules,
)
from lup.policy.rules import human_owned_path_rule, path_rule_row


class KernelModule(BaseModel):
    """One hermetic kernel source file copied into a generated runtime."""

    model_config = ConfigDict(frozen=True)

    name: str
    source: str


def policy_kernel_modules() -> list[KernelModule]:
    """Read the canonical kernel package verbatim for runtime assembly.

    The package's relative imports resolve the same beneath ``runtime/`` as
    they do in lup, so every module ships byte for byte.
    """
    directory = Path(kernel.__file__).parent
    return [
        KernelModule(name=path.name, source=path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.py"))
    ]


def bundled_antipattern_rows() -> dict[str, list[AntiPatternRow]]:
    """Compile primitive runtime rows directly from canonical rule objects."""
    python_rows = [
        AntiPatternRow(
            id=rule.id,
            pattern=rule.pattern.pattern,
            message=rule.message,
            context=rule.context,
        )
        for rule in PYTHON_ANTI_PATTERNS
    ]
    typescript_rows = [
        AntiPatternRow(
            id=rule.id,
            pattern=rule.pattern.pattern,
            message=rule.message,
            context=rule.context,
        )
        for rule in TS_ANTI_PATTERNS
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


def runtime_url_scope(
    origin: str,
    path_prefix: str,
    reason: str = "",
    include_subdomains: bool = False,
) -> UrlScopeRow:
    """Normalize one validated hook scope into a primitive runtime row."""
    parsed = urllib.parse.urlsplit(origin)
    if parsed.hostname is None:
        raise ValueError("validated hook URL scope has no hostname")
    return UrlScopeRow(
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=parsed.port,
        path_prefix=path_prefix,
        reason=reason,
        include_subdomains=include_subdomains,
    )


def runtime_path_rule(root: str) -> PathRuleRow:
    """Compile one application root into its primitive protected-path row."""
    match root:
        case "tmp":
            return PathRuleRow(
                kind="contains_part",
                value=root,
                reason="scratch path requires approval",
                allow_autonomous=False,
            )
        case _:
            return PathRuleRow(
                kind="subtree",
                value=root,
                reason="protected path requires approval",
                allow_autonomous=True,
            )


def runtime_path_rules(
    protected_roots: list[str], human_owned_files: list[str]
) -> list[PathRuleRow]:
    """Compile application roots plus invariant edit guardrails."""
    return [
        *[runtime_path_rule(root) for root in protected_roots],
        *[path_rule_row(human_owned_path_rule(path)) for path in human_owned_files],
        PathRuleRow(
            kind="name_prefix",
            value=".env",
            reason="protected path requires approval",
            allow_autonomous=True,
        ),
        PathRuleRow(
            kind="new_devtools",
            value="src",
            reason="new devtools module requires approval",
            allow_autonomous=False,
        ),
    ]


def runtime_shell_rules(extension: list[ShellCommandRule]) -> list[ShellRuleRow]:
    """Compile the baseline shell vocabulary plus an application extension."""
    return erase_shell_rules([*BASE_SHELL_RULES, *extension])


def dict_rows_literal(rows: list[list[str]]) -> str:
    """Render already-escaped ``"key": value`` rows in Ruff-stable form."""
    if not rows:
        return "()"
    blocks = [
        "    {\n" + "".join(f"        {entry},\n" for entry in row) + "    },"
        for row in rows
    ]
    return "[\n" + "\n".join(blocks) + "\n]"


def url_scope_rows_literal(rows: list[UrlScopeRow]) -> str:
    """Render normalized URL scopes as primitive runtime rows."""
    return dict_rows_literal(
        [
            [
                f'"scheme": {json.dumps(row["scheme"])}',
                f'"host": {json.dumps(row["host"])}',
                f'"port": {"None" if row["port"] is None else row["port"]}',
                f'"path_prefix": {json.dumps(row["path_prefix"])}',
                f'"reason": {json.dumps(row["reason"])}',
                f'"include_subdomains": {row["include_subdomains"]}',
            ]
            for row in rows
        ]
    )


def path_rule_rows_literal(rows: list[PathRuleRow]) -> str:
    """Render protected-path rows as primitive runtime rows."""
    return dict_rows_literal(
        [
            [
                f'"kind": {json.dumps(row["kind"])}',
                f'"value": {json.dumps(row["value"])}',
                f'"reason": {json.dumps(row["reason"])}',
                f'"allow_autonomous": {row["allow_autonomous"]}',
            ]
            for row in rows
        ]
    )


def antipattern_rows_literal(rows: dict[str, list[AntiPatternRow]]) -> str:
    """Render suffix-keyed anti-pattern rows in Ruff-stable form."""
    lines = ["{"]
    for suffix, patterns in sorted(rows.items()):
        lines.append(f"    {json.dumps(suffix)}: [")
        for row in patterns:
            block = (
                "        {\n"
                f'            "id": {json.dumps(row["id"])},\n'
                f'            "pattern": {json.dumps(row["pattern"])},\n'
                f'            "message": {json.dumps(row["message"])},\n'
                f'            "context": {json.dumps(row["context"])},\n'
                "        },"
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


def shell_rule_rows_literal(rows: list[ShellRuleRow]) -> str:
    """Render erased shell rules as Ruff-stable dict literals."""
    if not rows:
        return "[]"
    lines = ["["]
    for row in rows:
        lines.append("    {")
        lines.append(f'        "command": {json.dumps(row["command"])},')
        lines.append(f'        "subcommand": {json.dumps(row["subcommand"])},')
        lines.append(f'        "operation": {json.dumps(row["operation"])},')
        lines.append(f'        "effect": {json.dumps(row["effect"])},')
        for name, flags in (
            ("ask_flags", row["ask_flags"]),
            ("allow_flags", row["allow_flags"]),
            ("read_verbs", row["read_verbs"]),
            ("value_flags", row["value_flags"]),
        ):
            if flags:
                lines.append(f'        "{name}": [')
                lines.extend(f"            {json.dumps(flag)}," for flag in flags)
                lines.append("        ],")
            else:
                lines.append(f'        "{name}": [],')
        lines.append(f'        "reason": {json.dumps(row["reason"])},')
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


def render_policy_data(
    *,
    allowed_fetch_scopes: list[UrlScopeRow],
    denied_fetch_scopes: list[UrlScopeRow],
    protected_roots: list[str],
    human_owned_files: list[str],
    autonomous_agent_identities: list[str],
    shell_rule_extension: list[ShellCommandRule] | None = None,
) -> str:
    """Render one plugin's canonical policy rows without executable logic."""
    body = "\n\n".join(
        [
            "ALLOWED_FETCH_SCOPES = " + url_scope_rows_literal(allowed_fetch_scopes),
            "DENIED_FETCH_SCOPES = " + url_scope_rows_literal(denied_fetch_scopes),
            "PATH_RULES = "
            + path_rule_rows_literal(
                runtime_path_rules(protected_roots, human_owned_files)
            ),
            "ANTI_PATTERN_ROWS = "
            + antipattern_rows_literal(bundled_antipattern_rows()),
            "SHELL_RULES = "
            + shell_rule_rows_literal(runtime_shell_rules(shell_rule_extension or [])),
            "AUTONOMOUS_AGENT_IDENTITIES = "
            + string_rows_literal(autonomous_agent_identities),
            "MAXIMUM_ADDED_LINES = 3",
        ]
    )
    return (
        '"""Generated application-owned policy data.\n'
        "\n"
        "Rendered from lup.policy.bundle by\n"
        "`uv run lup-devtools harness generate all` — do not edit directly.\n"
        '"""\n\n' + body + "\n"
    )
