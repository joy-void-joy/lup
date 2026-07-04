# lup: ignore
"""Single importable source of truth for the codebase's anti-pattern set.

The edit-permission hook (`.claude/plugins/lup/hooks/scripts/auto_allow_edits.py`)
denies an edit whose added lines match one of these patterns unless the line
carries a `# lup: ignore`. The hook cannot import a package on its per-edit
hot path, so it mirrors these tables; a test asserts the two stay identical, and
the `lup-devtools dev check --antipatterns` auditor consumes them to scan the
whole tree after the fact (catching lines that slipped in past the hook and
`# lup: ignore` markers that no longer guard anything).

The rules live here as plain regexes rather than as custom linter rules: ruff
has no plugin API, and engines that do (flake8, pylint, semgrep) could not run
inside the hermetic hook — the shared table, mirrored hook, equality test, and
tree auditor together are the unification a linter would have provided.

Each entry pairs a compiled regex with the message the hook and auditor show.
This module imports only the standard library and `pydantic` (directly and
through `lup.review.common`) so the auditor can load it cheaply; `# lup:` marker
detection stays in `lup.review.markers`, and the shared scan core — ignore
matching, comment-column tokenization, the line cursor — in `lup.review.common`,
which this set's consumers and the auditor import directly.
"""

import re

from pydantic import BaseModel

from lup.review.common import IGNORE_RE, PythonContext, has_file_level_ignore


class AntiPattern(BaseModel):
    """One forbidden code shape: the regex that detects it and why it is denied."""

    model_config = {"arbitrary_types_allowed": True}

    pattern: re.Pattern[str]
    message: str


