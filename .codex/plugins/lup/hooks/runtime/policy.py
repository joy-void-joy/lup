# lup: ignore[dict-get, import-re, re-call, string-split, set-shape, empty-collection]
"""Generated hermetic semantic policy runtime."""

import ast
import base64
import json
import re
import shlex
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


class Decision:
    def __init__(self, effect, reason=""):
        self.effect = effect
        self.reason = reason


SHELL_PUNCTUATION = ";&|<>\n"
PASS_THROUGH = {
    "sudo": True,
    "env": True,
    "command": True,
    "exec": True,
    "time": True,
    "nohup": True,
    "setsid": True,
    "stdbuf": True,
}
READ_ONLY = {
    "ls": True,
    "tree": True,
    "grep": True,
    "cat": True,
    "echo": True,
    "test": True,
    "file": True,
    "wc": True,
    "head": True,
    "tail": True,
    "find": True,
}
INTERPRETERS = {
    "python": True,
    "python3": True,
    "perl": True,
    "ruby": True,
    "node": True,
    "deno": True,
    "bun": True,
    "php": True,
}


def decide_shell(command):
    if any(marker in command for marker in ["$(", "<(", ">(", "`"]):
        return Decision("ask", "command or process substitution requires approval")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SHELL_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return Decision("ask", "malformed shell input requires approval")
    segments = [[]]
    for token in tokens:
        if token and all(character in SHELL_PUNCTUATION for character in token):
            if "<" in token or ">" in token:
                return Decision("ask", "shell redirection requires approval")
            if segments[-1]:
                segments.append([])
        else:
            segments[-1].append(token)
    segments = [segment for segment in segments if segment]
    decisions = [decide_segment(segment) for segment in segments]
    denied = next((item for item in decisions if item.effect == "deny"), None)
    if denied is not None:
        return denied
    asked = next((item for item in decisions if item.effect == "ask"), None)
    if asked is not None:
        return asked
    return Decision("allow", "every shell segment is declared safe")


def command_words(words):
    position = 0
    while position < len(words):
        word = words[position]
        name, separator, _value = word.partition("=")  # lup: ignore[string-split]
        if separator and name.isidentifier():
            position += 1
            continue
        if PurePosixPath(word).name in PASS_THROUGH:
            position += 1
            continue
        return words[position:]
    return []


def uv_run_words(words):
    position = 2
    value_options = {
        "--directory": True,
        "--package": True,
        "--project": True,
        "--with": True,
        "--with-editable": True,
    }
    while position < len(words) and words[position].startswith("-"):
        option = words[position]
        if option in {"-c": True, "-m": True, "--script": True}:
            return words[position:]
        position += 2 if option in value_options else 1
    return words[position:]


def is_repository_tmp_script(word):
    path = PurePosixPath(word)
    return not path.is_absolute() and bool(path.parts) and path.parts[0] == "tmp"


def decide_segment(segment):
    words = command_words(segment)
    if not words:
        return Decision("ask", "shell segment has no command")
    executable = PurePosixPath(words[0]).name
    if executable in INTERPRETERS:
        return Decision("deny", "bare interpreters and inline code are denied")
    if executable in READ_ONLY:
        if executable == "find" and any(
            word in {"-exec": True, "-ok": True, "-delete": True} for word in words
        ):
            return Decision("ask", "find requests a mutating action")
        return Decision("allow")
    if executable == "cd":
        return Decision("allow", "directory navigation")
    if executable == "xargs":
        payload = [word for word in words[1:] if not word.startswith("-")]
        if not payload:
            return Decision("ask", "xargs payload is not classified")
        return decide_segment(payload)
    if (
        executable == "git"
        and len(words) > 1
        and words[1]
        in {
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
        }
    ):
        return Decision("allow")
    if (
        executable == "gh"
        and len(words) > 2
        and words[1] in {"pr", "issue"}
        and words[2] in {"list", "view", "diff", "status"}
    ):
        return Decision("allow")
    if executable == "uvx":
        if len(words) > 1 and PurePosixPath(words[1]).name in INTERPRETERS:
            return Decision("deny", "inline code is denied")
        return Decision("ask", "uvx command is not classified")
    if executable == "uv" and len(words) > 1:
        if words[1] in {"add", "sync"}:
            return Decision("ask", "dependency changes execute external code")
        if words[1] in {"remove", "lock"}:
            return Decision("allow")
        if words[1] == "run" and len(words) > 2:
            run_words = uv_run_words(words)
            if not run_words:
                return Decision("ask", "uv run has no command")
            run_command = PurePosixPath(run_words[0]).name
            script = (
                run_words[1]
                if run_command in INTERPRETERS and len(run_words) > 1
                else run_words[0]
            )
            if is_repository_tmp_script(script):
                return Decision("allow", "declared temporary script")
            if run_command in {"pyright", "pytest", "ruff", "lup-devtools"}:
                return Decision("allow")
            if len(run_words) == 2 and run_words[1] == "--help":
                return Decision("allow", "command help is read-only")
            if run_command in INTERPRETERS or run_command in {"-c", "-m", "--script"}:
                return Decision("deny", "inline code is denied")
    return Decision("ask", "command is not classified")


def url_in_scope(parsed, scope):
    expected = urlsplit(scope["origin"])
    try:
        return (
            parsed.scheme == expected.scheme
            and parsed.hostname == expected.hostname
            and parsed.port == expected.port
            and parsed.path.startswith(scope["path_prefix"])
        )
    except ValueError:
        return False


def decide_fetch(url, allowed_scopes, denied_scopes):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError:
        return Decision("ask", "malformed URL requires approval")
    if not parsed.scheme or host is None:
        return Decision("ask", "malformed URL requires approval")
    if any(url_in_scope(parsed, scope) for scope in denied_scopes):
        return Decision("deny", "URL host is denied")
    if any(url_in_scope(parsed, scope) for scope in allowed_scopes):
        return Decision("allow", "URL host is declared documentation")
    return Decision("ask", "URL host is not classified")


MARKER_RE = re.compile(r"(#|//)\s*lup\s*:", re.IGNORECASE)
IGNORE_RE = re.compile(
    r"(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?",
    re.IGNORECASE,
)
RESOLVE_EDITOR_AGENTS = {"resolve-editor", "lup:resolve-editor"}


def ignore_covers(line, rule_id):
    match = IGNORE_RE.search(line)
    if match is None:
        return False
    ids = match.group("ids")
    if ids is None:
        return True
    return rule_id in {item.strip() for item in ids.split(",") if item.strip()}


def antipattern_decision(path, before, after):
    rows = ANTI_PATTERN_ROWS.get(PurePosixPath(path).suffix.lower())
    if rows is None:
        return None
    remaining = before.splitlines() if before is not None else []
    added = []
    for number, line in enumerate(after.splitlines(), start=1):
        if line in remaining:
            remaining.remove(line)
        else:
            added.append((number, line))
    python_source = PurePosixPath(path).suffix in {".py", ".pyi"}
    docstrings = python_docstring_lines(after) if python_source else set()
    exempt = empty_collection_exempt_lines(after) if python_source else set()
    for number, line in added:
        if number in docstrings:
            continue
        stripped = line.strip()
        if not stripped or (stripped.startswith("#") and "type:" not in stripped):
            continue
        for rule_id, pattern, message in rows:
            if rule_id == "empty-collection" and number in exempt:
                continue
            if re.search(pattern, stripped) is None:
                continue
            if ignore_covers(line, rule_id):
                return Decision("ask", "edit introduces an antipattern suppression")
            return Decision("deny", message)
    return None


def is_tmp_path(path):
    parts = PurePosixPath(path).parts
    return parts[:2] != ("/", "tmp") and "tmp" in parts


def is_protected(path, protected_roots):
    portable = PurePosixPath(path)
    return any(
        portable == PurePosixPath(root) or portable.is_relative_to(PurePosixPath(root))
        for root in protected_roots
        if root != "tmp"
    ) or portable.name.startswith(".env")


def is_new_devtools(path):
    parts = PurePosixPath(path).parts
    try:
        src_index = parts.index("src")
    except ValueError:
        return False
    return (
        len(parts) > src_index + 2
        and parts[src_index + 2] == "devtools"
        and not Path(path).exists()
    )


def decide_edit(path, before, after, protected_roots, agent_type=""):
    autonomous = agent_type in RESOLVE_EDITOR_AGENTS
    previous = before or ""
    if len(MARKER_RE.findall(previous)) != len(MARKER_RE.findall(after)):
        return Decision("ask", "inline review marker changes require approval")
    antipattern = antipattern_decision(path, before, after)
    if antipattern is not None:
        return antipattern
    if is_tmp_path(path):
        return Decision("ask", "scratch path requires approval")
    if is_protected(path, protected_roots) and not autonomous:
        return Decision("ask", "protected path requires approval")
    if is_new_devtools(path) and not autonomous:
        return Decision("ask", "new devtools module requires approval")
    if before is None:
        if autonomous:
            return Decision("allow", "reviewed autonomous full write")
        return Decision("ask", "full-file writes require approval")
    if not after:
        return Decision("allow", "pure deletion")
    before_lines = before.splitlines()
    added = [line for line in after.splitlines() if line not in before_lines]
    if len(added) > 3:
        if autonomous:
            return Decision("allow", "reviewed autonomous edit")
        return Decision("ask", "edit exceeds the small-change gate")
    return Decision("allow", "small safe edit")


def python_docstring_lines(text: str) -> set[int]:
    """Lines (1-based) covered by a docstring — module, class, function, or
    the attribute-docstring convention (a bare string statement after a field
    or alias).

    Every bare string-expression statement is documentation by construction —
    it has no runtime effect — so it is prose where a note belongs, unlike an
    ordinary string such as an echoed message (those are operands, not
    statements). Returns an empty set when the source cannot be parsed; the
    comment scan still runs.
    """
    try:
        tree = ast.parse(text)
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


def empty_collection_exempt_lines(source: str) -> set[int]:
    """1-based lines whose empty-collection literal is a deliberate default.

    The empty-collection regex is a broad trigger; this refiner reads the
    AST and exempts the shapes whose whole point is an empty start:

    - ``self.<attr> = []`` (plain or annotated) inside ``__init__`` —
      instance state that accumulates over the object's life;
    - an annotated class-body field default (``x: list[str] = []``) — a
      declared typed default (pydantic copies it per instance);
    - a call keyword (``f(x=[])``) — an explicitly passed empty value;
    - a direct assignment in an ``except`` handler body — the
      degrade-to-empty fallback shape, which by construction is not a
      mutate-loop seed (a loop nested inside the handler still trips);
    - a function-local name that no loop mutates — conditional builds,
      branch defaults, and closure accumulators have no loop to fold,
      so there is no comprehension to prefer;
    - a seed whose every feeding loop carries a ``try`` within it — the
      per-item fault tolerance a comprehension cannot express;
    - a reassignment to empty inside a loop that also mutates the name —
      a stateful parse's reset, not a seed.

    Plain fold seeds (``x = []`` then unguarded ``.append`` in a loop),
    multi-accumulator and match-arm folds, and bare module-level seeds
    still trip the rule: those either want a comprehension or carry
    their marker deliberately. Unparseable source exempts nothing, so both
    consumers — the generated policy runtime and the tree auditor — fall back
    to the plain regex verdict. The function is self-contained over the stdlib
    ``ast`` module so harness generation can embed its source verbatim.
    """
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
        match node:
            case ast.Attribute(value=ast.Name(id="self")):
                return True
        return False

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
                in {
                    "append",
                    "appendleft",
                    "extend",
                    "add",
                    "update",
                    "insert",
                    "setdefault",
                }
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
        # For each name: one entry per feeding loop, True when that loop
        # carries a try (per-item tolerance) somewhere inside it.
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
                        continue  # a nested scope judges its own seeds
                    case (
                        ast.Assign(targets=[ast.Name(id=name)], value=value)
                        | ast.AnnAssign(target=ast.Name(id=name), value=value)
                    ) if is_empty_literal(value):
                        loops = feeding.get(name)
                        if in_loop:
                            if loops is not None:
                                mark(value)  # a reset inside the loop refilling it
                        elif loops is None or all(loops):
                            mark(value)  # loop-free, or every feeding loop tolerant
                visit(child, in_loop or is_loop(child))

        visit(scope, False)

    for node in ast.walk(tree):
        match node:
            case ast.Call(keywords=keywords):
                for keyword in keywords:
                    mark(keyword.value)
            case ast.ExceptHandler(body=handler_body):
                for stmt in handler_body:
                    match stmt:
                        case ast.Assign(value=value) | ast.AnnAssign(value=value):
                            mark(value)
            case ast.ClassDef(body=body):
                for stmt in body:
                    if isinstance(stmt, ast.AnnAssign):
                        mark(stmt.value)
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if node.name == "__init__":
                    for stmt in ast.walk(node):
                        match stmt:
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


