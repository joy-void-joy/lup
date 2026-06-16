#!/usr/bin/env python3
"""PreToolUse hook that gates Edit and Write operations.

Edit decision order:
1. Protected files (.claude/, pyproject.toml, .env*) and tmp/ scratch paths
   -> ask, always (overriding auto-accept). A `# claude:` marker change shows
   the review-gate reason; any other change shows a generic reason. The
   /lup:resolve editor subagent is allowed into protected files (its branch is
   reviewed at merge), but a marker-count change still asks.
2. Anti-patterns scanned over added lines in .py and TS-family files
   (see ANTI_PATTERNS / TS_ANTI_PATTERNS):
   - file has `# claude: ignore` in its first 10 lines on disk -> skip the
     anti-pattern scan (the size gate below still applies)
   - violating line carries an inline `# claude: ignore` -> ask (user prompt)
   - no marker -> deny with hint about `# claude: ignore`
3. Edit adds or removes any `# claude:` marker (count differs) -> ask
4. Pure deletion (new_string is empty) -> allow
5. replace_all that is a single-line identifier rename -> allow
   (any other replace_all falls through to the size gate)
6. Size gate: count nontrivial added lines per change block (using a state
   machine for context-aware classification) -> allow if every block stays
   within MAX_REAL_CHANGES

Write decision order:
1. Protected files and tmp/ scratch paths -> ask (identical to Edit)
2. Otherwise -> defer to the user (None; full-file rewrites never auto-allow)
"""

import difflib
import json
import re
import sys

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ValidationError

MAX_REAL_CHANGES = 3

# ---------------------------------------------------------------------------
# Configuration: protected paths and anti-pattern tables
# ---------------------------------------------------------------------------

# Files this hook never auto-allows: Edit and Write both prompt the user.
PROTECTED_PATTERNS = [
    r"(^|/)\.claude/",
    r"(^|/)pyproject\.toml$",
    r"(^|/)\.env($|\.)",
]

# The repo's own scratch dir (one-off scripts live here). The system temp dir
# (/tmp/..., used by pytest fixtures) is deliberately excluded — see is_tmp_path.
TMP_DIR = "tmp"

CLAUDE_IGNORE_MARKER = "# claude: ignore"

# Inline review-comment markers, mirroring lup.markers. Inlined so this safety
# hook stays hermetic — no package import on the per-edit hot path; keep both in
# sync. A marker is `#`/`//` + `claude:` (any case, optional spaces); the
# `ignore` keyword is the escape hatch, any other note is actionable feedback.
MARKER_RE = re.compile(r"(#|//)\s*claude\s*:", re.IGNORECASE)
IGNORE_RE = re.compile(r"(#|//)\s*claude\s*:\s*ignore\b", re.IGNORECASE)
FILE_IGNORE_RE = re.compile(r"^\s*(#|//)\s*claude\s*:\s*ignore\s*$", re.IGNORECASE)

MARKER_REVIEW_REASON = "Edit adds or removes a `# claude:` marker — review before applying"
PROTECTED_REVIEW_REASON = "Protected file — review before applying"
TMP_REVIEW_REASON = "Scratch file under tmp/ — review before applying"

# Subagent types the /lup:resolve workflow spawns. They edit on throwaway,
# independently reviewed worktree branches, so protected files are allowed for
# them — but a marker-count change still asks (markers are never theirs to drop).
RESOLVE_EDITOR_AGENTS = {"resolve-editor", "lup:resolve-editor"}

# (pattern, reason) rows checked against every line an edit adds to a .py
# file. A matching line denies the edit; an inline `# claude: ignore` on the
# line downgrades to a user prompt, and a file-level marker (first 10 lines
# on disk) skips this table entirely.