PYTHON_ANTI_PATTERNS: list[AntiPattern] = [
    AntiPattern(
        pattern=re.compile(r"\bAny\b"),
        message="Never use Any — use specific types, TypedDict, or BaseModel",
    ),
    AntiPattern(
        pattern=re.compile(r"#\s*type:\s*ignore"),
        message="Never use # type: ignore — fix the type error properly",
    ),
    AntiPattern(
        pattern=re.compile(r"#\s*pyright:\s*ignore"),
        message="Never use # pyright: ignore — fix the type error properly",
    ),
    AntiPattern(
        pattern=re.compile(r"#\s*noqa\b"),
        message="Never use # noqa — fix the lint issue properly",
    ),
    AntiPattern(
        pattern=re.compile(r"\bGeneric\["),
        message="Use Python 3.12+ class[T] syntax instead of Generic[T]",
    ),
    AntiPattern(
        pattern=re.compile(r"\b(?:Optional|Union)\["),
        message="Use PEP 604 unions — X | None instead of Optional, X | Y instead of Union",
    ),
    AntiPattern(
        pattern=re.compile(r"\b(?:List|Dict|Tuple|Set)\["),
        message="Use lowercase builtin generics — list, dict, tuple, set — "
        "instead of the capitalized typing aliases",
    ),
    AntiPattern(
        pattern=re.compile(r"__all__\s*[=:]"),
        message="No __all__ — import directly from the defining module",
    ),
    AntiPattern(
        pattern=re.compile(r"\b(?:dict|Mapping)\[\s*str\s*,\s*object\s*\]"),
        message="Never use dict[str, object] or Mapping[str, object] — use TypedDict or BaseModel",
    ),
    AntiPattern(
        pattern=re.compile(
            r"\b(?:dict|Mapping|MutableMapping)\[\s*str\s*,(?!\s*JsonValue\b)"
        ),
        message="String-keyed dict[str, ...] hides the value shape — name the fields "  # lup: I'm torn on this one. Like, for instance it can make sense to have dict[str, Engine], and use keyof this dict directly to have no dedup.
        # lup: We should add tuple here though
        "with a TypedDict or BaseModel, or use JsonValue for arbitrary JSON",
    ),
    AntiPattern(
        pattern=re.compile(r"(?:(?<!\w)(?!_)\w+\s*:|->)\s*object\b"),
        message="Bare `object` says nothing about the value — use a concrete type, "
        "TypedDict, or BaseModel, and narrow at untyped boundaries",
    ),
    AntiPattern(
        pattern=re.compile(r"(?:(?<!\[)\b\w+\s*:|->)\s*BaseModel\b(?!\s*[\]|])"),
        message="A parameter or return annotated exactly BaseModel accepts any model — "
        "name the concrete union of models or make the function generic",
    ),
    AntiPattern(
        pattern=re.compile(r"\btuple\["),
        message="`tuple[...]` as a return shape is a code smell — name the fields with a "  # lup: As a variable as well
        "TypedDict or BaseModel, or a `type Alias = ...` if it is a reused shape",
    ),
    AntiPattern(
        pattern=re.compile(r"\bcast\s*\("),
        message="`cast(...)` is a code smell — narrow with isinstance or a type guard, "
        "or fix the annotation so the cast is unnecessary",
    ),
    AntiPattern(
        pattern=re.compile(r"\bimport\s+re\b"),
        message="`import re` is a code smell — parse structured data with its own API instead: "
        "JSON -> json.loads, paths -> pathlib.Path, URLs -> urllib.parse, "
        "XML/HTML -> xml.etree.ElementTree / lxml, dates -> datetime",
    ),
    AntiPattern(
        pattern=re.compile(r"\bfrom\s+re\s+import\b"),
        message="`from re import` is a code smell — parse structured data with its own API instead: "
        "JSON -> json.loads, paths -> pathlib.Path, URLs -> urllib.parse, "
        "XML/HTML -> xml.etree.ElementTree / lxml, dates -> datetime",
    ),
    AntiPattern(
        pattern=re.compile(
            r"\bre\.(compile|search|match|fullmatch|sub|findall|split)\s*\("
        ),
        message="Avoid regex for structured data — reach for its parser instead: "
        "JSON -> json.loads, paths -> pathlib.Path, URLs -> urllib.parse, "
        "XML/HTML -> xml.etree.ElementTree / lxml, dates -> datetime",
    ),
    AntiPattern(
        # `.replace` on `os`, `Path`, or a `*path` receiver is pathlib/os's
        # atomic file rename, not string surgery — the lookbehinds keep the
        # codebase's path-named receivers out of the net.
        pattern=re.compile(
            r"(?<!\bos)(?<![Pp]ath)\.replace\s*\("
        ),  # lup: When possible we should avoid os. and prefer Path. Probably os. should be part of the antippattern
        message="Avoid .replace() for structured data — edit it through its parser instead "
        "(pathlib.Path for paths, urllib.parse for URLs, json for JSON)",
    ),
    AntiPattern(
        # Argument-less `.split()` is whitespace tokenization, which has no
        # parser alternative — only splitting on an explicit separator matches.
        # lup: Why is argument-less fine?
        pattern=re.compile(r"\.split\s*\((?!\s*\))"),
        message="Avoid .split() for structured data — parse it instead "
        "(urllib.parse for URLs, pathlib.Path for paths, json for JSON, datetime for dates)",
    ),
    AntiPattern(
        pattern=re.compile(r"\.strip\s*\("),
        message="Avoid .strip() for structured data — parse it instead "
        "(urllib.parse for URLs, pathlib.Path for paths, json for JSON, datetime for dates)",
    ),
    AntiPattern(
        pattern=re.compile(r"\bexcept\s*:"),
        message="Bare `except:` catches SystemExit/KeyboardInterrupt — name the exception",
    ),
    AntiPattern(
        pattern=re.compile(r"\bexcept\s+BaseException\b"),
        message="except BaseException catches KeyboardInterrupt — use Exception or narrower",
    ),
    AntiPattern(
        pattern=re.compile(r"\bcontextlib\.suppress\b"),
        message="contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    AntiPattern(
        pattern=re.compile(r"\bfrom\s+contextlib\s+import\b.*\bsuppress\b"),
        message="contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    AntiPattern(
        pattern=re.compile(
            r"@dataclass|\bimport\s+dataclasses\b|\bfrom\s+dataclasses\s+import\b"
        ),
        message="Use Pydantic BaseModel (or TypedDict) instead of dataclasses",
    ),
    AntiPattern(
        pattern=re.compile(r"\bimport\s+subprocess\b|\bfrom\s+subprocess\s+import\b"),
        message="Use the `sh` library instead of subprocess",
    ),
    AntiPattern(
        pattern=re.compile(r"\bos\.(?:system|popen)\s*\("),
        message="Use the `sh` library instead of os.system()/os.popen()",
    ),
    AntiPattern(
        pattern=re.compile(r"\bimport\s+argparse\b|\bfrom\s+argparse\s+import\b"),
        message="Use `typer` instead of argparse",
    ),
    AntiPattern(
        pattern=re.compile(r"\brich\.progress\b|\bfrom\s+rich\.progress\s+import\b"),
        message="Use `tqdm` instead of rich progress bars",
    ),
    AntiPattern(
        pattern=re.compile(r"\bos\.path\b"),
        message="Use pathlib.Path instead of os.path",
    ),
    AntiPattern(
        pattern=re.compile(r"(?<![.\w])(?:eval|exec)\s*\("),
        message="Never use eval()/exec() — parse the data (ast.literal_eval for "
        "literals) or dispatch explicitly",
    ),
    AntiPattern(
        pattern=re.compile(r"\butcnow\s*\("),
        message="datetime.utcnow() is naive and deprecated — use datetime.now(timezone.utc)",
    ),
    AntiPattern(
        pattern=re.compile(r"^global\s+\w"),
        message="No `global` statements — mutate a module-level holder object or pass "
        "state explicitly",
    ),
    AntiPattern(
        pattern=re.compile(r"\bdef\s+_[a-zA-Z]"),
        message="No `_` prefix on functions/methods — nothing is private (nest inside caller if needed)",
    ),
    AntiPattern(
        pattern=re.compile(r"\bclass\s+_[A-Z]"),
        message="No `_` prefix on classes — nothing is private",
    ),
    AntiPattern(
        pattern=re.compile(r"^_[a-zA-Z]\w*\s*(?::[^=]*)?=(?!=)(?!.*,\s*$)"),
        message="No `_` prefix on variables/constants — nothing is private "
        "(unused `_` function parameters are exempt)",
    ),
]
"""Anti-patterns checked against added lines of `.py` files (mirrors the hook)."""


