# lup: ignore[native-spelling]
# This checker necessarily owns the provider spellings it audits.
"""AST boundary rule keeping native adapters out of neutral consumers.

Named adapter packages, tests, and explicit application/CLI composition roots
may import concrete implementations. Every other module composes only the
portable contracts. A deliberate exception uses ``# lup:
ignore[seam-boundary]`` on the import or as a file-level directive.
"""

import ast
from pathlib import Path

from pydantic import BaseModel

from lup.codescan.common import (
    IGNORE_RE,
    PythonContext,
    file_level_ignore,
    ignore_rule_ids,
)
from lup.policy.kernel.decision import KERNEL_IMPORT_ALLOWLIST

RULE_ID = "seam-boundary"
NATIVE_SPELLING_RULE_ID = "native-spelling"
KERNEL_IMPORT_RULE_ID = "kernel-imports"
NATIVE_PREFIXES = ("lup.adapters.claude", "lup.adapters.codex")
NATIVE_SPELLINGS = {
    "/lup:": "Claude skill invocation",
    "$lup:": "Codex skill invocation",
    "CLAUDE_CONFIG_DIR": "Claude configuration environment",
    "CODEX_HOME": "Codex configuration environment",
    ".claude-plugin": "Claude plugin manifest path",
    ".codex-plugin": "Codex plugin manifest path",
    "PreToolUse": "native hook event",
    "PermissionRequest": "native hook event",
    "PostToolUse": "native hook event",
    "SessionStart": "native hook event",
    "thread/start": "Codex app-server method",
    "thread/resume": "Codex app-server method",
    "thread/fork": "Codex app-server method",
    "turn/start": "Codex app-server method",
    "turn/steer": "Codex app-server method",
    "turn/interrupt": "Codex app-server method",
}


def path_is_sanctioned(rel_path: Path) -> bool:
    """Whether a path may import native implementations as a composition root."""
    posix = rel_path.as_posix()
    return (
        "lup/adapters/" in posix
        or posix.startswith((".claude/", ".codex/", ".agents/"))
        or posix == "AGENTS.md"
        or posix.startswith("tests/")
        or posix.startswith("examples/")
        or posix == "src/lup_template/agent/core.py"
        or posix.startswith("src/lup_template/devtools/harness/")
        or posix == "src/lup_template/devtools/setup.py"
        or posix == "src/lup_template/devtools/usage/app.py"
    )


def native_spelling_path_is_sanctioned(rel_path: Path) -> bool:
    """Whether a path may own provider wire spellings without a suppression."""
    content_root = "src/lup_template/devtools/harness/content/"
    return path_is_sanctioned(rel_path) and not rel_path.as_posix().startswith(
        content_root
    )


class BoundaryBreach(BaseModel):
    """One concrete native import outside a sanctioned composition root."""

    line: int
    module: str
    text: str


class BoundaryAuditFinding(BaseModel):
    """One missing, untyped, or spurious boundary-rule suppression."""

    kind: str
    line: int
    text: str
    message: str
    rule_id: str
    module: str = ""


class SourceViolation(BaseModel):
    """One unsuppressed source shape before ordinary suppression auditing."""

    line: int
    text: str
    subject: str
    message: str


class BoundaryDirective(BaseModel):
    """One parsed inline or file-wide suppression directive."""

    line: int
    rule_ids: set[str] | None  # lup: ignore[set-shape] — rule identity membership
    file_level: bool = False


def native_module(name: str) -> bool:
    """Recognize only concrete named adapter packages."""
    return any(
        name == prefix or name.startswith(f"{prefix}.") for prefix in NATIVE_PREFIXES
    )