# claude: I am wondering whether this is something we can do with a linter actually? Is there a way to specify custome rules this way? Might be the best way to unify this?
ANTI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bAny\b"),
        "Never use Any — use specific types, TypedDict, or BaseModel",
    ),
    (
        re.compile(r"#\s*type:\s*ignore"),
        "Never use # type: ignore — fix the type error properly",
    ),
    (
        re.compile(r"#\s*pyright:\s*ignore"),
        "Never use # pyright: ignore — fix the type error properly",
    ),
    (re.compile(r"#\s*noqa\b"), "Never use # noqa — fix the lint issue properly"),
    (
        re.compile(r"\bGeneric\["),
        "Use Python 3.12+ class[T] syntax instead of Generic[T]",
    ),
    (
        re.compile(r"__all__\s*[=:]"),
        "No __all__ — import directly from the defining module",
    ),
    (
        re.compile(r"\bdict\[\s*str\s*,\s*object\s*\]"), #claude: seems a bit overspecific. Shouldn't it be about object?
        # claude: In fact, the model frequently uses Mapping[str, object] instead. Can't say if it's to avoid being detected, or if there are legitimate reasonsn there
        "Never use dict[str, object] — use TypedDict or BaseModel",
    ),
    (
        re.compile(r"\bimport\s+re\b"),
        "`import re` is a code smell — use structured APIs (json, pathlib, urllib.parse, etc.)", #claude: I notice the agent often tries to push through anyway. Maybe we're missing better explanation about what to do instead, or something?
    ),
    (
        re.compile(r"\bfrom\s+re\s+import\b"),
        "`from re import` is a code smell — use structured APIs instead", #claude: We might want something like a anti-pattern library
    ),
    (
        re.compile(r"\bre\.(compile|search|match|fullmatch|sub|findall|split)\s*\("),
        "Avoid regex for structured data — use proper parsers (json, pathlib, urllib.parse, xml, etc.)",
    ),
    (
        re.compile(r"\.replace\s*\("),
        "Avoid .replace() for structured data — use proper parsers",
    ),
    (
        re.compile(r"\.split\s*\("),
        "Avoid .split() for structured data — use proper parsers",
    ),
    (
        re.compile(r"\bexcept\s*:"),
        "Bare `except:` catches SystemExit/KeyboardInterrupt — name the exception",
    ),
    (
        re.compile(r"\bexcept\s+BaseException\b"),
        "except BaseException catches KeyboardInterrupt — use Exception or narrower",
    ),
    (
        re.compile(r"\bcontextlib\.suppress\b"),
        "contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    (
        re.compile(r"\bfrom\s+contextlib\s+import\b.*\bsuppress\b"),
        "contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    (
        re.compile(r"@dataclass|\bfrom\s+dataclasses\s+import\b"),
        "Use Pydantic BaseModel (or TypedDict) instead of dataclasses", #claude: Do we have good instructions about when to use which, BaseModel or TypedDict? Also you don't capture import dataclass (see my comment about needing an anti-pattern library)
    ),
    (
        re.compile(r"\bimport\s+subprocess\b|\bfrom\s+subprocess\s+import\b"),
        "Use the `sh` library instead of subprocess",
    ),
    (
        re.compile(r"\bimport\s+argparse\b|\bfrom\s+argparse\s+import\b"),
        "Use `typer` instead of argparse",
    ),
    (
        re.compile(r"\brich\.progress\b|\bfrom\s+rich\.progress\s+import\b"),
        "Use `tqdm` instead of rich progress bars",
    ),
    (
        re.compile(r"\bdef\s+_[a-zA-Z]"),
        "No `_` prefix on functions/methods — nothing is private (nest inside caller if needed)",
    ),
    (
        re.compile(r"\bclass\s+_[A-Z]"),
        "No `_` prefix on classes — nothing is private",
    ),
    # Fires only on assignments: bare annotations and trailing-comma lines
    # are function parameters, which may use `_` for unused arguments.
    (
        re.compile(r"^_[a-zA-Z]\w*\s*(?::[^=]*)?=(?!=)(?!.*,\s*$)"),
        "No `_` prefix on variables/constants — nothing is private "
        "(unused `_` function parameters are exempt)",
    ),
    # claude: Can you brainstorm more anti-patterns, or things we might want? Let's brainstorm about them
]

TS_FILE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte")
TS_CLAUDE_IGNORE_MARKER = "// claude: ignore"

# Same contract as ANTI_PATTERNS, for TypeScript/JavaScript-family files,
# using the `// claude: ignore` marker.
TS_ANTI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bas\s+any\b"),
        "Never use `as any` — use proper types or type guards",
    ),
    (
        re.compile(r"\bas\s+unknown\b"),
        "Never use `as unknown` — use type guards or proper types",
    ),
    (
        re.compile(r":\s*any\b"),
        "Never use `any` type annotation — use specific types, generics, or `unknown`",
    ),
    (
        re.compile(r"<any>"),
        "Never use `<any>` type assertion — use proper types",
    ),
    (
        re.compile(r"@ts-ignore"),
        "Never use @ts-ignore — fix the type error properly",
    ),
    (
        re.compile(r"@ts-expect-error"),
        "Never use @ts-expect-error — fix the type error properly",
    ),
    (
        re.compile(r"@ts-nocheck"),
        "Never use @ts-nocheck — fix the type errors in the file",
    ),
    (
        re.compile(r"//\s*eslint-disable"),
        "Never use eslint-disable — fix the lint issue properly",
    ),
    (
        re.compile(r"/\*\s*eslint-disable"),
        "Never use eslint-disable — fix the lint issue properly",
    ),
    (
        re.compile(r"//\s*tslint:disable"),
        "Never use tslint:disable — migrate to eslint and fix the issue",
    ),

    # claude: Same here, would like a bit more
]


