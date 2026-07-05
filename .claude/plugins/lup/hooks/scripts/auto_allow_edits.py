#!/usr/bin/env python3
# lup: ignore
"""PreToolUse hook that gates Edit and Write operations.

Edit decision order:
1. Protected files (.claude/, pyproject.toml, .env*) and tmp/ scratch paths
   -> ask, always (overriding auto-accept). A `# lup:` marker change shows
   the review-gate reason; any other change shows a generic reason. The
   /lup:resolve editor subagent is allowed into protected files (its branch is
   reviewed at merge), but a marker-count change still asks.
2. Anti-patterns scanned over added lines in .py and TS-family files
   (see ANTI_PATTERNS / TS_ANTI_PATTERNS), per rule and by rule id:
   - bare `# lup: ignore` in the first 10 lines on disk -> skip the whole scan;
     a typed `# lup: ignore[id]` there disables only that rule (size gate still
     applies)
   - violating line carries an ignore covering the rule (bare, or typed naming
     the rule's id) -> ask (user prompt)
   - no covering ignore -> deny with a `# lup: ignore[id]` hint for that rule
3. Edit adds or removes any `# lup:` marker (count differs) -> ask
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

LUP_IGNORE_MARKER = "# lup: ignore"

# Inline review-comment markers, mirroring lup.review.markers. Inlined so this safety
# hook stays hermetic — no package import on the per-edit hot path; keep both in
# sync. A marker is `#`/`//` + `lup:` (any case, optional spaces); the
# `ignore` keyword is the escape hatch, any other note is actionable feedback.
MARKER_RE = re.compile(r"(#|//)\s*lup\s*:", re.IGNORECASE)
# An `ignore` directive is bare (`# lup: ignore`, silences every rule) or typed
# pyright-style (`# lup: ignore[rule-id, other]`, silences only the named rules).
# Mirrors lup.markers.IGNORE_RE / FILE_IGNORE_RE.
IGNORE_RE = re.compile(
    r"(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?", re.IGNORECASE
)
FILE_IGNORE_RE = re.compile(
    r"^\s*(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?\s*$", re.IGNORECASE
)

MARKER_REVIEW_REASON = "Edit adds or removes a `# lup:` marker — review before applying"
PROTECTED_REVIEW_REASON = "Protected file — review before applying"
TMP_REVIEW_REASON = "Scratch file under tmp/ — review before applying"

# Subagent types the /lup:resolve workflow spawns. They edit on throwaway,
# independently reviewed worktree branches, so protected files are allowed for
# them — but a marker-count change still asks (markers are never theirs to drop).
RESOLVE_EDITOR_AGENTS = {"resolve-editor", "lup:resolve-editor"}

# (pattern, reason) rows checked against every line an edit adds to a .py
# file. A matching line denies the edit; an inline `# lup: ignore` on the
# line downgrades to a user prompt, and a file-level marker (first 10 lines
# on disk) skips this table entirely.
#
# The importable source of truth is lup.review.antipatterns.PYTHON_ANTI_PATTERNS,
# which `lup-devtools dev check --antipatterns` audits the whole tree with. This
# hook cannot import it on the per-edit hot path, so `lup-devtools dev gen-hook`
# generates the table below from that source and writes it here — change a rule
# there and regenerate, never edit this block by hand. test_python_table_matches_hook
# in tests/unit/test_antipatterns.py pins this committed copy equal to that output.
# The rules are not custom linter rules: ruff has no plugin API, and engines that
# have one would break the hook's hermeticity.

ANTI_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "any-type",
        re.compile(r"\bAny\b"),
        "Never use Any — use specific types, TypedDict, or BaseModel",
    ),
    (
        "type-ignore",
        re.compile(r"#\s*type:\s*ignore"),
        "Never use # type: ignore — fix the type error properly",
    ),
    (
        "pyright-ignore",
        re.compile(r"#\s*pyright:\s*ignore"),
        "Never use # pyright: ignore — fix the type error properly",
    ),
    (
        "noqa",
        re.compile(r"#\s*noqa\b"),
        "Never use # noqa — fix the lint issue properly",
    ),
    (
        "generic-base",
        re.compile(r"\bGeneric\["),
        "Use Python 3.12+ class[T] syntax instead of Generic[T]",
    ),
    (
        "typing-union",
        re.compile(r"\b(?:Optional|Union)\["),
        "Use PEP 604 unions — X | None instead of Optional, X | Y instead of Union",
    ),
    (
        "typing-generics",
        re.compile(r"\b(?:List|Dict|Tuple|Set)\["),
        "Use lowercase builtin generics — list, dict, tuple, set — instead of the capitalized typing aliases",
    ),
    (
        "all-export",
        re.compile(r"__all__\s*[=:]"),
        "No __all__ — import directly from the defining module",
    ),
    (
        "dict-str-object",
        re.compile(r"\b(?:dict|Mapping)\[\s*str\s*,\s*object\s*\]"),
        "Never use dict[str, object] or Mapping[str, object] — use TypedDict or BaseModel",
    ),
    (
        "dict-str-payload",
        re.compile(
            r"\b(?:dict|Mapping|MutableMapping)\[\s*str\s*,\s*(?:str|int|float|bool|bytes|complex)\b"
        ),
        "String-keyed dict with a scalar value hides shape when the keys are a CLOSED, enumerable set — use a BaseModel or dict[Literal[...], V]. When the keys are open and data-driven (a registry/cache/counter keyed by external data) this is legitimate: add `# lup: ignore[dict-str-payload]`. Concrete class/callable value types (dict[str, Engine]) are already accepted; JsonValue covers arbitrary JSON",
    ),
    (
        "dict-get",
        re.compile(r"\.get\s*\("),
        "`.get(` on payload/TypedDict-shaped data hides the schema — use typed attribute access (BaseModel/TypedDict). On a genuinely open dict (registry, cache) add `# lup: ignore[dict-get]`",
    ),
    (
        "bare-object",
        re.compile(r"(?:(?<!\w)(?!_)\w+\s*:|->)\s*object\b"),
        "Bare `object` says nothing about the value — use a concrete type, TypedDict, or BaseModel, and narrow at untyped boundaries",
    ),
    (
        "bare-basemodel",
        re.compile(r"(?:(?<!\[)\b\w+\s*:|->)\s*BaseModel\b(?!\s*[\]|])"),
        "A parameter or return annotated exactly BaseModel accepts any model — name the concrete union of models or make the function generic",
    ),
    (
        "tuple-shape",
        re.compile(r"\btuple\["),
        "A declared `tuple[...]` shape hides what each position means — name the fields with a TypedDict or BaseModel, a `type Alias = ...` for a reused shape, or `list` for a variable-length sequence",
    ),
    (
        "frozenset-shape",
        re.compile(r"\bfrozenset\b"),
        "A declared `frozenset[...]` shape or constant is usually overkill — use a dict or a purpose-built structure. For a genuinely immutable default argument add `# lup: ignore[frozenset-shape]`",
    ),
    (
        "set-shape",
        re.compile(r"\bset\b"),
        "A declared `set` is usually better as a dict (keyed lookup) or a purpose-built structure. For a genuinely set-shaped value add `# lup: ignore[set-shape]`",
    ),
    (
        "empty-collection",
        re.compile(r"(?<![=!<>])=\s*(?:\{\}|\[\]|set\(\))"),
        "Empty-collection literals (`= {}`, `= []`, `= set()`) usually seed an append/mutate loop — build the collection with a comprehension instead, or add `# lup: ignore[empty-collection]` for a deliberate typed default",
    ),
    (
        "cast",
        re.compile(r"\bcast\s*\("),
        "`cast(...)` is a code smell — narrow with isinstance or a type guard, or fix the annotation so the cast is unnecessary",
    ),
    (
        "import-re",
        re.compile(r"\bimport\s+re\b|\bfrom\s+re\s+import\b"),
        "`import re` / `from re import` is a code smell — parse structured data with its own API instead: JSON -> json.loads, paths -> pathlib.Path, URLs -> urllib.parse, XML/HTML -> xml.etree.ElementTree / lxml, dates -> datetime",
    ),
    (
        "re-call",
        re.compile(r"\bre\.(compile|search|match|fullmatch|sub|findall|split)\s*\("),
        "Avoid regex for structured data — reach for its parser instead: JSON -> json.loads, paths -> pathlib.Path, URLs -> urllib.parse, XML/HTML -> xml.etree.ElementTree / lxml, dates -> datetime",
    ),
    (
        "string-replace",
        re.compile(r"(?<!\bos)(?<![Pp]ath)\.replace\s*\("),
        "Avoid .replace() for structured data — edit it through its parser instead (pathlib.Path for paths, urllib.parse for URLs, json for JSON)",
    ),
    (
        "string-split",
        re.compile(r"\.split\s*\((?!\s*\))"),
        "Avoid .split() for structured data — parse it instead (urllib.parse for URLs, pathlib.Path for paths, json for JSON, datetime for dates)",
    ),
    (
        "string-strip",
        re.compile(r"\.strip\s*\("),
        "Avoid .strip() for structured data — parse it instead (urllib.parse for URLs, pathlib.Path for paths, json for JSON, datetime for dates)",
    ),
    (
        "bare-except",
        re.compile(r"\bexcept\s*:"),
        "Bare `except:` catches SystemExit/KeyboardInterrupt — name the exception",
    ),
    (
        "except-baseexception",
        re.compile(r"\bexcept\s+BaseException\b"),
        "except BaseException catches KeyboardInterrupt — use Exception or narrower",
    ),
    (
        "suppress",
        re.compile(r"\bcontextlib\.suppress\b"),
        "contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    (
        "suppress-import",
        re.compile(r"\bfrom\s+contextlib\s+import\b.*\bsuppress\b"),
        "contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    (
        "dataclass",
        re.compile(
            r"@dataclass|\bimport\s+dataclasses\b|\bfrom\s+dataclasses\s+import\b"
        ),
        "Use Pydantic BaseModel (or TypedDict) instead of dataclasses",
    ),
    (
        "subprocess",
        re.compile(r"\bimport\s+subprocess\b|\bfrom\s+subprocess\s+import\b"),
        "Use the `sh` library instead of subprocess",
    ),
    (
        "os-shell",
        re.compile(r"\bos\.(?:system|popen|exec[lv]\w*)\s*\("),
        "Use the `sh` library instead of os.system()/os.popen()/os.exec*()",
    ),
    (
        "argparse",
        re.compile(r"\bimport\s+argparse\b|\bfrom\s+argparse\s+import\b"),
        "Use `typer` instead of argparse",
    ),
    (
        "rich-progress",
        re.compile(r"\brich\.progress\b|\bfrom\s+rich\.progress\s+import\b"),
        "Use `tqdm` instead of rich progress bars",
    ),
    (
        "os-path",
        re.compile(r"\bos\.path\b"),
        "Use pathlib.Path instead of os.path",
    ),
    (
        "os-file-ops",
        re.compile(
            r"\bos\.(?:getcwd|chdir|listdir|scandir|walk|mkdir|makedirs|rmdir|removedirs|remove|unlink|rename|renames|replace|link|symlink|readlink|stat|lstat|chmod|chown)\s*\("
        ),
        "Use pathlib.Path for file/dir operations instead of os.* (Path.iterdir/mkdir/unlink/rename/replace/stat/...)",
    ),
    (
        "os-environ",
        re.compile(r"\bos\.(?:environ|getenv)\b"),
        "Read configuration through pydantic-settings, not os.environ/os.getenv",
    ),
    (
        "eval-exec",
        re.compile(r"(?<![.\w])(?:eval|exec)\s*\("),
        "Never use eval()/exec() — parse the data (ast.literal_eval for literals) or dispatch explicitly",
    ),
    (
        "utcnow",
        re.compile(r"\butcnow\s*\("),
        "datetime.utcnow() is naive and deprecated — use datetime.now(timezone.utc)",
    ),
    (
        "global-statement",
        re.compile(r"^global\s+\w"),
        "No `global` statements — mutate a module-level holder object or pass state explicitly",
    ),
    (
        "private-function",
        re.compile(r"\bdef\s+_[a-zA-Z]"),
        "No `_` prefix on functions/methods — nothing is private (nest inside caller if needed)",
    ),
    (
        "private-class",
        re.compile(r"\bclass\s+_[A-Z]"),
        "No `_` prefix on classes — nothing is private",
    ),
    (
        "private-variable",
        re.compile(r"^_[a-zA-Z]\w*\s*(?::[^=]*)?=(?!=)(?!.*,\s*$)"),
        "No `_` prefix on variables/constants — nothing is private (unused `_` function parameters are exempt)",
    ),
]

TS_FILE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte")
TS_LUP_IGNORE_MARKER = "// lup: ignore"

# Same contract as ANTI_PATTERNS, for TypeScript/JavaScript-family files,
# using the `// lup: ignore` marker. Mirrors lup.review.antipatterns.TS_ANTI_PATTERNS;
# test_ts_table_matches_hook pins the mirror equal.
TS_ANTI_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "as-any",
        re.compile(r"\bas\s+any\b"),
        "Never use `as any` — use proper types or type guards",
    ),
    (
        "as-unknown",
        re.compile(r"\bas\s+unknown\b"),
        "Never use `as unknown` — use type guards or proper types",
    ),
    (
        "any-annotation",
        re.compile(r":\s*any\b"),
        "Never use `any` type annotation — use specific types, generics, or `unknown`",
    ),
    (
        "any-assertion",
        re.compile("<any>"),
        "Never use `<any>` type assertion — use proper types",
    ),
    (
        "ts-ignore",
        re.compile("@ts-ignore"),
        "Never use @ts-ignore — fix the type error properly",
    ),
    (
        "ts-expect-error",
        re.compile("@ts-expect-error"),
        "Never use @ts-expect-error — fix the type error properly",
    ),
    (
        "ts-nocheck",
        re.compile("@ts-nocheck"),
        "Never use @ts-nocheck — fix the type errors in the file",
    ),
    (
        "eslint-disable",
        re.compile(r"//\s*eslint-disable"),
        "Never use eslint-disable — fix the lint issue properly",
    ),
    (
        "eslint-disable-block",
        re.compile(r"/\*\s*eslint-disable"),
        "Never use eslint-disable — fix the lint issue properly",
    ),
    (
        "tslint-disable",
        re.compile(r"//\s*tslint:disable"),
        "Never use tslint:disable — migrate to eslint and fix the issue",
    ),
    (
        "non-null-assertion",
        re.compile(r"[\w\)\]]!\."),
        "Postfix `!.` non-null assertion hides a possible null/undefined — narrow the type or handle the missing case",
    ),
    (
        "var-declaration",
        re.compile(r"\bvar\s+[A-Za-z_$]"),
        "Use `const` or `let` instead of `var` — var is function-scoped and hoisted",
    ),
    (
        "function-object-type",
        re.compile(r":\s*(?:Function|Object)\b"),
        "Never use `Function` or `Object` as a type — declare the call signature or the object shape",
    ),
    (
        "console-log",
        re.compile(r"\bconsole\.log\s*\("),
        "console.log is a debug leftover — remove it or route through a logger",
    ),
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
    """Count `# lup:` markers (feedback or ignore) for add/remove detection."""
    return len(MARKER_RE.findall(text))


class IgnoreDirective(BaseModel):
    """A `# lup: ignore` directive's coverage. Mirrors lup.markers.

    ``rule_ids`` is ``None`` for a bare ignore that silences every rule; a set
    names the rules a typed ``# lup: ignore[a, b]`` silences.
    """

    rule_ids: set[str] | None

    def covers(self, rule_id: str) -> bool:
        return self.rule_ids is None or rule_id in self.rule_ids


def ignore_rule_ids(match: re.Match[str]) -> set[str] | None:
    """Rule ids a matched ignore names, or None for a bare (all-rules) ignore."""
    raw = match.group("ids")
    if raw is None:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def inline_ignore(line: str) -> IgnoreDirective | None:
    """The inline `# lup: ignore` directive on a line, or None."""
    match = IGNORE_RE.search(line)
    if match is None:
        return None
    return IgnoreDirective(rule_ids=ignore_rule_ids(match))


def read_file_level_ignore(file_path: str) -> IgnoreDirective | None:
    """The file-level `# lup: ignore` on disk (first 10 lines), or None.

    A bare directive disables every rule for the file; a typed
    `# lup: ignore[id]` disables only the named rules file-wide.
    """
    try:
        with open(file_path) as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                match = FILE_IGNORE_RE.match(line)
                if match is not None:
                    return IgnoreDirective(rule_ids=ignore_rule_ids(match))
    except OSError:
        return None
    return None


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
    patterns: list[tuple[str, re.Pattern[str], str]] | None = None,
    ignore_marker: str = LUP_IGNORE_MARKER,
    line_violations: dict[int, str] | None = None,
) -> Violation | None:
    """Check newly added lines for anti-patterns, per rule.

    A bare file-level ignore (first 10 lines on disk) disables every rule; a
    typed `# lup: ignore[id]` disables only the named rule file-wide. On an
    added line, each tripped rule is checked on its own: an inline directive
    that covers the rule downgrades it to a prompt, one that does not (or none
    at all) denies. line_violations maps new_string line indices to precomputed
    violation reasons (e.g. silent swallows from find_swallowed_excepts).

    Returns (decision, reason) or None:
    - inline ignore covering the rule -> ("ask", reason)
    - no covering ignore -> ("deny", reason with a typed-ignore hint)
    """
    if patterns is None:
        patterns = ANTI_PATTERNS

    file_directive = read_file_level_ignore(file_path) if file_path else None
    if file_directive is not None and file_directive.rule_ids is None:
        return None  # bare file-level opt-out disables every rule
    file_disabled = file_directive.rule_ids if file_directive is not None else set()

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
            hits: list[tuple[str, str]] = [
                (rule_id, message)
                for rule_id, pattern, message in patterns
                if pattern.search(stripped)
            ]
            if line_violations and idx in line_violations:
                hits.insert(0, ("silent-except", line_violations[idx]))
            if not hits:
                continue
            preview = stripped[:80]
            directive = inline_ignore(new_lines[idx])
            for rule_id, message in hits:
                if rule_id in file_disabled:
                    continue
                if directive is not None and directive.covers(rule_id):
                    ask_reasons.append(f"{message} | line: {preview}")
                    continue
                hint = (
                    f"Add `{ignore_marker}[{rule_id}]` to the line "
                    "(or file-level) to request approval"
                )
                return ("deny", f"Denied: {message} | line: {preview}. {hint}")

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


def anti_pattern_decision(
    file_path: str, old_string: str, new_string: str
) -> AllowDecision | None:
    """Scan added lines for anti-patterns in .py and TS-family files.

    Shared by Edit and Write so an autonomous editor's full-file writes face the
    same denials as its edits. Returns a deny/ask decision, or None when clean.
    """
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
            ignore_marker=TS_LUP_IGNORE_MARKER,
        )
        if violation:
            return violation_decision(violation)

    return None


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

    anti_pattern = anti_pattern_decision(file_path, old_string, new_string)
    if anti_pattern is not None:
        return anti_pattern

    if marker_count(old_string) != marker_count(new_string):
        return ask_decision(MARKER_REVIEW_REASON)

    if old_string and not new_string:
        return allow_decision()

    if replace_all and is_identifier_rename(old_string, new_string):
        return allow_decision()

    if count_real_additions(old_string, new_string) <= MAX_REAL_CHANGES:
        return allow_decision()

    # The resolve editor writes autonomously on a disposable, reviewed branch:
    # past the tmp/, marker, and anti-pattern guardrails above, a larger edit
    # that would otherwise prompt is auto-allowed for it (never the main session).
    if agent_type in RESOLVE_EDITOR_AGENTS:
        return allow_decision()

    return None


def decide_write(tool_input: WriteInput, agent_type: str = "") -> AllowDecision | None:
    """Gate Write (full-file) operations.

    Writes never auto-allow — a whole-file rewrite needs user eyes. Protected
    and tmp/ paths prompt (identical to Edit). The /lup:resolve editor subagent
    writes autonomously on its disposable, reviewed branch, but tmp/ still
    prompts and anti-pattern denials still bite; everything else defers to the
    normal permission flow.
    """
    file_path = tool_input.file_path
    gate = always_ask_decision(file_path, agent_type)
    if gate is not None:
        return gate
    if agent_type in RESOLVE_EDITOR_AGENTS:
        anti_pattern = anti_pattern_decision(file_path, "", tool_input.content)
        if anti_pattern is not None:
            return anti_pattern
        return allow_decision()
    return None


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
