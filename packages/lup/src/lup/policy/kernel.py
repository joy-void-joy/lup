# lup: ignore[empty-collection, import-re, re-call, set-shape, string-split, tuple-shape]
# The dependency-free runtime deliberately uses primitive rows and stdlib scanners.
"""Hermetic semantic policy kernel shared by library and generated runtimes."""

import ast
import io
import posixpath
import re
import shlex
import tokenize
import urllib.parse

type UrlScopeRow = tuple[str, str, int | None, str, str]
type PathRuleRow = tuple[str, str, str, bool]
type AntiPatternRow = tuple[str, str, str]

KERNEL_IMPORT_ALLOWLIST = (
    "ast",
    "io",
    "posixpath",
    "re",
    "shlex",
    "tokenize",
    "urllib.parse",
)
SHELL_PUNCTUATION = ";&|<>\n"
PASS_THROUGH_WORDS = (
    "sudo",
    "env",
    "command",
    "exec",
    "time",
    "nohup",
    "setsid",
    "stdbuf",
)
READ_ONLY_COMMANDS = (
    "ls",
    "tree",
    "grep",
    "cat",
    "echo",
    "test",
    "file",
    "wc",
    "head",
    "tail",
    "find",
)
INTERPRETERS = (
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "deno",
    "bun",
    "php",
)
MARKER_RE = re.compile(r"(#|//)\s*lup\s*:", re.IGNORECASE)
IGNORE_RE = re.compile(
    r"(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?",
    re.IGNORECASE,
)
FILE_IGNORE_RE = re.compile(
    r"^\s*(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?\s*$",
    re.IGNORECASE,
)


class KernelDecision:
    """Dependency-free allow, ask, or deny result."""

    effect: str
    reason: str

    def __init__(self, effect: str, reason: str = "") -> None:
        if effect not in ("allow", "ask", "deny"):
            raise ValueError(f"invalid kernel decision effect {effect!r}")
        self.effect = effect
        self.reason = reason


def command_words(words: list[str]) -> list[str]:
    """Skip assignments and transparent wrappers to the effective command."""
    for position, word in enumerate(words):
        name, separator, _value = word.partition("=")
        if separator and name.isidentifier():
            continue
        if posixpath.basename(word) in PASS_THROUGH_WORDS:
            continue
        return words[position:]
    return []


def uv_run_words(words: list[str]) -> list[str]:
    """Return the executable portion of a ``uv run`` invocation."""
    position = 2
    value_options = (
        "--directory",
        "--package",
        "--project",
        "--with",
        "--with-editable",
    )
    while position < len(words) and words[position].startswith("-"):
        option = words[position]
        if option in ("-c", "-m", "--script"):
            return words[position:]
        position += 2 if option in value_options else 1
    return words[position:]


def is_repository_tmp_script(word: str) -> bool:
    """Recognize only a script beneath the repository-relative ``tmp`` root."""
    normalized = posixpath.normpath(word)
    return not normalized.startswith("/") and normalized.split("/")[0] == "tmp"


def decide_shell_segment(segment: list[str]) -> KernelDecision:
    """Classify one parsed shell segment."""
    words = command_words(segment)
    if not words:
        return KernelDecision("ask", "shell segment has no command")
    executable = posixpath.basename(words[0])
    if executable in INTERPRETERS:
        return KernelDecision(
            "deny", "bare interpreters and inline code are not allowed"
        )
    if executable in READ_ONLY_COMMANDS:
        if executable == "find" and any(
            word in ("-exec", "-ok", "-delete") for word in words
        ):
            return KernelDecision("ask", "find requests a mutating action")
        return KernelDecision("allow")
    if executable == "cd":
        return KernelDecision("allow", "directory navigation")
    if executable == "xargs":
        payload = [word for word in words[1:] if not word.startswith("-")]
        if not payload:
            return KernelDecision("ask", "xargs payload is not classified")
        return decide_shell_segment(payload)
    if (
        executable == "git"
        and len(words) > 1
        and words[1]
        in (
            "status",
            "log",
            "diff",
            "show",
            "branch",
            "worktree",
            "stash",
            "remote",
            "fetch",
            "tag",
            "add",
            "commit",
            "mv",
        )
    ):
        return KernelDecision("allow")
    if (
        executable == "gh"
        and len(words) > 2
        and words[1] in ("pr", "issue")
        and words[2] in ("list", "view", "diff", "status")
    ):
        return KernelDecision("allow")
    if executable == "uvx":
        if len(words) > 1 and posixpath.basename(words[1]) in INTERPRETERS:
            return KernelDecision("deny", "inline code is not allowed")
        return KernelDecision("ask", "uvx command is not classified")
    if executable == "uv" and len(words) > 1:
        if words[1] in ("add", "sync"):
            return KernelDecision(
                "ask", "dependency changes fetch and execute external code"
            )
        if words[1] in ("remove", "lock"):
            return KernelDecision("allow")
        if words[1] == "run" and len(words) > 2:
            run_words = uv_run_words(words)
            if not run_words:
                return KernelDecision("ask", "uv run has no command")
            run_command = posixpath.basename(run_words[0])
            script = (
                run_words[1]
                if run_command in INTERPRETERS and len(run_words) > 1
                else run_words[0]
            )
            if is_repository_tmp_script(script):
                return KernelDecision("allow", "declared temporary script")
            if run_command in ("pyright", "pytest", "ruff", "lup-devtools"):
                return KernelDecision("allow")
            if len(run_words) == 2 and run_words[1] == "--help":
                return KernelDecision("allow", "command help is read-only")
            if run_command in INTERPRETERS or run_command in (
                "-c",
                "-m",
                "--script",
            ):
                return KernelDecision("deny", "inline code is not allowed")
    return KernelDecision("ask", f"command {executable!r} is not classified")