TS_ANTI_PATTERNS: list[AntiPattern] = [
    AntiPattern(
        pattern=re.compile(r"\bas\s+any\b"),
        message="Never use `as any` — use proper types or type guards",
    ),
    AntiPattern(
        pattern=re.compile(r"\bas\s+unknown\b"),
        message="Never use `as unknown` — use type guards or proper types",
    ),
    AntiPattern(
        pattern=re.compile(r":\s*any\b"),
        message="Never use `any` type annotation — use specific types, generics, or `unknown`",
    ),
    AntiPattern(
        pattern=re.compile(r"<any>"),
        message="Never use `<any>` type assertion — use proper types",
    ),
    AntiPattern(
        pattern=re.compile(r"@ts-ignore"),
        message="Never use @ts-ignore — fix the type error properly",
    ),
    AntiPattern(
        pattern=re.compile(r"@ts-expect-error"),
        message="Never use @ts-expect-error — fix the type error properly",
    ),
    AntiPattern(
        pattern=re.compile(r"@ts-nocheck"),
        message="Never use @ts-nocheck — fix the type errors in the file",
    ),
    AntiPattern(
        pattern=re.compile(r"//\s*eslint-disable"),
        message="Never use eslint-disable — fix the lint issue properly",
    ),
    AntiPattern(
        pattern=re.compile(r"/\*\s*eslint-disable"),
        message="Never use eslint-disable — fix the lint issue properly",
    ),
    AntiPattern(
        pattern=re.compile(r"//\s*tslint:disable"),
        message="Never use tslint:disable — migrate to eslint and fix the issue",
    ),
    AntiPattern(
        pattern=re.compile(r"[\w\)\]]!\."),
        message="Postfix `!.` non-null assertion hides a possible null/undefined — "
        "narrow the type or handle the missing case",
    ),
    AntiPattern(
        pattern=re.compile(r"\bvar\s+[A-Za-z_$]"),
        message="Use `const` or `let` instead of `var` — var is function-scoped and hoisted",
    ),
    AntiPattern(
        pattern=re.compile(r":\s*(?:Function|Object)\b"),
        message="Never use `Function` or `Object` as a type — declare the call "
        "signature or the object shape",
    ),
    AntiPattern(
        pattern=re.compile(r"\bconsole\.log\s*\("),
        message="console.log is a debug leftover — remove it or route through a logger",
    ),
]
"""Anti-patterns checked against added lines of TypeScript/JavaScript files."""