def is_protected_file(file_path: str) -> bool:
    return any(re.search(p, file_path) for p in PROTECTED_PATTERNS)


def is_tmp_path(file_path: str) -> bool:
    """Whether a path is under the repo's ./tmp/ scratch dir.

    The system temp dir (/tmp/..., used by pytest fixtures) is excluded — only
    the project's own tmp/ is gated.
    """
    parts = PurePosixPath(file_path).parts
    if parts[:2] == ("/", TMP_DIR):
        return False
    return TMP_DIR in parts


def marker_count(text: str) -> int:
    """Count `# claude:` markers (feedback or ignore) for add/remove detection."""
    return len(MARKER_RE.findall(text))


def has_file_level_ignore(file_path: str) -> bool:
    """Check if the file on disk has a `# claude: ignore` marker in the first 10 lines."""
    try:
        with open(file_path) as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                if FILE_IGNORE_RE.match(line):
                    return True
    except OSError:
        return False
    return False


STRING_PREFIX_RE = re.compile(r"^[fFbBrRuU]*")


def is_string_literal(stripped: str) -> bool:
    """Check if a stripped line is a string literal (possibly with trailing comma)."""
    s = stripped.rstrip(",").rstrip()
    if len(s) < 2:
        return False
    bare = STRING_PREFIX_RE.sub("", s)
    if len(bare) < 2:
        return False
    for q in ('"""', "'''"):
        if bare.startswith(q) and bare.endswith(q) and len(bare) >= 2 * len(q):
            return True
    for q in ('"', "'"):
        if bare.startswith(q) and bare.endswith(q):
            return True
    return False


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def is_identifier_rename(old_string: str, new_string: str) -> bool:
    """Whether a replace_all is a genuine single-line symbol rename.

    Both sides must be single-line, non-empty, and look like an identifier
    (optionally a dotted attribute path). A multi-line ``replace_all`` that
    rewrites logic is not a rename and must fall through to the user.
    """
    if not old_string or not new_string:
        return False
    if "\n" in old_string or "\n" in new_string:
        return False
    return bool(IDENTIFIER_RE.match(old_string.strip())) and bool(
        IDENTIFIER_RE.match(new_string.strip())
    )


def is_trivial_content(stripped: str) -> bool:
    if not stripped:
        return True
    # Non-alpha lines: ), ], }, ):, etc.
    if not any(c.isalpha() for c in stripped):
        return True
    if stripped.startswith("#"):
        return True
    if stripped.startswith(("import ", "from ")):
        return True
    if stripped == "pass":
        return True
    if is_string_literal(stripped):
        return True
    # Type annotations / field definitions: name: Type, name: Type = value
    if re.match(r"^\w+\s*:\s*\S", stripped):
        return True
    return False


def classify_trivial(lines: list[str]) -> list[bool]:
    result: list[bool] = []
    in_docstring = False
    docstring_delim = ""
    in_import = False
    in_type_def = False
    type_def_indent = 0

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip()) if stripped else 0

        if in_docstring:
            result.append(True)
            if docstring_delim in stripped:
                in_docstring = False
            continue

        if in_import:
            result.append(True)
            if ")" in stripped:
                in_import = False
            continue

        for delim in ('"""', "'''"):
            if delim in stripped:
                if stripped.count(delim) == 1:
                    in_docstring = True
                    docstring_delim = delim
                result.append(True)
                break
        else:
            # Continuation mode only for actual multi-line import statements
            # (`from x import (`); other open parens stay nontrivial context.
            if (
                stripped.startswith(("import ", "from "))
                and "(" in stripped
                and ")" not in stripped
            ):
                in_import = True
                result.append(True)
                continue

            if in_type_def and stripped and indent <= type_def_indent:
                in_type_def = False

            m = re.match(
                r"(\s*)class\s+\w+\s*\(.*(?:TypedDict|BaseModel).*\)\s*:", line
            )
            if m:
                in_type_def = True
                type_def_indent = len(m.group(1))
                result.append(True)
            elif in_type_def:
                result.append(True)
            else:
                result.append(is_trivial_content(stripped))

    return result