def parse_shell_words(command: str) -> list[list[str]] | None:
    """Parse shell words into independent segments, rejecting opaque syntax."""
    if any(marker in command for marker in ("$(", "<(", ">(", "`")):
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(character in SHELL_PUNCTUATION for character in token):
            if "<" in token or ">" in token:
                return None
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments or None


def decide_shell(command: str) -> KernelDecision:
    """Conservatively classify every segment in one shell command."""
    segments = parse_shell_words(command)
    if segments is None:
        return KernelDecision("ask", "shell command has no executable segment")
    decisions = [decide_shell_segment(segment) for segment in segments]
    denied = next((item for item in decisions if item.effect == "deny"), None)
    if denied is not None:
        return denied
    asked = next((item for item in decisions if item.effect == "ask"), None)
    if asked is not None:
        return asked
    return KernelDecision("allow", "every shell segment is declared safe")


def url_matches_scope(
    scheme: str,
    hostname: str,
    port: int | None,
    path: str,
    scope: UrlScopeRow,
) -> bool:
    """Compare parsed URL components with one primitive scope row."""
    expected_scheme, expected_host, expected_port, path_prefix, _reason = scope
    return (
        scheme == expected_scheme
        and hostname == expected_host
        and port == expected_port
        and path.startswith(path_prefix)
    )


def decide_fetch(
    url: str,
    allowed_scopes: list[UrlScopeRow],
    denied_scopes: list[UrlScopeRow],
) -> KernelDecision:
    """Deny matching scopes first, allow declared scopes, and ask otherwise."""
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return KernelDecision("ask", "malformed URL requires approval")
    if not parsed.scheme or hostname is None:
        return KernelDecision("ask", "malformed URL requires approval")
    denied = next(
        (
            scope
            for scope in denied_scopes
            if url_matches_scope(parsed.scheme, hostname, port, parsed.path, scope)
        ),
        None,
    )
    if denied is not None:
        return KernelDecision("deny", denied[4] or "URL is denied")
    allowed = next(
        (
            scope
            for scope in allowed_scopes
            if url_matches_scope(parsed.scheme, hostname, port, parsed.path, scope)
        ),
        None,
    )
    if allowed is not None:
        return KernelDecision("allow", allowed[4])
    return KernelDecision("ask", "URL is outside the declared documentation scopes")


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


def marker_count(source: str, python_source: bool = False) -> int:
    """Count review markers, excluding markers inside ordinary Python strings."""
    if not python_source:
        return len(MARKER_RE.findall(source))
    tokens = python_tokens(source)
    if tokens is None:
        return len(MARKER_RE.findall(source))
    documentation = docstring_lines(source)
    return sum(
        len(MARKER_RE.findall(token.string))
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
            case ast.ClassDef(body=body):
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


def antipattern_decision(
    before: str | None,
    after: str,
    rows: list[AntiPatternRow],
    python_source: bool,
) -> KernelDecision | None:
    """Reject newly added unsuppressed anti-patterns and ask on suppressions."""
    added = added_line_numbers(before, after)
    original_lines = after.splitlines()
    scanned_lines = (
        mask_python_string_literals(after) if python_source else original_lines
    )
    exempt = empty_collection_exempt_lines(after) if python_source else set()
    comment_columns = python_comment_columns(after) if python_source else None
    has_file_ignore, disabled_ids = file_ignore(after)
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
            return KernelDecision("ask", "edit introduces an antipattern suppression")
    for number in added:
        stripped = scanned_lines[number - 1].strip()
        if not stripped or (stripped.startswith("#") and "type:" not in stripped):
            continue
        for rule_id, pattern, message in rows:
            if rule_id == "empty-collection" and number in exempt:
                continue
            if re.search(pattern, stripped) is None:
                continue
            if has_file_ignore and (disabled_ids is None or rule_id in disabled_ids):
                continue
            directive = IGNORE_RE.search(original_lines[number - 1])
            if directive is not None:
                covered = ignore_rule_ids(directive)
                if covered is None or rule_id in covered:
                    return KernelDecision(
                        "ask", "edit introduces an antipattern suppression"
                    )
            return KernelDecision("deny", message)
    return None


def normalized_path(path: str) -> str:
    """Normalize one portable path without resolving against the filesystem."""
    return posixpath.normpath(path.replace("\\", "/"))


def path_rule_matches(path: str, path_exists: bool, row: PathRuleRow) -> bool:
    """Evaluate one primitive protected-path rule."""
    kind, value, _reason, _allow_autonomous = row
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
    maximum_added_lines: int = 3,
    autonomous: bool = False,
    python_source: bool = False,
) -> KernelDecision:
    """Apply marker, anti-pattern, path, full-write, deletion, and size gates."""
    previous = before or ""
    updated = after or ""
    if marker_count(previous, python_source) != marker_count(updated, python_source):
        return KernelDecision("ask", "edit changes inline review markers")
    if after is not None:
        antipattern = antipattern_decision(
            before, after, antipattern_rows, python_source
        )
        if antipattern is not None:
            return antipattern
    protected = next(
        (row for row in path_rules if path_rule_matches(path, path_exists, row)),
        None,
    )
    if protected is not None and not (autonomous and protected[3]):
        return KernelDecision("ask", protected[2])
    if before is None:
        if autonomous:
            return KernelDecision("allow", "reviewed autonomous full write")
        return KernelDecision("ask", "full-file writes require approval")
    if after is None or after == "":
        return KernelDecision("allow", "pure deletion")
    if len(added_lines(before, after)) > maximum_added_lines:
        if autonomous:
            return KernelDecision("allow", "reviewed autonomous edit")
        return KernelDecision("ask", "edit exceeds the small-change gate")
    return KernelDecision("allow", "small safe edit")