PY_SUFFIXES = (".py", ".pyi")
TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte")


def patterns_for_suffix(suffix: str) -> list[AntiPattern] | None:
    """The anti-pattern table that applies to a file suffix, or None to skip it.

    Mirrors the hook's split: Python files are checked against the Python
    table, TS/JS-family files against the TS table, and any other suffix is
    not scanned (the hook only gates those two families).
    """
    if suffix in PY_SUFFIXES:
        return PYTHON_ANTI_PATTERNS
    if suffix in TS_SUFFIXES:
        return TS_ANTI_PATTERNS
    return None


def line_matches(line: str, patterns: list[AntiPattern]) -> list[str]:
    """Messages for every anti-pattern a single line trips, skipping comments.

    A blank line or a pure comment that is not a `# type:` directive is code
    the hook never scans, so it never matches — keeping the auditor's verdict
    aligned with what the hook would have allowed.
    """
    stripped = line.strip()
    if not stripped:
        return []
    if stripped.startswith("#") and "type:" not in stripped:
        return []
    return [ap.message for ap in patterns if ap.pattern.search(stripped)]


class AntiPatternFinding(BaseModel):
    """One auditor result: a line that should carry a marker, or one that shouldn't.

    `kind` is "missing" when the line trips an anti-pattern with no inline
    `# lup: ignore` guarding it, or "spurious" when an inline ignore guards
    a line that trips nothing (a dead marker to delete). `line` is 1-based.
    """

    kind: str
    line: int
    text: str
    message: str


def audit_text(text: str, patterns: list[AntiPattern]) -> list[AntiPatternFinding]:
    """Audit one file's current text for missing and spurious ignore markers.

    A file-level `# lup: ignore` opts the whole file out (matching the
    hook), so it yields no findings. Otherwise each line is checked against
    *patterns*: an unguarded match is a "missing" finding, and an inline
    ignore on a line that matches nothing is a "spurious" finding.

    An ignore counts as a guard only where a comment actually starts (per
    the tokenizer), so a docstring or string literal that merely *mentions*
    `# lup: ignore` — and a note whose prose quotes it — guards nothing.
    Text that does not tokenize as Python falls back to a plain substring
    check.
    """
    if has_file_level_ignore(text):
        return []

    context = PythonContext.parse(text)

    def inline_ignore(line_no: int, line: str) -> bool:
        match = IGNORE_RE.search(line)
        if match is None:
            return False
        return context.comment_at(line_no, match.start())

    findings: list[AntiPatternFinding] = []
    for index, line in enumerate(text.splitlines(), start=1):
        guarded = inline_ignore(index, line)
        hits = line_matches(line, patterns)
        if hits and not guarded:
            findings.append(
                AntiPatternFinding(
                    kind="missing",
                    line=index,
                    text=line.strip()[:80],
                    message=hits[0],
                )
            )
        elif guarded and not hits:
            findings.append(
                AntiPatternFinding(
                    kind="spurious",
                    line=index,
                    text=line.strip()[:80],
                    message="`# lup: ignore` guards a line that matches no anti-pattern — remove it",
                )
            )
    return findings
