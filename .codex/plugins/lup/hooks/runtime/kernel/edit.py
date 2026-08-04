# lup: ignore[empty-collection, import-re, re-call, set-shape, string-split, tuple-shape]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Edit gates: anti-patterns, protected paths, markers, and size."""

import ast
import io
import posixpath
import re
import tokenize
from collections.abc import Callable

from .decision import KernelDecision
from .roles import path_role
from .rows import AntiPatternRow, PathRoleRow, PathRuleRow

MARKER_RE = re.compile(r"(#|//)\s*lup\s*:", re.IGNORECASE)
# A review note is any marker whose keyword is not `ignore`, which is the
# anti-pattern escape hatch rather than feedback — the same split
# `lup.codescan.markers` makes when it gathers notes.
# The whitespace sits inside the lookahead: leaving it outside lets the regex
# backtrack to zero width and match `# lup: ignore` after all.
NOTE_RE = re.compile(r"(#|//)\s*lup\s*:(?!\s*ignore\b)", re.IGNORECASE)
IGNORE_RE = re.compile(
    r"(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?",
    re.IGNORECASE,
)
FILE_IGNORE_RE = re.compile(
    r"^\s*(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?\s*$",
    re.IGNORECASE,
)


def python_tokens(source: str) -> list[tokenize.TokenInfo] | None:
    """Tokenize Python source, returning ``None`` for incomplete syntax."""
    try:
        return list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None


def python_comment_columns(source: str) -> dict[int, int] | None:
    """Map Python line numbers to real comment-token columns."""
    tokens = python_tokens(source)
    if tokens is None:
        return None
    return {
        token.start[0]: token.start[1]
        for token in tokens
        if token.type == tokenize.COMMENT
    }