def import_violations(text: str) -> list[SourceViolation]:
    """Find native adapter imports through Python syntax before suppression."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    violations: list[SourceViolation] = []  # lup: ignore[empty-collection]
    for node in ast.walk(tree):
        modules: list[str]
        match node:
            case ast.Import(names=names):
                modules = [item.name for item in names if native_module(item.name)]
            case ast.ImportFrom(module=str(module)) if native_module(module):
                modules = [module]
            case _:
                continue
        line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        violations.extend(
            SourceViolation(
                line=node.lineno,
                subject=module,
                text=line.strip(),
                message=f"neutral module imports native adapter {module}",
            )
            for module in modules
        )
    return violations


def kernel_import_violations(text: str) -> list[SourceViolation]:
    """Find imports outside the hermetic policy kernel's pinned stdlib set."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    violations: list[SourceViolation] = []  # lup: ignore[empty-collection]
    for node in ast.walk(tree):
        modules: list[str]
        match node:
            case ast.Import(names=names):
                modules = [
                    item.name
                    for item in names
                    if item.name not in KERNEL_IMPORT_ALLOWLIST
                ]
            # A relative import names a sibling kernel module, which carries
            # the same hermetic guarantee this rule enforces.
            case ast.ImportFrom(level=int(level)) if level > 0:
                continue
            case ast.ImportFrom(module=str(module)) if (
                module not in KERNEL_IMPORT_ALLOWLIST
            ):
                modules = [module]
            case _:
                continue
        line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        violations.extend(
            SourceViolation(
                line=node.lineno,
                subject=module,
                text=line.strip(),
                message=f"policy kernel imports non-hermetic module {module}",
            )
            for module in modules
        )
    return violations


def literal_string(node: ast.AST) -> str | None:
    """Fold only statically known string syntax for the spelling audit."""
    match node:
        case ast.Constant(value=str(value)):
            return value
        case ast.BinOp(left=left, op=ast.Add(), right=right):
            before = literal_string(left)
            after = literal_string(right)
            return before + after if before is not None and after is not None else None
        case ast.JoinedStr(values=values):
            parts = [
                part for value in values if (part := literal_string(value)) is not None
            ]
            return "".join(parts) if len(parts) == len(values) else None
        case ast.FormattedValue(value=ast.Constant(value=str(value))):
            return value
    return None