def count_real_additions(old_string: str, new_string: str) -> int:
    """Return the max nontrivial addition count across change blocks.

    Consecutive insert/replace/delete opcodes form a single block.
    Each block is checked independently, so multiple small changes
    scattered through the diff are each allowed up to MAX_REAL_CHANGES.
    """
    old_lines = old_string.splitlines() if old_string else []
    new_lines = new_string.splitlines() if new_string else []

    matcher = difflib.SequenceMatcher(
        None,
        [ln.strip() for ln in old_lines],
        [ln.strip() for ln in new_lines],
    )

    trivial = classify_trivial(new_lines)

    max_nontrivial = 0
    current_block: set[int] = set()

    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            current_block.update(range(j1, j2))
        elif tag == "equal":
            if current_block:
                n = sum(1 for j in current_block if not trivial[j])
                max_nontrivial = max(max_nontrivial, n)
                current_block = set()
        # "delete" doesn't add indices but doesn't break the block

    if current_block:
        n = sum(1 for j in current_block if not trivial[j])
        max_nontrivial = max(max_nontrivial, n)

    return max_nontrivial


AllowDecision = dict[str, dict[str, str]]


class EditInput(BaseModel):
    file_path: str = ""
    old_string: str = ""
    new_string: str = ""
    replace_all: bool = False


class WriteInput(BaseModel):
    file_path: str = ""
    content: str = ""


class HookEnvelope(BaseModel):
    tool_name: str = ""
    agent_type: str = ""


class EditEvent(BaseModel):
    tool_input: EditInput = EditInput()


class WriteEvent(BaseModel):
    tool_input: WriteInput = WriteInput()


def allow_decision() -> AllowDecision:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "Auto-allowed: safe edit pattern detected",
        }
    }


def deny_decision(reason: str) -> AllowDecision:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def ask_decision(reason: str) -> AllowDecision:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }


SWALLOW_REASON = (
    "Never silently swallow exceptions — log with logger.exception(), "
    "handle meaningfully, or re-raise"
)

EXCEPT_CLAUSE_RE = re.compile(r"except\b[^:]*:\s*(?P<body>.*)$")

SILENT_BODIES = ("pass", "...")


def find_swallowed_excepts(new_lines: list[str]) -> dict[int, str]:
    """Map line indices of silent exception swallows to a violation reason.

    Flags `except ...: pass` one-liners on the except line, and multi-line
    handlers whose first statement is `pass`/`...` on the body line — so the
    check fires even when an edit adds only the body under an existing
    except clause.
    """
    violations: dict[int, str] = {}
    for i, line in enumerate(new_lines):
        clause = EXCEPT_CLAUSE_RE.match(line.strip())
        if not clause:
            continue
        inline = clause.group("body").partition("#")[0].strip()
        if inline:
            if inline in SILENT_BODIES:
                violations[i] = SWALLOW_REASON
            continue
        for j in range(i + 1, len(new_lines)):
            body = new_lines[j].strip()
            if not body or body.startswith("#"):
                continue
            if body.partition("#")[0].strip() in SILENT_BODIES:
                violations[j] = SWALLOW_REASON
            break
    return violations


Violation = tuple[Literal["ask", "deny"], str]