def docstring_lines(source: str) -> set[int]:
    """Return lines occupied by bare string-expression documentation."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.end_lineno is not None
        ):
            lines.update(range(node.lineno, node.end_lineno + 1))
    return lines


def string_literal_lines(source: str) -> set[int]:
    """Return every line touched by a Python string token."""
    tokens = python_tokens(source)
    if tokens is None:
        return set()
    lines: set[int] = set()
    for token in tokens:
        if token.type == tokenize.STRING:
            lines.update(range(token.start[0], token.end[0] + 1))
    return lines


def mask_python_string_literals(source: str) -> list[str]:
    """Blank string-token characters while preserving line and column positions."""
    lines = [list(line) for line in source.splitlines()]
    tokens = python_tokens(source)
    if tokens is None:
        return source.splitlines()
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        start_line, start_column = token.start
        end_line, end_column = token.end
        for line_number in range(start_line, end_line + 1):
            line = lines[line_number - 1]
            first = start_column if line_number == start_line else 0
            last = end_column if line_number == end_line else len(line)
            line[first:last] = [" "] * (last - first)
            if line_number == start_line and last - first >= 2:
                line[first : first + 2] = ["'", "'"]
    return ["".join(line) for line in lines]


def python_code_lines(source: str) -> list[str]:
    """Blank string and comment tokens while preserving line and column positions."""
    lines = [list(line) for line in mask_python_string_literals(source)]
    tokens = python_tokens(source)
    if tokens is None:
        return ["".join(line) for line in lines]
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        start_line, start_column = token.start
        line = lines[start_line - 1]
        line[start_column : token.end[1]] = [" "] * (token.end[1] - start_column)
    return ["".join(line) for line in lines]


def count_in_prose(
    source: str, pattern: re.Pattern[str], python_source: bool = False
) -> int:
    """Count pattern matches where prose belongs, not inside ordinary strings."""
    if not python_source:
        return len(pattern.findall(source))
    tokens = python_tokens(source)
    if tokens is None:
        return len(pattern.findall(source))
    documentation = docstring_lines(source)
    return sum(
        len(pattern.findall(token.string))
        for token in tokens
        if token.type == tokenize.COMMENT
        or (
            token.type == tokenize.STRING
            and any(
                line in documentation
                for line in range(token.start[0], token.end[0] + 1)
            )
        )
    )


def review_marker_count(source: str, python_source: bool = False) -> int:
    """Count review notes — the feedback whose removal is the gated act."""
    return count_in_prose(source, NOTE_RE, python_source)


def empty_collection_exempt_lines(source: str) -> set[int]:
    """Return empty-collection lines whose AST context makes the seed deliberate."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    def is_empty_literal(node: ast.expr | None) -> bool:
        match node:
            case ast.Dict(keys=[]) | ast.List(elts=[]):
                return True
            case ast.Call(func=ast.Name(id="set"), args=[], keywords=[]):
                return True
        return False

    def is_self_attribute(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )

    exempt: set[int] = set()

    def mark(value: ast.expr | None) -> None:
        if value is not None and is_empty_literal(value):
            exempt.add(value.lineno)

    def is_loop(node: ast.AST) -> bool:
        return isinstance(node, ast.For | ast.AsyncFor | ast.While)

    def mutated_name(node: ast.AST) -> str | None:
        match node:
            case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=attr)) if (
                attr
                in (
                    "append",
                    "appendleft",
                    "extend",
                    "add",
                    "update",
                    "insert",
                    "setdefault",
                )
            ):
                return name
            case ast.Assign(targets=[ast.Subscript(value=ast.Name(id=name))]):
                return name
            case ast.AugAssign(
                target=ast.Name(id=name) | ast.Subscript(value=ast.Name(id=name))
            ):
                return name
        return None

    def exempt_scope_seeds(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        feeding: dict[str, list[bool]] = {}
        for loop in ast.walk(scope):
            if not is_loop(loop):
                continue
            tolerant = any(isinstance(inner, ast.Try) for inner in ast.walk(loop))
            for inner in ast.walk(loop):
                name = mutated_name(inner)
                if name is not None:
                    feeding.setdefault(name, []).append(tolerant)

        def visit(node: ast.AST, in_loop: bool) -> None:
            for child in ast.iter_child_nodes(node):
                match child:
                    case (
                        ast.FunctionDef()
                        | ast.AsyncFunctionDef()
                        | ast.ClassDef()
                        | ast.Lambda()
                    ):
                        continue
                    case (
                        ast.Assign(targets=[ast.Name(id=name)], value=value)
                        | ast.AnnAssign(target=ast.Name(id=name), value=value)
                    ) if is_empty_literal(value):
                        loops = feeding[name] if name in feeding else None
                        if in_loop:
                            if loops is not None:
                                mark(value)
                        elif loops is None or all(loops):
                            mark(value)
                visit(child, in_loop or is_loop(child))

        visit(scope, False)

    for node in ast.walk(tree):
        match node:
            case ast.Call(keywords=keywords):
                for keyword in keywords:
                    mark(keyword.value)
            case ast.ExceptHandler(body=handler_body):
                for statement in handler_body:
                    match statement:
                        case ast.Assign(value=value) | ast.AnnAssign(value=value):
                            mark(value)
            case ast.Module(body=body) | ast.ClassDef(body=body):
                for statement in body:
                    if isinstance(statement, ast.AnnAssign):
                        mark(statement.value)
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if node.name == "__init__":
                    for statement in ast.walk(node):
                        match statement:
                            case ast.Assign(targets=targets, value=value) if all(
                                is_self_attribute(target) for target in targets
                            ):
                                mark(value)
                            case ast.AnnAssign(target=target, value=value) if (
                                is_self_attribute(target)
                            ):
                                mark(value)
                exempt_scope_seeds(node)
    return exempt


def dict_get_exempt_lines(source: str) -> set[int]:
    """Return `.get(` lines whose AST context makes the call a decorator.

    A decorator is not payload access. ``@app.get("/path")`` names a route on
    a framework object, and no schema is being read out of a dict. Which
    lines are decorators is decidable from the tree alone, so this holds for
    a fragment that carries no types — and that is what lets a suppression
    here be retired instead of being demanded by the audit and refused by
    the kernel.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for decorator in node.decorator_list:
                last = decorator.end_lineno or decorator.lineno
                exempt.update(range(decorator.lineno, last + 1))
    return exempt


def refiner_for(rule_id: str) -> Callable[[str], set[int]] | None:
    """The AST context that narrows one rule, where the rule has one.

    A rule earns a refiner when its pattern is wider than the defect it names
    and the difference is decidable without types. The kernel resolves it from
    the id because a row projected into the hermetic runtime is primitive and
    cannot carry a callable; the rule declaration in `lup.codescan.antipatterns`
    holds the same function directly, and a test pins the two together.
    """
    match rule_id:
        case "empty-collection":
            return empty_collection_exempt_lines
        case "dict-get":
            return dict_get_exempt_lines
    return None


def refined_exempt_lines(
    source: str, rows: list[AntiPatternRow]
) -> dict[str, set[int]]:
    """Where each refined rule is cleared in this source, computed once."""
    found: dict[str, set[int]] = {}
    for row in rows:
        refiner = refiner_for(row["id"])
        if refiner is not None:
            found[row["id"]] = refiner(source)
    return found


def added_line_numbers(before: str | None, after: str | None) -> dict[int, bool]:
    """Identify added line positions with duplicate-line accounting."""
    remaining = before.splitlines() if before is not None else []
    added: dict[int, bool] = {}
    for number, line in enumerate((after or "").splitlines(), start=1):
        if line in remaining:
            remaining.remove(line)
        else:
            added[number] = True
    return added


def added_lines(before: str | None, after: str | None) -> list[str]:
    """Return added lines with duplicate-line accounting."""
    remaining = before.splitlines() if before is not None else []
    added: list[str] = []
    for line in (after or "").splitlines():
        if line in remaining:
            remaining.remove(line)
        else:
            added.append(line)
    return added


def is_record_class(node: ast.ClassDef) -> bool:
    """Recognize a declarative record whose field lines are not real changes."""
    records = ("BaseModel", "TypedDict", "Enum", "IntEnum", "StrEnum", "NamedTuple")
    return any(
        (isinstance(base, ast.Name) and base.id in records)
        or (isinstance(base, ast.Attribute) and base.attr in records)
        for base in node.bases
    )


def non_real_lines(source: str) -> set[int]:
    """Return line numbers that do not count toward the small-change gate.

    Blank lines, comments, string and docstring bodies (already blanked by
    ``python_code_lines``), imports, and the field declarations of a pydantic
    or ``TypedDict`` record are boilerplate rather than logic.
    """
    code = python_code_lines(source)
    excluded = {
        number
        for number, line in enumerate(code, start=1)
        if not line or line.isspace()
    }
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return excluded
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom) and node.end_lineno:
            excluded.update(range(node.lineno, node.end_lineno + 1))
        if isinstance(node, ast.ClassDef) and is_record_class(node):
            for statement in node.body:
                if (
                    isinstance(statement, ast.AnnAssign | ast.Assign)
                    and statement.end_lineno
                ):
                    excluded.update(range(statement.lineno, statement.end_lineno + 1))
    return excluded


def real_added_line_count(
    before: str | None, after: str | None, python_source: bool
) -> int:
    """Count added lines that carry real code, ignoring boilerplate."""
    added = added_line_numbers(before, after)
    lines = (after or "").splitlines()
    if not python_source:
        return sum(
            1
            for number in added
            if lines[number - 1] and not lines[number - 1].isspace()
        )
    excluded = non_real_lines(after or "")
    return sum(1 for number in added if number not in excluded)


def ignore_rule_ids(match: re.Match[str]) -> tuple[str, ...] | None:
    """Return typed ids, or ``None`` for a bare suppression."""
    raw = match.group("ids")
    if raw is None:
        return None
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def file_ignore(source: str) -> tuple[bool, tuple[str, ...] | None]:
    """Return whether a file-level suppression exists and the ids it names."""
    for line in source.splitlines()[:10]:
        match = FILE_IGNORE_RE.match(line)
        if match is not None:
            return True, ignore_rule_ids(match)
    return False, ()


def suppression_site(number: int, line: str) -> str:
    """One suppression, located and quoted so it can be read before approving."""
    return f"line {number}: {line.strip()[:160]}"


def suppression_reason(sites: list[str]) -> str:
    """Name every suppression this edit declares, not merely that it declares one.

    A permission prompt carries the reason and nothing else, so a verdict
    that said only what kind of thing happened left the reviewer to find the
    line themselves — in a diff they were being asked to approve precisely
    because it needed reading. Every site is listed rather than the first,
    since approving is one decision over the whole batch.
    """
    return "edit introduces an antipattern suppression\n" + "\n".join(sites)


def antipattern_decision(
    before: str | None,
    after: str,
    rows: list[AntiPatternRow],
    python_source: bool,
    allowances: list[str] | None = None,
) -> KernelDecision | None:
    """Reject newly added unsuppressed anti-patterns and ask on suppressions.

    Each row carries the syntactic context it inspects: a "code" rule is
    matched against token-masked Python (string literals and comments both
    blanked) so prose never trips it, while a "comment" rule targets comment
    directives and sees comments intact. Without a tokenizer (non-Python
    files, fragments that fail to tokenize) every rule scans the raw line.

    A granted ``antipattern-suppression`` allowance turns the two suppression
    asks into allows, because a human already approved the plan that needs
    them. It never touches the deny below: an allowance justifies a typed,
    argued suppression, never a bare anti-pattern.
    """
    suppression = "allow" if "antipattern-suppression" in (allowances or []) else "ask"
    added = added_line_numbers(before, after)
    original_lines = after.splitlines()
    scanned_lines = (
        mask_python_string_literals(after) if python_source else original_lines
    )
    code_lines = python_code_lines(after) if python_source else original_lines
    exempt = refined_exempt_lines(after, rows) if python_source else {}
    comment_columns = python_comment_columns(after) if python_source else None
    has_file_ignore, disabled_ids = file_ignore(after)
    declared: list[str] = []
    for number in added:
        original = original_lines[number - 1]
        directive = IGNORE_RE.search(original)
        if directive is not None and (
            not python_source
            or comment_columns is None
            or (
                number in comment_columns
                and comment_columns[number] == directive.start()
            )
        ):
            declared.append(suppression_site(number, original))
    if declared:
        return KernelDecision(suppression, suppression_reason(declared))
    tokenized = comment_columns is not None
    for number in added:
        masked = scanned_lines[number - 1].strip()
        if not tokenized and masked.startswith("#") and "type:" not in masked:
            continue
        code = code_lines[number - 1].strip()
        for row in rows:
            rule_id = row["id"]
            message = row["message"]
            stripped = code if tokenized and row["context"] == "code" else masked
            if not stripped:
                continue
            if rule_id in exempt and number in exempt[rule_id]:
                continue
            if re.search(row["pattern"], stripped) is None:
                continue
            if has_file_ignore and (disabled_ids is None or rule_id in disabled_ids):
                continue
            original = original_lines[number - 1]
            directive = IGNORE_RE.search(original)
            if directive is not None:
                covered = ignore_rule_ids(directive)
                if covered is None or rule_id in covered:
                    return KernelDecision(
                        suppression,
                        suppression_reason([suppression_site(number, original)]),
                    )
            return KernelDecision(
                "deny",
                f"line {number}: {message} (rule {rule_id} — see docs/rules.md)",
            )
    return None


def normalized_path(path: str) -> str:
    """Normalize one portable path without resolving against the filesystem."""
    return posixpath.normpath(path.replace("\\", "/"))


def path_rule_matches(path: str, path_exists: bool, row: PathRuleRow) -> bool:
    """Evaluate one primitive protected-path rule."""
    kind = row["kind"]
    value = row["value"]
    portable = normalized_path(path)
    expected = normalized_path(value)
    parts = tuple(part for part in portable.split("/") if part)
    match kind:
        case "exact":
            return portable == expected
        case "subtree":
            return portable == expected or portable.startswith(expected + "/")
        case "name_prefix":
            return posixpath.basename(portable).startswith(value)
        case "new_subtree":
            return (
                portable == expected or portable.startswith(expected + "/")
            ) and not path_exists
        case "contains_part":
            return value in parts and not (
                portable == f"/{value}" or portable.startswith(f"/{value}/")
            )
        case "new_devtools":
            return (
                any(
                    parts[index] == "src"
                    and index + 2 < len(parts)
                    and parts[index + 2] == "devtools"
                    for index in range(len(parts))
                )
                and not path_exists
            )
        case _:
            raise ValueError(f"invalid path rule kind {kind!r}")


def decide_edit(
    path: str,
    before: str | None,
    after: str | None,
    *,
    path_exists: bool,
    path_rules: list[PathRuleRow],
    antipattern_rows: list[AntiPatternRow],
    path_roles: list[PathRoleRow] | None = None,
    maximum_added_lines: int = 3,
    autonomous: bool = False,
    allowances: list[str] | None = None,
    python_source: bool = False,
) -> KernelDecision:
    """Apply anti-pattern, path, marker, full-write, deletion, and size gates.

    ``allowances`` names what a human already approved for the concern this
    edit belongs to. A grant releases exactly the gate it names and nothing
    adjacent, so an ungranted session sees the unchanged lattice.

    The marker gate counts review notes only, because the two marker families
    are gated in opposite directions. Deleting feedback before its concern is
    resolved is the act the conventions forbid, so notes gate on a changed
    count. A suppression is gated where it is declared — an added line
    carrying an `ignore` directive, which :func:`antipattern_decision` asks
    about — while retiring one needs no gate at all: the same decision
    re-reads the uncovered line, allows it where nothing trips, and denies
    where the violation is still live. What makes that verdict trustworthy is
    :func:`refined_exempt_lines`, without which a rule broader than the defect
    it names holds its own suppression in place forever.

    Each gate reaches as far as its own reason. Anti-patterns and the size
    gate describe how production code should read and stop at production;
    the marker gate follows the feedback instead and stops only at scratch,
    where nothing persists to be read.
    """
    granted = allowances or []
    previous = before or ""
    updated = after or ""
    role = path_role(path, path_roles or [])
    # The conventions describe how production code should read. A test's
    # subject is production's behaviour, and scratch is disposable, so
    # neither is judged against them.
    if after is not None and role == "production":
        antipattern = antipattern_decision(
            before, after, antipattern_rows, python_source, granted
        )
        # A granted suppression answers this gate and no other, so an allow
        # falls through to the rest of the lattice rather than ending it.
        if antipattern is not None and antipattern.effect != "allow":
            return antipattern
    protected = next(
        (
            row
            for row in path_rules
            if path_rule_matches(path, path_exists, row)
            and not (row["kind"] == "new_devtools" and "new-devtools-module" in granted)
        ),
        None,
    )
    if protected is not None and not (autonomous and protected["allow_autonomous"]):
        return KernelDecision("ask", protected["reason"])
    # Feedback is feedback wherever it is left, so this gate follows the file
    # rather than the conventions: a note on a test still names work somebody
    # owes. Scratch is the exception, and only because nothing there persists
    # to be read — a note in a disposable tree has no reader to protect.
    if role != "scratch" and review_marker_count(
        previous, python_source
    ) != review_marker_count(updated, python_source):
        return KernelDecision("ask", "edit changes inline review markers")
    if before is None:
        if autonomous:
            return KernelDecision("allow", "reviewed autonomous full write")
        return KernelDecision("ask", "full-file writes require approval")
    if after is None or after == "":
        return KernelDecision("allow", "pure deletion")
    if (
        role == "production"
        and real_added_line_count(before, after, python_source) > maximum_added_lines
    ):
        if autonomous:
            return KernelDecision("allow", "reviewed autonomous edit")
        return KernelDecision("defer", "edit exceeds the small-change gate")
    return KernelDecision("allow", "small safe edit")