def native_spelling_violations(text: str) -> list[SourceViolation]:
    """Find provider wire spellings in code strings outside native ownership."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    context = PythonContext.parse(text)
    violations: list[SourceViolation] = []  # lup: ignore[empty-collection]
    folded_children: set[int] = set()  # lup: ignore[set-shape,empty-collection]
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp | ast.JoinedStr):
            folded_children.update(
                id(child) for child in ast.walk(node) if child is not node
            )
        if id(node) in folded_children:
            continue
        value = literal_string(node)
        line_number = getattr(node, "lineno", 0)
        if value is None or line_number in context.docstring_lines:
            continue
        line = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
        for spelling, description in NATIVE_SPELLINGS.items():
            if spelling not in value:
                continue
            violations.append(
                SourceViolation(
                    line=line_number,
                    text=line.strip(),
                    subject=spelling,
                    message=(
                        f"neutral module contains {description} spelling {spelling!r}"
                    ),
                )
            )
    return violations


def audit_rule(
    text: str, rule_id: str, violations: list[SourceViolation]
) -> list[BoundaryAuditFinding]:
    """Apply ordinary inline/file suppression auditing to one boundary rule."""
    context = PythonContext.parse(text)
    file_ignore = file_level_ignore(text)
    directives: list[BoundaryDirective] = []  # lup: ignore[empty-collection]
    if file_ignore is not None:
        directives.append(
            BoundaryDirective(
                line=file_ignore.line,
                rule_ids=file_ignore.rule_ids,
                file_level=True,
            )
        )
    for line_number, line in enumerate(text.splitlines(), start=1):
        if file_ignore is not None and line_number == file_ignore.line:
            continue
        match = IGNORE_RE.search(line)
        if match is None or not context.comment_at(line_number, match.start()):
            continue
        directives.append(
            BoundaryDirective(
                line=line_number,
                rule_ids=ignore_rule_ids(match),
            )
        )

    used: set[int] = set()  # lup: ignore[set-shape,empty-collection]
    untyped: set[int] = set()  # lup: ignore[set-shape,empty-collection]
    findings: list[BoundaryAuditFinding] = []  # lup: ignore[empty-collection]
    for violation in violations:
        candidates = [
            (index, directive)
            for index, directive in enumerate(directives)
            if (directive.file_level or directive.line == violation.line)
            and (directive.rule_ids is None or rule_id in directive.rule_ids)
        ]
        if not candidates:
            findings.append(
                BoundaryAuditFinding(
                    kind="missing",
                    line=violation.line,
                    text=violation.text,
                    message=violation.message,
                    rule_id=rule_id,
                    module=violation.subject,
                )
            )
            continue
        index, directive = candidates[0]
        used.add(index)
        if directive.rule_ids is None and index not in untyped:
            findings.append(
                BoundaryAuditFinding(
                    kind="untyped",
                    line=directive.line,
                    text=violation.text,
                    message=(
                        f"bare suppression covers {rule_id}; use "
                        f"# lup: ignore[{rule_id}] with a reason"
                    ),
                    rule_id=rule_id,
                    module=violation.subject,
                )
            )
            untyped.add(index)
    for index, directive in enumerate(directives):
        rule_ids = directive.rule_ids
        if index in used or rule_ids is None or rule_id not in rule_ids:
            continue
        findings.append(
            BoundaryAuditFinding(
                kind="spurious",
                line=directive.line,
                text="",
                message=f"suppression names {rule_id} but guards no violation",
                rule_id=rule_id,
            )
        )
    return findings


def audit_boundaries(text: str) -> list[BoundaryAuditFinding]:
    """Audit native imports, native spellings, and both rule suppressions."""
    return [
        *audit_rule(text, RULE_ID, import_violations(text)),
        *audit_rule(
            text,
            NATIVE_SPELLING_RULE_ID,
            native_spelling_violations(text),
        ),
    ]


def audit_path_boundaries(rel_path: Path, text: str) -> list[BoundaryAuditFinding]:
    """Audit only the boundary rules that apply at one repository path."""
    findings: list[BoundaryAuditFinding] = []
    if not path_is_sanctioned(rel_path):
        findings.extend(audit_rule(text, RULE_ID, import_violations(text)))
    if not native_spelling_path_is_sanctioned(rel_path):
        findings.extend(
            audit_rule(
                text,
                NATIVE_SPELLING_RULE_ID,
                native_spelling_violations(text),
            )
        )
    return findings


def audit_kernel_imports(text: str) -> list[BoundaryAuditFinding]:
    """Audit the canonical kernel against its pinned dependency allowlist."""
    return audit_rule(text, KERNEL_IMPORT_RULE_ID, kernel_import_violations(text))


def find_boundary_breaches(text: str) -> list[BoundaryBreach]:
    """Find native adapter imports through Python syntax, honoring suppressions."""
    return [
        BoundaryBreach(line=item.line, module=item.module, text=item.text)
        for item in audit_rule(text, RULE_ID, import_violations(text))
        if item.kind == "missing"
    ]


def find_native_spelling_breaches(text: str) -> list[BoundaryBreach]:
    """Find native wire spellings in neutral code, honoring suppressions."""
    return [
        BoundaryBreach(line=item.line, module=item.module, text=item.text)
        for item in audit_rule(
            text,
            NATIVE_SPELLING_RULE_ID,
            native_spelling_violations(text),
        )
        if item.kind == "missing"
    ]


def find_kernel_import_breaches(text: str) -> list[BoundaryBreach]:
    """Find unsuppressed non-hermetic imports in the policy kernel."""
    return [
        BoundaryBreach(line=item.line, module=item.module, text=item.text)
        for item in audit_kernel_imports(text)
        if item.kind == "missing"
    ]
