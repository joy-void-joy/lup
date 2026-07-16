# lup: ignore[string-split, tuple-shape, import-re, re-call, dict-get, set-shape, empty-collection]
"""Dependency-free semantic policy snapshot embedded into generated plugins."""

import base64
import json
from inspect import getsource

from lup.codescan.antipatterns import (
    PYTHON_ANTI_PATTERNS,
    TS_ANTI_PATTERNS,
    empty_collection_exempt_lines,
)
from lup.codescan.common import python_docstring_lines

BUNDLED_POLICY_SOURCE = '''# lup: ignore[dict-get, import-re, re-call, string-split, set-shape, empty-collection]
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


SHELL_PUNCTUATION = ";&|<>\\n"
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
    lexer.whitespace = " \\t\\r"
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


MARKER_RE = re.compile(r"(#|//)\\s*lup\\s*:", re.IGNORECASE)
IGNORE_RE = re.compile(
    r"(#|//)\\s*lup\\s*:\\s*ignore\\b(?:\\s*\\[(?P<ids>[^\\]]*)\\])?",
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
'''


def bundled_antipattern_rows() -> dict[str, list[tuple[str, str, str]]]:
    """Compile the hermetic table directly from the canonical rule objects."""
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


bundled_rows_json = json.dumps(bundled_antipattern_rows(), sort_keys=True)
bundled_rows_base64 = base64.b64encode(bundled_rows_json.encode("utf-8")).decode(
    "ascii"
)
bundled_rows_lines = "\n".join(
    "        " + bundled_rows_base64[offset : offset + 88]
    for offset in range(0, len(bundled_rows_base64), 88)
)
BUNDLED_POLICY_SOURCE += "\n\n" + getsource(python_docstring_lines)
BUNDLED_POLICY_SOURCE += "\n\n" + getsource(empty_collection_exempt_lines)
BUNDLED_POLICY_SOURCE += (
    "\n\nANTI_PATTERN_ROWS = json.loads(\n"
    "    base64.b64decode(\n"
    '        """\n' + bundled_rows_lines + '\n        """\n'
    "    )\n"
    ")\n"
)