def find_anti_pattern_violations(
    old_string: str,
    new_string: str,
    file_path: str = "",
    patterns: list[tuple[re.Pattern[str], str]] | None = None,
    ignore_marker: str = CLAUDE_IGNORE_MARKER,
    line_violations: dict[int, str] | None = None,
) -> Violation | None:
    """Check newly added lines for anti-patterns.

    A file-level ignore marker (first 10 lines on disk) disables the scan;
    the caller's size gate still applies. line_violations maps new_string
    line indices to precomputed violation reasons (e.g. silent swallows
    from find_swallowed_excepts).

    Returns (decision, reason) or None:
    - inline ignore marker on the violating line -> ("ask", reason)
    - no marker -> ("deny", reason with hint)
    """
    if patterns is None:
        patterns = ANTI_PATTERNS

    if file_path and has_file_level_ignore(file_path):
        return None

    old_lines = old_string.splitlines() if old_string else []
    new_lines = new_string.splitlines() if new_string else []

    matcher = difflib.SequenceMatcher(
        None,
        [ln.strip() for ln in old_lines],
        [ln.strip() for ln in new_lines],
    )

    ask_reasons: list[str] = []

    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag not in ("insert", "replace"):
            continue
        for idx in range(j1, j2):
            stripped = new_lines[idx].strip()
            if not stripped or stripped.startswith("#") and "type:" not in stripped:
                continue
            hits = [r for pattern, r in patterns if pattern.search(stripped)]
            if line_violations and idx in line_violations:
                hits.insert(0, line_violations[idx])
            if not hits:
                continue
            preview = stripped[:80]
            if IGNORE_RE.search(new_lines[idx]):
                ask_reasons.append(f"{hits[0]} | line: {preview}")
            else:
                hint = f"Add `{ignore_marker}` to the line (or file-level) to request approval"
                return ("deny", f"Denied: {hits[0]} | line: {preview}. {hint}")

    if ask_reasons:
        return ("ask", ask_reasons[0])
    return None


def violation_decision(violation: Violation) -> AllowDecision:
    decision, reason = violation
    match decision:
        case "ask":
            return ask_decision(reason)
        case "deny":
            return deny_decision(reason)


def always_ask_decision(
    file_path: str, agent_type: str = "", old_string: str = "", new_string: str = ""
) -> AllowDecision | None:
    """Paths the hook never auto-allows — Edit and Write both prompt the user.

    Protected config and tmp/ scratch files always defer to a prompt rather
    than auto-allowing (Edit) or denying (Write), so the two tools behave
    identically here. The /lup:resolve editor subagent is the exception: it may
    edit protected files (reviewed at merge), though a marker-count change still
    asks. Any other path returns None.
    """
    if is_protected_file(file_path):
        if marker_count(old_string) != marker_count(new_string):
            return ask_decision(MARKER_REVIEW_REASON)
        if agent_type in RESOLVE_EDITOR_AGENTS:
            return allow_decision()
        return ask_decision(PROTECTED_REVIEW_REASON)
    if is_tmp_path(file_path):
        return ask_decision(TMP_REVIEW_REASON)
    return None


def decide(tool_input: EditInput, agent_type: str = "") -> AllowDecision | None:
    file_path = tool_input.file_path
    old_string = tool_input.old_string
    new_string = tool_input.new_string
    replace_all = tool_input.replace_all

    gate = always_ask_decision(file_path, agent_type, old_string, new_string)
    if gate is not None:
        return gate

    if file_path.endswith(".py") and new_string:
        violation = find_anti_pattern_violations(
            old_string,
            new_string,
            file_path,
            line_violations=find_swallowed_excepts(new_string.splitlines()),
        )
        if violation:
            return violation_decision(violation)

    if file_path.endswith(TS_FILE_EXTENSIONS) and new_string:
        violation = find_anti_pattern_violations(
            old_string,
            new_string,
            file_path,
            patterns=TS_ANTI_PATTERNS,
            ignore_marker=TS_CLAUDE_IGNORE_MARKER,
        )
        if violation:
            return violation_decision(violation)

    if marker_count(old_string) != marker_count(new_string):
        return ask_decision(MARKER_REVIEW_REASON)

    if old_string and not new_string:
        return allow_decision()

    if replace_all and is_identifier_rename(old_string, new_string):
        return allow_decision()

    if count_real_additions(old_string, new_string) <= MAX_REAL_CHANGES:
        return allow_decision()

    return None


def decide_write(tool_input: WriteInput, agent_type: str = "") -> AllowDecision | None:
    """Gate Write (full-file) operations.

    Writes never auto-allow — a whole-file rewrite needs user eyes. Protected
    and tmp/ paths prompt (identical to Edit), except for the /lup:resolve editor
    subagent; everything else defers to the normal permission flow.
    """
    return always_ask_decision(tool_input.file_path, agent_type)


def main() -> None:
    try:
        raw = sys.stdin.read()
        envelope = HookEnvelope.model_validate_json(raw)
        match envelope.tool_name:
            case "Edit":
                result = decide(
                    EditEvent.model_validate_json(raw).tool_input, envelope.agent_type
                )
            case "Write":
                result = decide_write(
                    WriteEvent.model_validate_json(raw).tool_input, envelope.agent_type
                )
            case _:
                sys.exit(0)
    except (ValidationError, OSError):
        sys.exit(0)

    if result:
        json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