ANTI_PATTERN_ROWS = json.loads(
    base64.b64decode(
        """
        eyIuanMiOiBbWyJhcy1hbnkiLCAiXFxiYXNcXHMrYW55XFxiIiwgIk5ldmVyIHVzZSBgYXMgYW55YCBcdTIwMTQg
        dXNlIHByb3BlciB0eXBlcyBvciB0eXBlIGd1YXJkcyJdLCBbImFzLXVua25vd24iLCAiXFxiYXNcXHMrdW5rbm93
        blxcYiIsICJOZXZlciB1c2UgYGFzIHVua25vd25gIFx1MjAxNCB1c2UgdHlwZSBndWFyZHMgb3IgcHJvcGVyIHR5
        cGVzIl0sIFsiYW55LWFubm90YXRpb24iLCAiOlxccyphbnlcXGIiLCAiTmV2ZXIgdXNlIGBhbnlgIHR5cGUgYW5u
        b3RhdGlvbiBcdTIwMTQgdXNlIHNwZWNpZmljIHR5cGVzLCBnZW5lcmljcywgb3IgYHVua25vd25gIl0sIFsiYW55
        LWFzc2VydGlvbiIsICI8YW55PiIsICJOZXZlciB1c2UgYDxhbnk+YCB0eXBlIGFzc2VydGlvbiBcdTIwMTQgdXNl
        IHByb3BlciB0eXBlcyJdLCBbInRzLWlnbm9yZSIsICJAdHMtaWdub3JlIiwgIk5ldmVyIHVzZSBAdHMtaWdub3Jl
        IFx1MjAxNCBmaXggdGhlIHR5cGUgZXJyb3IgcHJvcGVybHkiXSwgWyJ0cy1leHBlY3QtZXJyb3IiLCAiQHRzLWV4
        cGVjdC1lcnJvciIsICJOZXZlciB1c2UgQHRzLWV4cGVjdC1lcnJvciBcdTIwMTQgZml4IHRoZSB0eXBlIGVycm9y
        IHByb3Blcmx5Il0sIFsidHMtbm9jaGVjayIsICJAdHMtbm9jaGVjayIsICJOZXZlciB1c2UgQHRzLW5vY2hlY2sg
        XHUyMDE0IGZpeCB0aGUgdHlwZSBlcnJvcnMgaW4gdGhlIGZpbGUiXSwgWyJlc2xpbnQtZGlzYWJsZSIsICIvL1xc
        cyplc2xpbnQtZGlzYWJsZSIsICJOZXZlciB1c2UgZXNsaW50LWRpc2FibGUgXHUyMDE0IGZpeCB0aGUgbGludCBp
        c3N1ZSBwcm9wZXJseSJdLCBbImVzbGludC1kaXNhYmxlLWJsb2NrIiwgIi9cXCpcXHMqZXNsaW50LWRpc2FibGUi
        LCAiTmV2ZXIgdXNlIGVzbGludC1kaXNhYmxlIFx1MjAxNCBmaXggdGhlIGxpbnQgaXNzdWUgcHJvcGVybHkiXSwg
        WyJ0c2xpbnQtZGlzYWJsZSIsICIvL1xccyp0c2xpbnQ6ZGlzYWJsZSIsICJOZXZlciB1c2UgdHNsaW50OmRpc2Fi
        bGUgXHUyMDE0IG1pZ3JhdGUgdG8gZXNsaW50IGFuZCBmaXggdGhlIGlzc3VlIl0sIFsibm9uLW51bGwtYXNzZXJ0
        aW9uIiwgIltcXHdcXClcXF1dIVxcLiIsICJQb3N0Zml4IGAhLmAgbm9uLW51bGwgYXNzZXJ0aW9uIGhpZGVzIGEg
        cG9zc2libGUgbnVsbC91bmRlZmluZWQgXHUyMDE0IG5hcnJvdyB0aGUgdHlwZSBvciBoYW5kbGUgdGhlIG1pc3Np
        bmcgY2FzZSJdLCBbInZhci1kZWNsYXJhdGlvbiIsICJcXGJ2YXJcXHMrW0EtWmEtel8kXSIsICJVc2UgYGNvbnN0
        YCBvciBgbGV0YCBpbnN0ZWFkIG9mIGB2YXJgIFx1MjAxNCB2YXIgaXMgZnVuY3Rpb24tc2NvcGVkIGFuZCBob2lz
        dGVkIl0sIFsiZnVuY3Rpb24tb2JqZWN0LXR5cGUiLCAiOlxccyooPzpGdW5jdGlvbnxPYmplY3QpXFxiIiwgIk5l
        dmVyIHVzZSBgRnVuY3Rpb25gIG9yIGBPYmplY3RgIGFzIGEgdHlwZSBcdTIwMTQgZGVjbGFyZSB0aGUgY2FsbCBz
        aWduYXR1cmUgb3IgdGhlIG9iamVjdCBzaGFwZSJdLCBbImNvbnNvbGUtbG9nIiwgIlxcYmNvbnNvbGVcXC5sb2dc
        XHMqXFwoIiwgImNvbnNvbGUubG9nIGlzIGEgZGVidWcgbGVmdG92ZXIgXHUyMDE0IHJlbW92ZSBpdCBvciByb3V0
        ZSB0aHJvdWdoIGEgbG9nZ2VyIl1dLCAiLmpzeCI6IFtbImFzLWFueSIsICJcXGJhc1xccythbnlcXGIiLCAiTmV2
        ZXIgdXNlIGBhcyBhbnlgIFx1MjAxNCB1c2UgcHJvcGVyIHR5cGVzIG9yIHR5cGUgZ3VhcmRzIl0sIFsiYXMtdW5r
        bm93biIsICJcXGJhc1xccyt1bmtub3duXFxiIiwgIk5ldmVyIHVzZSBgYXMgdW5rbm93bmAgXHUyMDE0IHVzZSB0
        eXBlIGd1YXJkcyBvciBwcm9wZXIgdHlwZXMiXSwgWyJhbnktYW5ub3RhdGlvbiIsICI6XFxzKmFueVxcYiIsICJO
        ZXZlciB1c2UgYGFueWAgdHlwZSBhbm5vdGF0aW9uIFx1MjAxNCB1c2Ugc3BlY2lmaWMgdHlwZXMsIGdlbmVyaWNz
        LCBvciBgdW5rbm93bmAiXSwgWyJhbnktYXNzZXJ0aW9uIiwgIjxhbnk+IiwgIk5ldmVyIHVzZSBgPGFueT5gIHR5
        cGUgYXNzZXJ0aW9uIFx1MjAxNCB1c2UgcHJvcGVyIHR5cGVzIl0sIFsidHMtaWdub3JlIiwgIkB0cy1pZ25vcmUi
        LCAiTmV2ZXIgdXNlIEB0cy1pZ25vcmUgXHUyMDE0IGZpeCB0aGUgdHlwZSBlcnJvciBwcm9wZXJseSJdLCBbInRz
        LWV4cGVjdC1lcnJvciIsICJAdHMtZXhwZWN0LWVycm9yIiwgIk5ldmVyIHVzZSBAdHMtZXhwZWN0LWVycm9yIFx1
        MjAxNCBmaXggdGhlIHR5cGUgZXJyb3IgcHJvcGVybHkiXSwgWyJ0cy1ub2NoZWNrIiwgIkB0cy1ub2NoZWNrIiwg
        Ik5ldmVyIHVzZSBAdHMtbm9jaGVjayBcdTIwMTQgZml4IHRoZSB0eXBlIGVycm9ycyBpbiB0aGUgZmlsZSJdLCBb
        ImVzbGludC1kaXNhYmxlIiwgIi8vXFxzKmVzbGludC1kaXNhYmxlIiwgIk5ldmVyIHVzZSBlc2xpbnQtZGlzYWJs
        ZSBcdTIwMTQgZml4IHRoZSBsaW50IGlzc3VlIHByb3Blcmx5Il0sIFsiZXNsaW50LWRpc2FibGUtYmxvY2siLCAi
        L1xcKlxccyplc2xpbnQtZGlzYWJsZSIsICJOZXZlciB1c2UgZXNsaW50LWRpc2FibGUgXHUyMDE0IGZpeCB0aGUg
        bGludCBpc3N1ZSBwcm9wZXJseSJdLCBbInRzbGludC1kaXNhYmxlIiwgIi8vXFxzKnRzbGludDpkaXNhYmxlIiwg
        Ik5ldmVyIHVzZSB0c2xpbnQ6ZGlzYWJsZSBcdTIwMTQgbWlncmF0ZSB0byBlc2xpbnQgYW5kIGZpeCB0aGUgaXNz
        dWUiXSwgWyJub24tbnVsbC1hc3NlcnRpb24iLCAiW1xcd1xcKVxcXV0hXFwuIiwgIlBvc3RmaXggYCEuYCBub24t
        bnVsbCBhc3NlcnRpb24gaGlkZXMgYSBwb3NzaWJsZSBudWxsL3VuZGVmaW5lZCBcdTIwMTQgbmFycm93IHRoZSB0
        eXBlIG9yIGhhbmRsZSB0aGUgbWlzc2luZyBjYXNlIl0sIFsidmFyLWRlY2xhcmF0aW9uIiwgIlxcYnZhclxccytb
        QS1aYS16XyRdIiwgIlVzZSBgY29uc3RgIG9yIGBsZXRgIGluc3RlYWQgb2YgYHZhcmAgXHUyMDE0IHZhciBpcyBm
        dW5jdGlvbi1zY29wZWQgYW5kIGhvaXN0ZWQiXSwgWyJmdW5jdGlvbi1vYmplY3QtdHlwZSIsICI6XFxzKig/OkZ1
        bmN0aW9ufE9iamVjdClcXGIiLCAiTmV2ZXIgdXNlIGBGdW5jdGlvbmAgb3IgYE9iamVjdGAgYXMgYSB0eXBlIFx1
        MjAxNCBkZWNsYXJlIHRoZSBjYWxsIHNpZ25hdHVyZSBvciB0aGUgb2JqZWN0IHNoYXBlIl0sIFsiY29uc29sZS1s
        b2ciLCAiXFxiY29uc29sZVxcLmxvZ1xccypcXCgiLCAiY29uc29sZS5sb2cgaXMgYSBkZWJ1ZyBsZWZ0b3ZlciBc
        dTIwMTQgcmVtb3ZlIGl0IG9yIHJvdXRlIHRocm91Z2ggYSBsb2dnZXIiXV0sICIucHkiOiBbWyJhbnktdHlwZSIs
        ICJcXGJBbnlcXGIiLCAiTmV2ZXIgdXNlIEFueSBcdTIwMTQgdXNlIHNwZWNpZmljIHR5cGVzLCBUeXBlZERpY3Qs
        IG9yIEJhc2VNb2RlbCJdLCBbInR5cGUtaWdub3JlIiwgIiNcXHMqdHlwZTpcXHMqaWdub3JlIiwgIk5ldmVyIHVz
        ZSAjIHR5cGU6IGlnbm9yZSBcdTIwMTQgZml4IHRoZSB0eXBlIGVycm9yIHByb3Blcmx5Il0sIFsicHlyaWdodC1p
        Z25vcmUiLCAiI1xccypweXJpZ2h0OlxccyppZ25vcmUiLCAiTmV2ZXIgdXNlICMgcHlyaWdodDogaWdub3JlIFx1
        MjAxNCBmaXggdGhlIHR5cGUgZXJyb3IgcHJvcGVybHkiXSwgWyJub3FhIiwgIiNcXHMqbm9xYVxcYiIsICJOZXZl
        ciB1c2UgIyBub3FhIFx1MjAxNCBmaXggdGhlIGxpbnQgaXNzdWUgcHJvcGVybHkiXSwgWyJnZW5lcmljLWJhc2Ui
        LCAiXFxiR2VuZXJpY1xcWyIsICJVc2UgUHl0aG9uIDMuMTIrIGNsYXNzW1RdIHN5bnRheCBpbnN0ZWFkIG9mIEdl
        bmVyaWNbVF0iXSwgWyJ0eXBpbmctdW5pb24iLCAiXFxiKD86T3B0aW9uYWx8VW5pb24pXFxbIiwgIlVzZSBQRVAg
        NjA0IHVuaW9ucyBcdTIwMTQgWCB8IE5vbmUgaW5zdGVhZCBvZiBPcHRpb25hbCwgWCB8IFkgaW5zdGVhZCBvZiBV
        bmlvbiJdLCBbInR5cGluZy1nZW5lcmljcyIsICJcXGIoPzpMaXN0fERpY3R8VHVwbGV8U2V0KVxcWyIsICJVc2Ug
        bG93ZXJjYXNlIGJ1aWx0aW4gZ2VuZXJpY3MgXHUyMDE0IGxpc3QsIGRpY3QsIHR1cGxlLCBzZXQgXHUyMDE0IGlu
        c3RlYWQgb2YgdGhlIGNhcGl0YWxpemVkIHR5cGluZyBhbGlhc2VzIl0sIFsiYWxsLWV4cG9ydCIsICJfX2FsbF9f
        XFxzKls9Ol0iLCAiTm8gX19hbGxfXyBcdTIwMTQgaW1wb3J0IGRpcmVjdGx5IGZyb20gdGhlIGRlZmluaW5nIG1v
        ZHVsZSJdLCBbImRpY3Qtc3RyLW9iamVjdCIsICJcXGIoPzpkaWN0fE1hcHBpbmcpXFxbXFxzKnN0clxccyosXFxz
        Km9iamVjdFxccypcXF0iLCAiTmV2ZXIgdXNlIGRpY3Rbc3RyLCBvYmplY3RdIG9yIE1hcHBpbmdbc3RyLCBvYmpl
        Y3RdIFx1MjAxNCB1c2UgVHlwZWREaWN0IG9yIEJhc2VNb2RlbCJdLCBbImRpY3Qtc3RyLXBheWxvYWQiLCAiXFxi
        KD86ZGljdHxNYXBwaW5nfE11dGFibGVNYXBwaW5nKVxcW1xccypzdHJcXHMqLFxccyooPzpzdHJ8aW50fGZsb2F0
        fGJvb2x8Ynl0ZXN8Y29tcGxleClcXGIiLCAiU3RyaW5nLWtleWVkIGRpY3Qgd2l0aCBhIHNjYWxhciB2YWx1ZSBo
        aWRlcyBzaGFwZSB3aGVuIHRoZSBrZXlzIGFyZSBhIENMT1NFRCwgZW51bWVyYWJsZSBzZXQgXHUyMDE0IHVzZSBh
        IEJhc2VNb2RlbCBvciBkaWN0W0xpdGVyYWxbLi4uXSwgVl0uIFdoZW4gdGhlIGtleXMgYXJlIG9wZW4gYW5kIGRh
        dGEtZHJpdmVuIChhIHJlZ2lzdHJ5L2NhY2hlL2NvdW50ZXIga2V5ZWQgYnkgZXh0ZXJuYWwgZGF0YSkgdGhpcyBp
        cyBsZWdpdGltYXRlOiBhZGQgYCMgbHVwOiBpZ25vcmVbZGljdC1zdHItcGF5bG9hZF1gLiBDb25jcmV0ZSBjbGFz
        cy9jYWxsYWJsZSB2YWx1ZSB0eXBlcyAoZGljdFtzdHIsIFNlc3Npb25GYWN0b3J5XSkgYXJlIGFscmVhZHkgYWNj
        ZXB0ZWQ7IEpzb25WYWx1ZSBjb3ZlcnMgYXJiaXRyYXJ5IEpTT04iXSwgWyJkaWN0LWdldCIsICJcXC5nZXRcXHMq
        XFwoIiwgImAuZ2V0KGAgb24gcGF5bG9hZC9UeXBlZERpY3Qtc2hhcGVkIGRhdGEgaGlkZXMgdGhlIHNjaGVtYSBc
        dTIwMTQgdXNlIHR5cGVkIGF0dHJpYnV0ZSBhY2Nlc3MgKEJhc2VNb2RlbC9UeXBlZERpY3QpLiBPbiBhIGdlbnVp
        bmVseSBvcGVuIGRpY3QgKHJlZ2lzdHJ5LCBjYWNoZSkgYWRkIGAjIGx1cDogaWdub3JlW2RpY3QtZ2V0XWAiXSwg
        WyJiYXJlLW9iamVjdCIsICIoPzooPzwhXFx3KSg/IV8pXFx3K1xccyo6fC0+KVxccypvYmplY3RcXGIiLCAiQmFy
        ZSBgb2JqZWN0YCBzYXlzIG5vdGhpbmcgYWJvdXQgdGhlIHZhbHVlIFx1MjAxNCB1c2UgYSBjb25jcmV0ZSB0eXBl
        LCBUeXBlZERpY3QsIG9yIEJhc2VNb2RlbCwgYW5kIG5hcnJvdyBhdCB1bnR5cGVkIGJvdW5kYXJpZXMiXSwgWyJi
        YXJlLWJhc2Vtb2RlbCIsICIoPzooPzwhXFxbKVxcYlxcdytcXHMqOnwtPilcXHMqQmFzZU1vZGVsXFxiKD8hXFxz
        KltcXF18XSkiLCAiQSBwYXJhbWV0ZXIgb3IgcmV0dXJuIGFubm90YXRlZCBleGFjdGx5IEJhc2VNb2RlbCBhY2Nl
        cHRzIGFueSBtb2RlbCBcdTIwMTQgbmFtZSB0aGUgY29uY3JldGUgdW5pb24gb2YgbW9kZWxzIG9yIG1ha2UgdGhl
        IGZ1bmN0aW9uIGdlbmVyaWMiXSwgWyJ0dXBsZS1zaGFwZSIsICJcXGJ0dXBsZVxcWyIsICJBIGRlY2xhcmVkIGB0
        dXBsZVsuLi5dYCBzaGFwZSBoaWRlcyB3aGF0IGVhY2ggcG9zaXRpb24gbWVhbnMgXHUyMDE0IG5hbWUgdGhlIGZp
        ZWxkcyB3aXRoIGEgVHlwZWREaWN0IG9yIEJhc2VNb2RlbCwgYSBgdHlwZSBBbGlhcyA9IC4uLmAgZm9yIGEgcmV1
        c2VkIHNoYXBlLCBvciBgbGlzdGAgZm9yIGEgdmFyaWFibGUtbGVuZ3RoIHNlcXVlbmNlIl0sIFsiZnJvemVuc2V0
        LXNoYXBlIiwgIlxcYmZyb3plbnNldFxcYiIsICJBIGRlY2xhcmVkIGBmcm96ZW5zZXRbLi4uXWAgc2hhcGUgb3Ig
        Y29uc3RhbnQgaXMgdXN1YWxseSBvdmVya2lsbCBcdTIwMTQgdXNlIGEgZGljdCBvciBhIHB1cnBvc2UtYnVpbHQg
        c3RydWN0dXJlLiBGb3IgYSBnZW51aW5lbHkgaW1tdXRhYmxlIGRlZmF1bHQgYXJndW1lbnQgYWRkIGAjIGx1cDog
        aWdub3JlW2Zyb3plbnNldC1zaGFwZV1gIl0sIFsic2V0LXNoYXBlIiwgIig/PCFcXC4pXFxic2V0W1xcWyhdfCg/
        Ojp8LT4pXFxzKnNldFxcYiIsICJBIGRlY2xhcmVkIGBzZXRgIGlzIHVzdWFsbHkgYmV0dGVyIGFzIGEgZGljdCAo
        a2V5ZWQgbG9va3VwKSBvciBhIHB1cnBvc2UtYnVpbHQgc3RydWN0dXJlLiBGb3IgYSBnZW51aW5lbHkgc2V0LXNo
        YXBlZCB2YWx1ZSBhZGQgYCMgbHVwOiBpZ25vcmVbc2V0LXNoYXBlXWAiXSwgWyJlbXB0eS1jb2xsZWN0aW9uIiwg
        Iig/PCFbPSE8Pl0pPVxccyooPzpcXHtcXH18XFxbXFxdfHNldFxcKFxcKSkiLCAiRW1wdHktY29sbGVjdGlvbiBs
        aXRlcmFscyAoYD0ge31gLCBgPSBbXWAsIGA9IHNldCgpYCkgdXN1YWxseSBzZWVkIGFuIGFwcGVuZC9tdXRhdGUg
        bG9vcCBcdTIwMTQgYnVpbGQgdGhlIGNvbGxlY3Rpb24gd2l0aCBhIGNvbXByZWhlbnNpb24gaW5zdGVhZCwgb3Ig
        YWRkIGAjIGx1cDogaWdub3JlW2VtcHR5LWNvbGxlY3Rpb25dYCBmb3IgYSBmb2xkIG5vIGNvbXByZWhlbnNpb24g
        Y2FuIGV4cHJlc3MiXSwgWyJjYXN0IiwgIlxcYmNhc3RcXHMqXFwoIiwgImBjYXN0KC4uLilgIGlzIGEgY29kZSBz
        bWVsbCBcdTIwMTQgbmFycm93IHdpdGggaXNpbnN0YW5jZSBvciBhIHR5cGUgZ3VhcmQsIG9yIGZpeCB0aGUgYW5u
        b3RhdGlvbiBzbyB0aGUgY2FzdCBpcyB1bm5lY2Vzc2FyeSJdLCBbImltcG9ydC1yZSIsICJcXGJpbXBvcnRcXHMr
        cmVcXGJ8XFxiZnJvbVxccytyZVxccytpbXBvcnRcXGIiLCAiYGltcG9ydCByZWAgLyBgZnJvbSByZSBpbXBvcnRg
        IGlzIGEgY29kZSBzbWVsbCBcdTIwMTQgcGFyc2Ugc3RydWN0dXJlZCBkYXRhIHdpdGggaXRzIG93biBBUEkgaW5z
        dGVhZDogSlNPTiAtPiBqc29uLmxvYWRzLCBwYXRocyAtPiBwYXRobGliLlBhdGgsIFVSTHMgLT4gdXJsbGliLnBh
        cnNlLCBYTUwvSFRNTCAtPiB4bWwuZXRyZWUuRWxlbWVudFRyZWUgLyBseG1sLCBkYXRlcyAtPiBkYXRldGltZSJd
        LCBbInJlLWNhbGwiLCAiXFxicmVcXC4oY29tcGlsZXxzZWFyY2h8bWF0Y2h8ZnVsbG1hdGNofHN1YnxmaW5kYWxs
        fHNwbGl0KVxccypcXCgiLCAiQXZvaWQgcmVnZXggZm9yIHN0cnVjdHVyZWQgZGF0YSBcdTIwMTQgcmVhY2ggZm9y
        IGl0cyBwYXJzZXIgaW5zdGVhZDogSlNPTiAtPiBqc29uLmxvYWRzLCBwYXRocyAtPiBwYXRobGliLlBhdGgsIFVS
        THMgLT4gdXJsbGliLnBhcnNlLCBYTUwvSFRNTCAtPiB4bWwuZXRyZWUuRWxlbWVudFRyZWUgLyBseG1sLCBkYXRl
        cyAtPiBkYXRldGltZSJdLCBbInN0cmluZy1yZXBsYWNlIiwgIig/PCFcXGJvcykoPzwhW1BwXWF0aClcXC5yZXBs
        YWNlXFxzKlxcKCIsICJBdm9pZCAucmVwbGFjZSgpIGZvciBzdHJ1Y3R1cmVkIGRhdGEgXHUyMDE0IGVkaXQgaXQg
        dGhyb3VnaCBpdHMgcGFyc2VyIGluc3RlYWQgKHBhdGhsaWIuUGF0aCBmb3IgcGF0aHMsIHVybGxpYi5wYXJzZSBm
        b3IgVVJMcywganNvbiBmb3IgSlNPTikiXSwgWyJzdHJpbmctc3BsaXQiLCAiXFwucj9zcGxpdFxccypcXCgoPyFc
        XHMqXFwpKXxcXC5yP3BhcnRpdGlvblxccypcXCgiLCAiQXZvaWQgLnNwbGl0KHNlcCkvLnJzcGxpdC8ucGFydGl0
        aW9uIGZvciBzdHJ1Y3R1cmVkIGRhdGEgXHUyMDE0IHBhcnNlIGl0IGluc3RlYWQgKHVybGxpYi5wYXJzZSBmb3Ig
        VVJMcywgcGF0aGxpYi5QYXRoIGZvciBwYXRocywganNvbiBmb3IgSlNPTiwgZGF0ZXRpbWUgZm9yIGRhdGVzKSJd
        LCBbInN0cmluZy1zdHJpcCIsICJcXC5bbHJdP3N0cmlwXFxzKlxcKCg/IVxccypcXCkpIiwgIkF2b2lkIC5zdHJp
        cChjaGFycykvLmxzdHJpcC8ucnN0cmlwIGZvciBzdHJ1Y3R1cmVkIGRhdGEgXHUyMDE0IHBhcnNlIGl0IGluc3Rl
        YWQgKHVybGxpYi5wYXJzZSBmb3IgVVJMcywgcGF0aGxpYi5QYXRoIGZvciBwYXRocywganNvbiBmb3IgSlNPTiwg
        ZGF0ZXRpbWUgZm9yIGRhdGVzKSJdLCBbImJhcmUtZXhjZXB0IiwgIlxcYmV4Y2VwdFxccyo6IiwgIkJhcmUgYGV4
        Y2VwdDpgIGNhdGNoZXMgU3lzdGVtRXhpdC9LZXlib2FyZEludGVycnVwdCBcdTIwMTQgbmFtZSB0aGUgZXhjZXB0
        aW9uIl0sIFsiZXhjZXB0LWJhc2VleGNlcHRpb24iLCAiXFxiZXhjZXB0XFxzK0Jhc2VFeGNlcHRpb25cXGIiLCAi
        ZXhjZXB0IEJhc2VFeGNlcHRpb24gY2F0Y2hlcyBLZXlib2FyZEludGVycnVwdCBcdTIwMTQgdXNlIEV4Y2VwdGlv
        biBvciBuYXJyb3dlciJdLCBbInN1cHByZXNzIiwgIlxcYmNvbnRleHRsaWJcXC5zdXBwcmVzc1xcYiIsICJjb250
        ZXh0bGliLnN1cHByZXNzIHNpbGVudGx5IHN3YWxsb3dzIGV4Y2VwdGlvbnMgXHUyMDE0IGxvZywgaGFuZGxlLCBv
        ciByZS1yYWlzZSJdLCBbInN1cHByZXNzLWltcG9ydCIsICJcXGJmcm9tXFxzK2NvbnRleHRsaWJcXHMraW1wb3J0
        XFxiLipcXGJzdXBwcmVzc1xcYiIsICJjb250ZXh0bGliLnN1cHByZXNzIHNpbGVudGx5IHN3YWxsb3dzIGV4Y2Vw
        dGlvbnMgXHUyMDE0IGxvZywgaGFuZGxlLCBvciByZS1yYWlzZSJdLCBbImRhdGFjbGFzcyIsICJAZGF0YWNsYXNz
        fFxcYmltcG9ydFxccytkYXRhY2xhc3Nlc1xcYnxcXGJmcm9tXFxzK2RhdGFjbGFzc2VzXFxzK2ltcG9ydFxcYiIs
        ICJVc2UgUHlkYW50aWMgQmFzZU1vZGVsIChvciBUeXBlZERpY3QpIGluc3RlYWQgb2YgZGF0YWNsYXNzZXMiXSwg
        WyJuYW1lZHR1cGxlIiwgIlxcYk5hbWVkVHVwbGVcXGJ8XFxibmFtZWR0dXBsZVxcYiIsICJVc2UgUHlkYW50aWMg
        QmFzZU1vZGVsIChvciBUeXBlZERpY3QpIGluc3RlYWQgb2YgTmFtZWRUdXBsZS9uYW1lZHR1cGxlIl0sIFsic3Vi
        cHJvY2VzcyIsICJcXGJpbXBvcnRcXHMrc3VicHJvY2Vzc1xcYnxcXGJmcm9tXFxzK3N1YnByb2Nlc3NcXHMraW1w
        b3J0XFxiIiwgIlVzZSB0aGUgYHNoYCBsaWJyYXJ5IGluc3RlYWQgb2Ygc3VicHJvY2VzcyJdLCBbIm9zLXNoZWxs
        IiwgIlxcYm9zXFwuKD86c3lzdGVtfHBvcGVufGV4ZWNbbHZdXFx3KilcXHMqXFwoIiwgIlVzZSB0aGUgYHNoYCBs
        aWJyYXJ5IGluc3RlYWQgb2Ygb3Muc3lzdGVtKCkvb3MucG9wZW4oKS9vcy5leGVjKigpIl0sIFsiYXJncGFyc2Ui
        LCAiXFxiaW1wb3J0XFxzK2FyZ3BhcnNlXFxifFxcYmZyb21cXHMrYXJncGFyc2VcXHMraW1wb3J0XFxiIiwgIlVz
        ZSBgdHlwZXJgIGluc3RlYWQgb2YgYXJncGFyc2UiXSwgWyJyaWNoLXByb2dyZXNzIiwgIlxcYnJpY2hcXC5wcm9n
        cmVzc1xcYnxcXGJmcm9tXFxzK3JpY2hcXC5wcm9ncmVzc1xccytpbXBvcnRcXGIiLCAiVXNlIGB0cWRtYCBpbnN0
        ZWFkIG9mIHJpY2ggcHJvZ3Jlc3MgYmFycyJdLCBbIm9zLXBhdGgiLCAiXFxib3NcXC5wYXRoXFxiIiwgIlVzZSBw
        YXRobGliLlBhdGggaW5zdGVhZCBvZiBvcy5wYXRoIl0sIFsib3MtZmlsZS1vcHMiLCAiXFxib3NcXC4oPzpnZXRj
        d2R8Y2hkaXJ8bGlzdGRpcnxzY2FuZGlyfHdhbGt8bWtkaXJ8bWFrZWRpcnN8cm1kaXJ8cmVtb3ZlZGlyc3xyZW1v
        dmV8dW5saW5rfHJlbmFtZXxyZW5hbWVzfHJlcGxhY2V8bGlua3xzeW1saW5rfHJlYWRsaW5rfHN0YXR8bHN0YXR8
        Y2htb2R8Y2hvd24pXFxzKlxcKCIsICJVc2UgcGF0aGxpYi5QYXRoIGZvciBmaWxlL2RpciBvcGVyYXRpb25zIGlu
        c3RlYWQgb2Ygb3MuKiAoUGF0aC5pdGVyZGlyL21rZGlyL3VubGluay9yZW5hbWUvcmVwbGFjZS9zdGF0Ly4uLiki
        XSwgWyJvcy1lbnZpcm9uIiwgIlxcYm9zXFwuKD86ZW52aXJvbnxnZXRlbnYpXFxiIiwgIlJlYWQgY29uZmlndXJh
        dGlvbiB0aHJvdWdoIHB5ZGFudGljLXNldHRpbmdzLCBub3Qgb3MuZW52aXJvbi9vcy5nZXRlbnYiXSwgWyJldmFs
        LWV4ZWMiLCAiKD88IVsuXFx3XSkoPzpldmFsfGV4ZWMpXFxzKlxcKCIsICJOZXZlciB1c2UgZXZhbCgpL2V4ZWMo
        KSBcdTIwMTQgcGFyc2UgdGhlIGRhdGEgKGFzdC5saXRlcmFsX2V2YWwgZm9yIGxpdGVyYWxzKSBvciBkaXNwYXRj
        aCBleHBsaWNpdGx5Il0sIFsidXRjbm93IiwgIlxcYnV0Y25vd1xccypcXCgiLCAiZGF0ZXRpbWUudXRjbm93KCkg
        aXMgbmFpdmUgYW5kIGRlcHJlY2F0ZWQgXHUyMDE0IHVzZSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKSJdLCBb
        Imdsb2JhbC1zdGF0ZW1lbnQiLCAiXmdsb2JhbFxccytcXHciLCAiTm8gYGdsb2JhbGAgc3RhdGVtZW50cyBcdTIw
        MTQgbXV0YXRlIGEgbW9kdWxlLWxldmVsIGhvbGRlciBvYmplY3Qgb3IgcGFzcyBzdGF0ZSBleHBsaWNpdGx5Il0s
        IFsicHJpdmF0ZS1mdW5jdGlvbiIsICJcXGJkZWZcXHMrX1thLXpBLVpdIiwgIk5vIGBfYCBwcmVmaXggb24gZnVu
        Y3Rpb25zL21ldGhvZHMgXHUyMDE0IG5vdGhpbmcgaXMgcHJpdmF0ZSAobmVzdCBpbnNpZGUgY2FsbGVyIGlmIG5l
        ZWRlZCkiXSwgWyJwcml2YXRlLWNsYXNzIiwgIlxcYmNsYXNzXFxzK19bQS1aXSIsICJObyBgX2AgcHJlZml4IG9u
        IGNsYXNzZXMgXHUyMDE0IG5vdGhpbmcgaXMgcHJpdmF0ZSJdLCBbInByaXZhdGUtdmFyaWFibGUiLCAiXl9bYS16
        QS1aXVxcdypcXHMqKD86OltePV0qKT89KD8hPSkoPyEuKixcXHMqJCkiLCAiTm8gYF9gIHByZWZpeCBvbiB2YXJp
        YWJsZXMvY29uc3RhbnRzIFx1MjAxNCBub3RoaW5nIGlzIHByaXZhdGUgKHVudXNlZCBgX2AgZnVuY3Rpb24gcGFy
        YW1ldGVycyBhcmUgZXhlbXB0KSJdXSwgIi5weWkiOiBbWyJhbnktdHlwZSIsICJcXGJBbnlcXGIiLCAiTmV2ZXIg
        dXNlIEFueSBcdTIwMTQgdXNlIHNwZWNpZmljIHR5cGVzLCBUeXBlZERpY3QsIG9yIEJhc2VNb2RlbCJdLCBbInR5
        cGUtaWdub3JlIiwgIiNcXHMqdHlwZTpcXHMqaWdub3JlIiwgIk5ldmVyIHVzZSAjIHR5cGU6IGlnbm9yZSBcdTIw
        MTQgZml4IHRoZSB0eXBlIGVycm9yIHByb3Blcmx5Il0sIFsicHlyaWdodC1pZ25vcmUiLCAiI1xccypweXJpZ2h0
        OlxccyppZ25vcmUiLCAiTmV2ZXIgdXNlICMgcHlyaWdodDogaWdub3JlIFx1MjAxNCBmaXggdGhlIHR5cGUgZXJy
        b3IgcHJvcGVybHkiXSwgWyJub3FhIiwgIiNcXHMqbm9xYVxcYiIsICJOZXZlciB1c2UgIyBub3FhIFx1MjAxNCBm
        aXggdGhlIGxpbnQgaXNzdWUgcHJvcGVybHkiXSwgWyJnZW5lcmljLWJhc2UiLCAiXFxiR2VuZXJpY1xcWyIsICJV
        c2UgUHl0aG9uIDMuMTIrIGNsYXNzW1RdIHN5bnRheCBpbnN0ZWFkIG9mIEdlbmVyaWNbVF0iXSwgWyJ0eXBpbmct
        dW5pb24iLCAiXFxiKD86T3B0aW9uYWx8VW5pb24pXFxbIiwgIlVzZSBQRVAgNjA0IHVuaW9ucyBcdTIwMTQgWCB8
        IE5vbmUgaW5zdGVhZCBvZiBPcHRpb25hbCwgWCB8IFkgaW5zdGVhZCBvZiBVbmlvbiJdLCBbInR5cGluZy1nZW5l
        cmljcyIsICJcXGIoPzpMaXN0fERpY3R8VHVwbGV8U2V0KVxcWyIsICJVc2UgbG93ZXJjYXNlIGJ1aWx0aW4gZ2Vu
        ZXJpY3MgXHUyMDE0IGxpc3QsIGRpY3QsIHR1cGxlLCBzZXQgXHUyMDE0IGluc3RlYWQgb2YgdGhlIGNhcGl0YWxp
        emVkIHR5cGluZyBhbGlhc2VzIl0sIFsiYWxsLWV4cG9ydCIsICJfX2FsbF9fXFxzKls9Ol0iLCAiTm8gX19hbGxf
        XyBcdTIwMTQgaW1wb3J0IGRpcmVjdGx5IGZyb20gdGhlIGRlZmluaW5nIG1vZHVsZSJdLCBbImRpY3Qtc3RyLW9i
        amVjdCIsICJcXGIoPzpkaWN0fE1hcHBpbmcpXFxbXFxzKnN0clxccyosXFxzKm9iamVjdFxccypcXF0iLCAiTmV2
        ZXIgdXNlIGRpY3Rbc3RyLCBvYmplY3RdIG9yIE1hcHBpbmdbc3RyLCBvYmplY3RdIFx1MjAxNCB1c2UgVHlwZWRE
        aWN0IG9yIEJhc2VNb2RlbCJdLCBbImRpY3Qtc3RyLXBheWxvYWQiLCAiXFxiKD86ZGljdHxNYXBwaW5nfE11dGFi
        bGVNYXBwaW5nKVxcW1xccypzdHJcXHMqLFxccyooPzpzdHJ8aW50fGZsb2F0fGJvb2x8Ynl0ZXN8Y29tcGxleClc
        XGIiLCAiU3RyaW5nLWtleWVkIGRpY3Qgd2l0aCBhIHNjYWxhciB2YWx1ZSBoaWRlcyBzaGFwZSB3aGVuIHRoZSBr
        ZXlzIGFyZSBhIENMT1NFRCwgZW51bWVyYWJsZSBzZXQgXHUyMDE0IHVzZSBhIEJhc2VNb2RlbCBvciBkaWN0W0xp
        dGVyYWxbLi4uXSwgVl0uIFdoZW4gdGhlIGtleXMgYXJlIG9wZW4gYW5kIGRhdGEtZHJpdmVuIChhIHJlZ2lzdHJ5
        L2NhY2hlL2NvdW50ZXIga2V5ZWQgYnkgZXh0ZXJuYWwgZGF0YSkgdGhpcyBpcyBsZWdpdGltYXRlOiBhZGQgYCMg
        bHVwOiBpZ25vcmVbZGljdC1zdHItcGF5bG9hZF1gLiBDb25jcmV0ZSBjbGFzcy9jYWxsYWJsZSB2YWx1ZSB0eXBl
        cyAoZGljdFtzdHIsIFNlc3Npb25GYWN0b3J5XSkgYXJlIGFscmVhZHkgYWNjZXB0ZWQ7IEpzb25WYWx1ZSBjb3Zl
        cnMgYXJiaXRyYXJ5IEpTT04iXSwgWyJkaWN0LWdldCIsICJcXC5nZXRcXHMqXFwoIiwgImAuZ2V0KGAgb24gcGF5
        bG9hZC9UeXBlZERpY3Qtc2hhcGVkIGRhdGEgaGlkZXMgdGhlIHNjaGVtYSBcdTIwMTQgdXNlIHR5cGVkIGF0dHJp
        YnV0ZSBhY2Nlc3MgKEJhc2VNb2RlbC9UeXBlZERpY3QpLiBPbiBhIGdlbnVpbmVseSBvcGVuIGRpY3QgKHJlZ2lz
        dHJ5LCBjYWNoZSkgYWRkIGAjIGx1cDogaWdub3JlW2RpY3QtZ2V0XWAiXSwgWyJiYXJlLW9iamVjdCIsICIoPzoo
        PzwhXFx3KSg/IV8pXFx3K1xccyo6fC0+KVxccypvYmplY3RcXGIiLCAiQmFyZSBgb2JqZWN0YCBzYXlzIG5vdGhp
        bmcgYWJvdXQgdGhlIHZhbHVlIFx1MjAxNCB1c2UgYSBjb25jcmV0ZSB0eXBlLCBUeXBlZERpY3QsIG9yIEJhc2VN
        b2RlbCwgYW5kIG5hcnJvdyBhdCB1bnR5cGVkIGJvdW5kYXJpZXMiXSwgWyJiYXJlLWJhc2Vtb2RlbCIsICIoPzoo
        PzwhXFxbKVxcYlxcdytcXHMqOnwtPilcXHMqQmFzZU1vZGVsXFxiKD8hXFxzKltcXF18XSkiLCAiQSBwYXJhbWV0
        ZXIgb3IgcmV0dXJuIGFubm90YXRlZCBleGFjdGx5IEJhc2VNb2RlbCBhY2NlcHRzIGFueSBtb2RlbCBcdTIwMTQg
        bmFtZSB0aGUgY29uY3JldGUgdW5pb24gb2YgbW9kZWxzIG9yIG1ha2UgdGhlIGZ1bmN0aW9uIGdlbmVyaWMiXSwg
        WyJ0dXBsZS1zaGFwZSIsICJcXGJ0dXBsZVxcWyIsICJBIGRlY2xhcmVkIGB0dXBsZVsuLi5dYCBzaGFwZSBoaWRl
        cyB3aGF0IGVhY2ggcG9zaXRpb24gbWVhbnMgXHUyMDE0IG5hbWUgdGhlIGZpZWxkcyB3aXRoIGEgVHlwZWREaWN0
        IG9yIEJhc2VNb2RlbCwgYSBgdHlwZSBBbGlhcyA9IC4uLmAgZm9yIGEgcmV1c2VkIHNoYXBlLCBvciBgbGlzdGAg
        Zm9yIGEgdmFyaWFibGUtbGVuZ3RoIHNlcXVlbmNlIl0sIFsiZnJvemVuc2V0LXNoYXBlIiwgIlxcYmZyb3plbnNl
        dFxcYiIsICJBIGRlY2xhcmVkIGBmcm96ZW5zZXRbLi4uXWAgc2hhcGUgb3IgY29uc3RhbnQgaXMgdXN1YWxseSBv
        dmVya2lsbCBcdTIwMTQgdXNlIGEgZGljdCBvciBhIHB1cnBvc2UtYnVpbHQgc3RydWN0dXJlLiBGb3IgYSBnZW51
        aW5lbHkgaW1tdXRhYmxlIGRlZmF1bHQgYXJndW1lbnQgYWRkIGAjIGx1cDogaWdub3JlW2Zyb3plbnNldC1zaGFw
        ZV1gIl0sIFsic2V0LXNoYXBlIiwgIig/PCFcXC4pXFxic2V0W1xcWyhdfCg/Ojp8LT4pXFxzKnNldFxcYiIsICJB
        IGRlY2xhcmVkIGBzZXRgIGlzIHVzdWFsbHkgYmV0dGVyIGFzIGEgZGljdCAoa2V5ZWQgbG9va3VwKSBvciBhIHB1
        cnBvc2UtYnVpbHQgc3RydWN0dXJlLiBGb3IgYSBnZW51aW5lbHkgc2V0LXNoYXBlZCB2YWx1ZSBhZGQgYCMgbHVw
        OiBpZ25vcmVbc2V0LXNoYXBlXWAiXSwgWyJlbXB0eS1jb2xsZWN0aW9uIiwgIig/PCFbPSE8Pl0pPVxccyooPzpc
        XHtcXH18XFxbXFxdfHNldFxcKFxcKSkiLCAiRW1wdHktY29sbGVjdGlvbiBsaXRlcmFscyAoYD0ge31gLCBgPSBb
        XWAsIGA9IHNldCgpYCkgdXN1YWxseSBzZWVkIGFuIGFwcGVuZC9tdXRhdGUgbG9vcCBcdTIwMTQgYnVpbGQgdGhl
        IGNvbGxlY3Rpb24gd2l0aCBhIGNvbXByZWhlbnNpb24gaW5zdGVhZCwgb3IgYWRkIGAjIGx1cDogaWdub3JlW2Vt
        cHR5LWNvbGxlY3Rpb25dYCBmb3IgYSBmb2xkIG5vIGNvbXByZWhlbnNpb24gY2FuIGV4cHJlc3MiXSwgWyJjYXN0
        IiwgIlxcYmNhc3RcXHMqXFwoIiwgImBjYXN0KC4uLilgIGlzIGEgY29kZSBzbWVsbCBcdTIwMTQgbmFycm93IHdp
        dGggaXNpbnN0YW5jZSBvciBhIHR5cGUgZ3VhcmQsIG9yIGZpeCB0aGUgYW5ub3RhdGlvbiBzbyB0aGUgY2FzdCBp
        cyB1bm5lY2Vzc2FyeSJdLCBbImltcG9ydC1yZSIsICJcXGJpbXBvcnRcXHMrcmVcXGJ8XFxiZnJvbVxccytyZVxc
        cytpbXBvcnRcXGIiLCAiYGltcG9ydCByZWAgLyBgZnJvbSByZSBpbXBvcnRgIGlzIGEgY29kZSBzbWVsbCBcdTIw
        MTQgcGFyc2Ugc3RydWN0dXJlZCBkYXRhIHdpdGggaXRzIG93biBBUEkgaW5zdGVhZDogSlNPTiAtPiBqc29uLmxv
        YWRzLCBwYXRocyAtPiBwYXRobGliLlBhdGgsIFVSTHMgLT4gdXJsbGliLnBhcnNlLCBYTUwvSFRNTCAtPiB4bWwu
        ZXRyZWUuRWxlbWVudFRyZWUgLyBseG1sLCBkYXRlcyAtPiBkYXRldGltZSJdLCBbInJlLWNhbGwiLCAiXFxicmVc
        XC4oY29tcGlsZXxzZWFyY2h8bWF0Y2h8ZnVsbG1hdGNofHN1YnxmaW5kYWxsfHNwbGl0KVxccypcXCgiLCAiQXZv
        aWQgcmVnZXggZm9yIHN0cnVjdHVyZWQgZGF0YSBcdTIwMTQgcmVhY2ggZm9yIGl0cyBwYXJzZXIgaW5zdGVhZDog
        SlNPTiAtPiBqc29uLmxvYWRzLCBwYXRocyAtPiBwYXRobGliLlBhdGgsIFVSTHMgLT4gdXJsbGliLnBhcnNlLCBY
        TUwvSFRNTCAtPiB4bWwuZXRyZWUuRWxlbWVudFRyZWUgLyBseG1sLCBkYXRlcyAtPiBkYXRldGltZSJdLCBbInN0
        cmluZy1yZXBsYWNlIiwgIig/PCFcXGJvcykoPzwhW1BwXWF0aClcXC5yZXBsYWNlXFxzKlxcKCIsICJBdm9pZCAu
        cmVwbGFjZSgpIGZvciBzdHJ1Y3R1cmVkIGRhdGEgXHUyMDE0IGVkaXQgaXQgdGhyb3VnaCBpdHMgcGFyc2VyIGlu
        c3RlYWQgKHBhdGhsaWIuUGF0aCBmb3IgcGF0aHMsIHVybGxpYi5wYXJzZSBmb3IgVVJMcywganNvbiBmb3IgSlNP
        TikiXSwgWyJzdHJpbmctc3BsaXQiLCAiXFwucj9zcGxpdFxccypcXCgoPyFcXHMqXFwpKXxcXC5yP3BhcnRpdGlv
        blxccypcXCgiLCAiQXZvaWQgLnNwbGl0KHNlcCkvLnJzcGxpdC8ucGFydGl0aW9uIGZvciBzdHJ1Y3R1cmVkIGRh
        dGEgXHUyMDE0IHBhcnNlIGl0IGluc3RlYWQgKHVybGxpYi5wYXJzZSBmb3IgVVJMcywgcGF0aGxpYi5QYXRoIGZv
        ciBwYXRocywganNvbiBmb3IgSlNPTiwgZGF0ZXRpbWUgZm9yIGRhdGVzKSJdLCBbInN0cmluZy1zdHJpcCIsICJc
        XC5bbHJdP3N0cmlwXFxzKlxcKCg/IVxccypcXCkpIiwgIkF2b2lkIC5zdHJpcChjaGFycykvLmxzdHJpcC8ucnN0
        cmlwIGZvciBzdHJ1Y3R1cmVkIGRhdGEgXHUyMDE0IHBhcnNlIGl0IGluc3RlYWQgKHVybGxpYi5wYXJzZSBmb3Ig
        VVJMcywgcGF0aGxpYi5QYXRoIGZvciBwYXRocywganNvbiBmb3IgSlNPTiwgZGF0ZXRpbWUgZm9yIGRhdGVzKSJd
        LCBbImJhcmUtZXhjZXB0IiwgIlxcYmV4Y2VwdFxccyo6IiwgIkJhcmUgYGV4Y2VwdDpgIGNhdGNoZXMgU3lzdGVt
        RXhpdC9LZXlib2FyZEludGVycnVwdCBcdTIwMTQgbmFtZSB0aGUgZXhjZXB0aW9uIl0sIFsiZXhjZXB0LWJhc2Vl
        eGNlcHRpb24iLCAiXFxiZXhjZXB0XFxzK0Jhc2VFeGNlcHRpb25cXGIiLCAiZXhjZXB0IEJhc2VFeGNlcHRpb24g
        Y2F0Y2hlcyBLZXlib2FyZEludGVycnVwdCBcdTIwMTQgdXNlIEV4Y2VwdGlvbiBvciBuYXJyb3dlciJdLCBbInN1
        cHByZXNzIiwgIlxcYmNvbnRleHRsaWJcXC5zdXBwcmVzc1xcYiIsICJjb250ZXh0bGliLnN1cHByZXNzIHNpbGVu
        dGx5IHN3YWxsb3dzIGV4Y2VwdGlvbnMgXHUyMDE0IGxvZywgaGFuZGxlLCBvciByZS1yYWlzZSJdLCBbInN1cHBy
        ZXNzLWltcG9ydCIsICJcXGJmcm9tXFxzK2NvbnRleHRsaWJcXHMraW1wb3J0XFxiLipcXGJzdXBwcmVzc1xcYiIs
        ICJjb250ZXh0bGliLnN1cHByZXNzIHNpbGVudGx5IHN3YWxsb3dzIGV4Y2VwdGlvbnMgXHUyMDE0IGxvZywgaGFu
        ZGxlLCBvciByZS1yYWlzZSJdLCBbImRhdGFjbGFzcyIsICJAZGF0YWNsYXNzfFxcYmltcG9ydFxccytkYXRhY2xh
        c3Nlc1xcYnxcXGJmcm9tXFxzK2RhdGFjbGFzc2VzXFxzK2ltcG9ydFxcYiIsICJVc2UgUHlkYW50aWMgQmFzZU1v
        ZGVsIChvciBUeXBlZERpY3QpIGluc3RlYWQgb2YgZGF0YWNsYXNzZXMiXSwgWyJuYW1lZHR1cGxlIiwgIlxcYk5h
        bWVkVHVwbGVcXGJ8XFxibmFtZWR0dXBsZVxcYiIsICJVc2UgUHlkYW50aWMgQmFzZU1vZGVsIChvciBUeXBlZERp
        Y3QpIGluc3RlYWQgb2YgTmFtZWRUdXBsZS9uYW1lZHR1cGxlIl0sIFsic3VicHJvY2VzcyIsICJcXGJpbXBvcnRc
        XHMrc3VicHJvY2Vzc1xcYnxcXGJmcm9tXFxzK3N1YnByb2Nlc3NcXHMraW1wb3J0XFxiIiwgIlVzZSB0aGUgYHNo
        YCBsaWJyYXJ5IGluc3RlYWQgb2Ygc3VicHJvY2VzcyJdLCBbIm9zLXNoZWxsIiwgIlxcYm9zXFwuKD86c3lzdGVt
        fHBvcGVufGV4ZWNbbHZdXFx3KilcXHMqXFwoIiwgIlVzZSB0aGUgYHNoYCBsaWJyYXJ5IGluc3RlYWQgb2Ygb3Mu
        c3lzdGVtKCkvb3MucG9wZW4oKS9vcy5leGVjKigpIl0sIFsiYXJncGFyc2UiLCAiXFxiaW1wb3J0XFxzK2FyZ3Bh
        cnNlXFxifFxcYmZyb21cXHMrYXJncGFyc2VcXHMraW1wb3J0XFxiIiwgIlVzZSBgdHlwZXJgIGluc3RlYWQgb2Yg
        YXJncGFyc2UiXSwgWyJyaWNoLXByb2dyZXNzIiwgIlxcYnJpY2hcXC5wcm9ncmVzc1xcYnxcXGJmcm9tXFxzK3Jp
        Y2hcXC5wcm9ncmVzc1xccytpbXBvcnRcXGIiLCAiVXNlIGB0cWRtYCBpbnN0ZWFkIG9mIHJpY2ggcHJvZ3Jlc3Mg
        YmFycyJdLCBbIm9zLXBhdGgiLCAiXFxib3NcXC5wYXRoXFxiIiwgIlVzZSBwYXRobGliLlBhdGggaW5zdGVhZCBv
        ZiBvcy5wYXRoIl0sIFsib3MtZmlsZS1vcHMiLCAiXFxib3NcXC4oPzpnZXRjd2R8Y2hkaXJ8bGlzdGRpcnxzY2Fu
        ZGlyfHdhbGt8bWtkaXJ8bWFrZWRpcnN8cm1kaXJ8cmVtb3ZlZGlyc3xyZW1vdmV8dW5saW5rfHJlbmFtZXxyZW5h
        bWVzfHJlcGxhY2V8bGlua3xzeW1saW5rfHJlYWRsaW5rfHN0YXR8bHN0YXR8Y2htb2R8Y2hvd24pXFxzKlxcKCIs
        ICJVc2UgcGF0aGxpYi5QYXRoIGZvciBmaWxlL2RpciBvcGVyYXRpb25zIGluc3RlYWQgb2Ygb3MuKiAoUGF0aC5p
        dGVyZGlyL21rZGlyL3VubGluay9yZW5hbWUvcmVwbGFjZS9zdGF0Ly4uLikiXSwgWyJvcy1lbnZpcm9uIiwgIlxc
        Ym9zXFwuKD86ZW52aXJvbnxnZXRlbnYpXFxiIiwgIlJlYWQgY29uZmlndXJhdGlvbiB0aHJvdWdoIHB5ZGFudGlj
        LXNldHRpbmdzLCBub3Qgb3MuZW52aXJvbi9vcy5nZXRlbnYiXSwgWyJldmFsLWV4ZWMiLCAiKD88IVsuXFx3XSko
        PzpldmFsfGV4ZWMpXFxzKlxcKCIsICJOZXZlciB1c2UgZXZhbCgpL2V4ZWMoKSBcdTIwMTQgcGFyc2UgdGhlIGRh
        dGEgKGFzdC5saXRlcmFsX2V2YWwgZm9yIGxpdGVyYWxzKSBvciBkaXNwYXRjaCBleHBsaWNpdGx5Il0sIFsidXRj
        bm93IiwgIlxcYnV0Y25vd1xccypcXCgiLCAiZGF0ZXRpbWUudXRjbm93KCkgaXMgbmFpdmUgYW5kIGRlcHJlY2F0
        ZWQgXHUyMDE0IHVzZSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKSJdLCBbImdsb2JhbC1zdGF0ZW1lbnQiLCAi
        Xmdsb2JhbFxccytcXHciLCAiTm8gYGdsb2JhbGAgc3RhdGVtZW50cyBcdTIwMTQgbXV0YXRlIGEgbW9kdWxlLWxl
        dmVsIGhvbGRlciBvYmplY3Qgb3IgcGFzcyBzdGF0ZSBleHBsaWNpdGx5Il0sIFsicHJpdmF0ZS1mdW5jdGlvbiIs
        ICJcXGJkZWZcXHMrX1thLXpBLVpdIiwgIk5vIGBfYCBwcmVmaXggb24gZnVuY3Rpb25zL21ldGhvZHMgXHUyMDE0
        IG5vdGhpbmcgaXMgcHJpdmF0ZSAobmVzdCBpbnNpZGUgY2FsbGVyIGlmIG5lZWRlZCkiXSwgWyJwcml2YXRlLWNs
        YXNzIiwgIlxcYmNsYXNzXFxzK19bQS1aXSIsICJObyBgX2AgcHJlZml4IG9uIGNsYXNzZXMgXHUyMDE0IG5vdGhp
        bmcgaXMgcHJpdmF0ZSJdLCBbInByaXZhdGUtdmFyaWFibGUiLCAiXl9bYS16QS1aXVxcdypcXHMqKD86OltePV0q
        KT89KD8hPSkoPyEuKixcXHMqJCkiLCAiTm8gYF9gIHByZWZpeCBvbiB2YXJpYWJsZXMvY29uc3RhbnRzIFx1MjAx
        NCBub3RoaW5nIGlzIHByaXZhdGUgKHVudXNlZCBgX2AgZnVuY3Rpb24gcGFyYW1ldGVycyBhcmUgZXhlbXB0KSJd
        XSwgIi5zdmVsdGUiOiBbWyJhcy1hbnkiLCAiXFxiYXNcXHMrYW55XFxiIiwgIk5ldmVyIHVzZSBgYXMgYW55YCBc
        dTIwMTQgdXNlIHByb3BlciB0eXBlcyBvciB0eXBlIGd1YXJkcyJdLCBbImFzLXVua25vd24iLCAiXFxiYXNcXHMr
        dW5rbm93blxcYiIsICJOZXZlciB1c2UgYGFzIHVua25vd25gIFx1MjAxNCB1c2UgdHlwZSBndWFyZHMgb3IgcHJv
        cGVyIHR5cGVzIl0sIFsiYW55LWFubm90YXRpb24iLCAiOlxccyphbnlcXGIiLCAiTmV2ZXIgdXNlIGBhbnlgIHR5
        cGUgYW5ub3RhdGlvbiBcdTIwMTQgdXNlIHNwZWNpZmljIHR5cGVzLCBnZW5lcmljcywgb3IgYHVua25vd25gIl0s
        IFsiYW55LWFzc2VydGlvbiIsICI8YW55PiIsICJOZXZlciB1c2UgYDxhbnk+YCB0eXBlIGFzc2VydGlvbiBcdTIw
        MTQgdXNlIHByb3BlciB0eXBlcyJdLCBbInRzLWlnbm9yZSIsICJAdHMtaWdub3JlIiwgIk5ldmVyIHVzZSBAdHMt
        aWdub3JlIFx1MjAxNCBmaXggdGhlIHR5cGUgZXJyb3IgcHJvcGVybHkiXSwgWyJ0cy1leHBlY3QtZXJyb3IiLCAi
        QHRzLWV4cGVjdC1lcnJvciIsICJOZXZlciB1c2UgQHRzLWV4cGVjdC1lcnJvciBcdTIwMTQgZml4IHRoZSB0eXBl
        IGVycm9yIHByb3Blcmx5Il0sIFsidHMtbm9jaGVjayIsICJAdHMtbm9jaGVjayIsICJOZXZlciB1c2UgQHRzLW5v
        Y2hlY2sgXHUyMDE0IGZpeCB0aGUgdHlwZSBlcnJvcnMgaW4gdGhlIGZpbGUiXSwgWyJlc2xpbnQtZGlzYWJsZSIs
        ICIvL1xccyplc2xpbnQtZGlzYWJsZSIsICJOZXZlciB1c2UgZXNsaW50LWRpc2FibGUgXHUyMDE0IGZpeCB0aGUg
        bGludCBpc3N1ZSBwcm9wZXJseSJdLCBbImVzbGludC1kaXNhYmxlLWJsb2NrIiwgIi9cXCpcXHMqZXNsaW50LWRp
        c2FibGUiLCAiTmV2ZXIgdXNlIGVzbGludC1kaXNhYmxlIFx1MjAxNCBmaXggdGhlIGxpbnQgaXNzdWUgcHJvcGVy
        bHkiXSwgWyJ0c2xpbnQtZGlzYWJsZSIsICIvL1xccyp0c2xpbnQ6ZGlzYWJsZSIsICJOZXZlciB1c2UgdHNsaW50
        OmRpc2FibGUgXHUyMDE0IG1pZ3JhdGUgdG8gZXNsaW50IGFuZCBmaXggdGhlIGlzc3VlIl0sIFsibm9uLW51bGwt
        YXNzZXJ0aW9uIiwgIltcXHdcXClcXF1dIVxcLiIsICJQb3N0Zml4IGAhLmAgbm9uLW51bGwgYXNzZXJ0aW9uIGhp
        ZGVzIGEgcG9zc2libGUgbnVsbC91bmRlZmluZWQgXHUyMDE0IG5hcnJvdyB0aGUgdHlwZSBvciBoYW5kbGUgdGhl
        IG1pc3NpbmcgY2FzZSJdLCBbInZhci1kZWNsYXJhdGlvbiIsICJcXGJ2YXJcXHMrW0EtWmEtel8kXSIsICJVc2Ug
        YGNvbnN0YCBvciBgbGV0YCBpbnN0ZWFkIG9mIGB2YXJgIFx1MjAxNCB2YXIgaXMgZnVuY3Rpb24tc2NvcGVkIGFu
        ZCBob2lzdGVkIl0sIFsiZnVuY3Rpb24tb2JqZWN0LXR5cGUiLCAiOlxccyooPzpGdW5jdGlvbnxPYmplY3QpXFxi
        IiwgIk5ldmVyIHVzZSBgRnVuY3Rpb25gIG9yIGBPYmplY3RgIGFzIGEgdHlwZSBcdTIwMTQgZGVjbGFyZSB0aGUg
        Y2FsbCBzaWduYXR1cmUgb3IgdGhlIG9iamVjdCBzaGFwZSJdLCBbImNvbnNvbGUtbG9nIiwgIlxcYmNvbnNvbGVc
        XC5sb2dcXHMqXFwoIiwgImNvbnNvbGUubG9nIGlzIGEgZGVidWcgbGVmdG92ZXIgXHUyMDE0IHJlbW92ZSBpdCBv
        ciByb3V0ZSB0aHJvdWdoIGEgbG9nZ2VyIl1dLCAiLnRzIjogW1siYXMtYW55IiwgIlxcYmFzXFxzK2FueVxcYiIs
        ICJOZXZlciB1c2UgYGFzIGFueWAgXHUyMDE0IHVzZSBwcm9wZXIgdHlwZXMgb3IgdHlwZSBndWFyZHMiXSwgWyJh
        cy11bmtub3duIiwgIlxcYmFzXFxzK3Vua25vd25cXGIiLCAiTmV2ZXIgdXNlIGBhcyB1bmtub3duYCBcdTIwMTQg
        dXNlIHR5cGUgZ3VhcmRzIG9yIHByb3BlciB0eXBlcyJdLCBbImFueS1hbm5vdGF0aW9uIiwgIjpcXHMqYW55XFxi
        IiwgIk5ldmVyIHVzZSBgYW55YCB0eXBlIGFubm90YXRpb24gXHUyMDE0IHVzZSBzcGVjaWZpYyB0eXBlcywgZ2Vu
        ZXJpY3MsIG9yIGB1bmtub3duYCJdLCBbImFueS1hc3NlcnRpb24iLCAiPGFueT4iLCAiTmV2ZXIgdXNlIGA8YW55
        PmAgdHlwZSBhc3NlcnRpb24gXHUyMDE0IHVzZSBwcm9wZXIgdHlwZXMiXSwgWyJ0cy1pZ25vcmUiLCAiQHRzLWln
        bm9yZSIsICJOZXZlciB1c2UgQHRzLWlnbm9yZSBcdTIwMTQgZml4IHRoZSB0eXBlIGVycm9yIHByb3Blcmx5Il0s
        IFsidHMtZXhwZWN0LWVycm9yIiwgIkB0cy1leHBlY3QtZXJyb3IiLCAiTmV2ZXIgdXNlIEB0cy1leHBlY3QtZXJy
        b3IgXHUyMDE0IGZpeCB0aGUgdHlwZSBlcnJvciBwcm9wZXJseSJdLCBbInRzLW5vY2hlY2siLCAiQHRzLW5vY2hl
        Y2siLCAiTmV2ZXIgdXNlIEB0cy1ub2NoZWNrIFx1MjAxNCBmaXggdGhlIHR5cGUgZXJyb3JzIGluIHRoZSBmaWxl
        Il0sIFsiZXNsaW50LWRpc2FibGUiLCAiLy9cXHMqZXNsaW50LWRpc2FibGUiLCAiTmV2ZXIgdXNlIGVzbGludC1k
        aXNhYmxlIFx1MjAxNCBmaXggdGhlIGxpbnQgaXNzdWUgcHJvcGVybHkiXSwgWyJlc2xpbnQtZGlzYWJsZS1ibG9j
        ayIsICIvXFwqXFxzKmVzbGludC1kaXNhYmxlIiwgIk5ldmVyIHVzZSBlc2xpbnQtZGlzYWJsZSBcdTIwMTQgZml4
        IHRoZSBsaW50IGlzc3VlIHByb3Blcmx5Il0sIFsidHNsaW50LWRpc2FibGUiLCAiLy9cXHMqdHNsaW50OmRpc2Fi
        bGUiLCAiTmV2ZXIgdXNlIHRzbGludDpkaXNhYmxlIFx1MjAxNCBtaWdyYXRlIHRvIGVzbGludCBhbmQgZml4IHRo
        ZSBpc3N1ZSJdLCBbIm5vbi1udWxsLWFzc2VydGlvbiIsICJbXFx3XFwpXFxdXSFcXC4iLCAiUG9zdGZpeCBgIS5g
        IG5vbi1udWxsIGFzc2VydGlvbiBoaWRlcyBhIHBvc3NpYmxlIG51bGwvdW5kZWZpbmVkIFx1MjAxNCBuYXJyb3cg
        dGhlIHR5cGUgb3IgaGFuZGxlIHRoZSBtaXNzaW5nIGNhc2UiXSwgWyJ2YXItZGVjbGFyYXRpb24iLCAiXFxidmFy
        XFxzK1tBLVphLXpfJF0iLCAiVXNlIGBjb25zdGAgb3IgYGxldGAgaW5zdGVhZCBvZiBgdmFyYCBcdTIwMTQgdmFy
        IGlzIGZ1bmN0aW9uLXNjb3BlZCBhbmQgaG9pc3RlZCJdLCBbImZ1bmN0aW9uLW9iamVjdC10eXBlIiwgIjpcXHMq
        KD86RnVuY3Rpb258T2JqZWN0KVxcYiIsICJOZXZlciB1c2UgYEZ1bmN0aW9uYCBvciBgT2JqZWN0YCBhcyBhIHR5
        cGUgXHUyMDE0IGRlY2xhcmUgdGhlIGNhbGwgc2lnbmF0dXJlIG9yIHRoZSBvYmplY3Qgc2hhcGUiXSwgWyJjb25z
        b2xlLWxvZyIsICJcXGJjb25zb2xlXFwubG9nXFxzKlxcKCIsICJjb25zb2xlLmxvZyBpcyBhIGRlYnVnIGxlZnRv
        dmVyIFx1MjAxNCByZW1vdmUgaXQgb3Igcm91dGUgdGhyb3VnaCBhIGxvZ2dlciJdXSwgIi50c3giOiBbWyJhcy1h
        bnkiLCAiXFxiYXNcXHMrYW55XFxiIiwgIk5ldmVyIHVzZSBgYXMgYW55YCBcdTIwMTQgdXNlIHByb3BlciB0eXBl
        cyBvciB0eXBlIGd1YXJkcyJdLCBbImFzLXVua25vd24iLCAiXFxiYXNcXHMrdW5rbm93blxcYiIsICJOZXZlciB1
        c2UgYGFzIHVua25vd25gIFx1MjAxNCB1c2UgdHlwZSBndWFyZHMgb3IgcHJvcGVyIHR5cGVzIl0sIFsiYW55LWFu
        bm90YXRpb24iLCAiOlxccyphbnlcXGIiLCAiTmV2ZXIgdXNlIGBhbnlgIHR5cGUgYW5ub3RhdGlvbiBcdTIwMTQg
        dXNlIHNwZWNpZmljIHR5cGVzLCBnZW5lcmljcywgb3IgYHVua25vd25gIl0sIFsiYW55LWFzc2VydGlvbiIsICI8
        YW55PiIsICJOZXZlciB1c2UgYDxhbnk+YCB0eXBlIGFzc2VydGlvbiBcdTIwMTQgdXNlIHByb3BlciB0eXBlcyJd
        LCBbInRzLWlnbm9yZSIsICJAdHMtaWdub3JlIiwgIk5ldmVyIHVzZSBAdHMtaWdub3JlIFx1MjAxNCBmaXggdGhl
        IHR5cGUgZXJyb3IgcHJvcGVybHkiXSwgWyJ0cy1leHBlY3QtZXJyb3IiLCAiQHRzLWV4cGVjdC1lcnJvciIsICJO
        ZXZlciB1c2UgQHRzLWV4cGVjdC1lcnJvciBcdTIwMTQgZml4IHRoZSB0eXBlIGVycm9yIHByb3Blcmx5Il0sIFsi
        dHMtbm9jaGVjayIsICJAdHMtbm9jaGVjayIsICJOZXZlciB1c2UgQHRzLW5vY2hlY2sgXHUyMDE0IGZpeCB0aGUg
        dHlwZSBlcnJvcnMgaW4gdGhlIGZpbGUiXSwgWyJlc2xpbnQtZGlzYWJsZSIsICIvL1xccyplc2xpbnQtZGlzYWJs
        ZSIsICJOZXZlciB1c2UgZXNsaW50LWRpc2FibGUgXHUyMDE0IGZpeCB0aGUgbGludCBpc3N1ZSBwcm9wZXJseSJd
        LCBbImVzbGludC1kaXNhYmxlLWJsb2NrIiwgIi9cXCpcXHMqZXNsaW50LWRpc2FibGUiLCAiTmV2ZXIgdXNlIGVz
        bGludC1kaXNhYmxlIFx1MjAxNCBmaXggdGhlIGxpbnQgaXNzdWUgcHJvcGVybHkiXSwgWyJ0c2xpbnQtZGlzYWJs
        ZSIsICIvL1xccyp0c2xpbnQ6ZGlzYWJsZSIsICJOZXZlciB1c2UgdHNsaW50OmRpc2FibGUgXHUyMDE0IG1pZ3Jh
        dGUgdG8gZXNsaW50IGFuZCBmaXggdGhlIGlzc3VlIl0sIFsibm9uLW51bGwtYXNzZXJ0aW9uIiwgIltcXHdcXClc
        XF1dIVxcLiIsICJQb3N0Zml4IGAhLmAgbm9uLW51bGwgYXNzZXJ0aW9uIGhpZGVzIGEgcG9zc2libGUgbnVsbC91
        bmRlZmluZWQgXHUyMDE0IG5hcnJvdyB0aGUgdHlwZSBvciBoYW5kbGUgdGhlIG1pc3NpbmcgY2FzZSJdLCBbInZh
        ci1kZWNsYXJhdGlvbiIsICJcXGJ2YXJcXHMrW0EtWmEtel8kXSIsICJVc2UgYGNvbnN0YCBvciBgbGV0YCBpbnN0
        ZWFkIG9mIGB2YXJgIFx1MjAxNCB2YXIgaXMgZnVuY3Rpb24tc2NvcGVkIGFuZCBob2lzdGVkIl0sIFsiZnVuY3Rp
        b24tb2JqZWN0LXR5cGUiLCAiOlxccyooPzpGdW5jdGlvbnxPYmplY3QpXFxiIiwgIk5ldmVyIHVzZSBgRnVuY3Rp
        b25gIG9yIGBPYmplY3RgIGFzIGEgdHlwZSBcdTIwMTQgZGVjbGFyZSB0aGUgY2FsbCBzaWduYXR1cmUgb3IgdGhl
        IG9iamVjdCBzaGFwZSJdLCBbImNvbnNvbGUtbG9nIiwgIlxcYmNvbnNvbGVcXC5sb2dcXHMqXFwoIiwgImNvbnNv
        bGUubG9nIGlzIGEgZGVidWcgbGVmdG92ZXIgXHUyMDE0IHJlbW92ZSBpdCBvciByb3V0ZSB0aHJvdWdoIGEgbG9n
        Z2VyIl1dLCAiLnZ1ZSI6IFtbImFzLWFueSIsICJcXGJhc1xccythbnlcXGIiLCAiTmV2ZXIgdXNlIGBhcyBhbnlg
        IFx1MjAxNCB1c2UgcHJvcGVyIHR5cGVzIG9yIHR5cGUgZ3VhcmRzIl0sIFsiYXMtdW5rbm93biIsICJcXGJhc1xc
        cyt1bmtub3duXFxiIiwgIk5ldmVyIHVzZSBgYXMgdW5rbm93bmAgXHUyMDE0IHVzZSB0eXBlIGd1YXJkcyBvciBw
        cm9wZXIgdHlwZXMiXSwgWyJhbnktYW5ub3RhdGlvbiIsICI6XFxzKmFueVxcYiIsICJOZXZlciB1c2UgYGFueWAg
        dHlwZSBhbm5vdGF0aW9uIFx1MjAxNCB1c2Ugc3BlY2lmaWMgdHlwZXMsIGdlbmVyaWNzLCBvciBgdW5rbm93bmAi
        XSwgWyJhbnktYXNzZXJ0aW9uIiwgIjxhbnk+IiwgIk5ldmVyIHVzZSBgPGFueT5gIHR5cGUgYXNzZXJ0aW9uIFx1
        MjAxNCB1c2UgcHJvcGVyIHR5cGVzIl0sIFsidHMtaWdub3JlIiwgIkB0cy1pZ25vcmUiLCAiTmV2ZXIgdXNlIEB0
        cy1pZ25vcmUgXHUyMDE0IGZpeCB0aGUgdHlwZSBlcnJvciBwcm9wZXJseSJdLCBbInRzLWV4cGVjdC1lcnJvciIs
        ICJAdHMtZXhwZWN0LWVycm9yIiwgIk5ldmVyIHVzZSBAdHMtZXhwZWN0LWVycm9yIFx1MjAxNCBmaXggdGhlIHR5
        cGUgZXJyb3IgcHJvcGVybHkiXSwgWyJ0cy1ub2NoZWNrIiwgIkB0cy1ub2NoZWNrIiwgIk5ldmVyIHVzZSBAdHMt
        bm9jaGVjayBcdTIwMTQgZml4IHRoZSB0eXBlIGVycm9ycyBpbiB0aGUgZmlsZSJdLCBbImVzbGludC1kaXNhYmxl
        IiwgIi8vXFxzKmVzbGludC1kaXNhYmxlIiwgIk5ldmVyIHVzZSBlc2xpbnQtZGlzYWJsZSBcdTIwMTQgZml4IHRo
        ZSBsaW50IGlzc3VlIHByb3Blcmx5Il0sIFsiZXNsaW50LWRpc2FibGUtYmxvY2siLCAiL1xcKlxccyplc2xpbnQt
        ZGlzYWJsZSIsICJOZXZlciB1c2UgZXNsaW50LWRpc2FibGUgXHUyMDE0IGZpeCB0aGUgbGludCBpc3N1ZSBwcm9w
        ZXJseSJdLCBbInRzbGludC1kaXNhYmxlIiwgIi8vXFxzKnRzbGludDpkaXNhYmxlIiwgIk5ldmVyIHVzZSB0c2xp
        bnQ6ZGlzYWJsZSBcdTIwMTQgbWlncmF0ZSB0byBlc2xpbnQgYW5kIGZpeCB0aGUgaXNzdWUiXSwgWyJub24tbnVs
        bC1hc3NlcnRpb24iLCAiW1xcd1xcKVxcXV0hXFwuIiwgIlBvc3RmaXggYCEuYCBub24tbnVsbCBhc3NlcnRpb24g
        aGlkZXMgYSBwb3NzaWJsZSBudWxsL3VuZGVmaW5lZCBcdTIwMTQgbmFycm93IHRoZSB0eXBlIG9yIGhhbmRsZSB0
        aGUgbWlzc2luZyBjYXNlIl0sIFsidmFyLWRlY2xhcmF0aW9uIiwgIlxcYnZhclxccytbQS1aYS16XyRdIiwgIlVz
        ZSBgY29uc3RgIG9yIGBsZXRgIGluc3RlYWQgb2YgYHZhcmAgXHUyMDE0IHZhciBpcyBmdW5jdGlvbi1zY29wZWQg
        YW5kIGhvaXN0ZWQiXSwgWyJmdW5jdGlvbi1vYmplY3QtdHlwZSIsICI6XFxzKig/OkZ1bmN0aW9ufE9iamVjdClc
        XGIiLCAiTmV2ZXIgdXNlIGBGdW5jdGlvbmAgb3IgYE9iamVjdGAgYXMgYSB0eXBlIFx1MjAxNCBkZWNsYXJlIHRo
        ZSBjYWxsIHNpZ25hdHVyZSBvciB0aGUgb2JqZWN0IHNoYXBlIl0sIFsiY29uc29sZS1sb2ciLCAiXFxiY29uc29s
        ZVxcLmxvZ1xccypcXCgiLCAiY29uc29sZS5sb2cgaXMgYSBkZWJ1ZyBsZWZ0b3ZlciBcdTIwMTQgcmVtb3ZlIGl0
        IG9yIHJvdXRlIHRocm91Z2ggYSBsb2dnZXIiXV19
        """
    )
)
