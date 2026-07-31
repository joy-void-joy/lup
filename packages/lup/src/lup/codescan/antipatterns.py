# lup: ignore[empty-collection, import-re, re-call, set-shape]
"""Single importable source of truth for the codebase's anti-pattern set.

The generated hermetic edit policy denies an edit whose added lines match one
of these patterns unless the line carries a `# lup: ignore`. Harness generation
projects these rows into its dependency-free runtime; a test asserts that
projection stays identical, and the `lup-devtools dev check --antipatterns`
auditor consumes them to scan the whole tree after the fact (catching lines that slipped in past the hook and
`# lup: ignore` markers that no longer guard anything).

Each rule carries a stable kebab-case ``id``. A directive names rules
pyright-style — `# lup: ignore[dict-get]` silences only ``dict-get`` on that
line, `# lup: ignore[a, b]` a list — so one open site opts out of one rule
without blinding the others. The bare `# lup: ignore` stays valid (it silences
every rule) but the auditor surfaces it as "untyped" so the migration to typed
directives is gradual.

The set is a syntax-aware linter pass, not a raw grep: every rule declares the
syntactic ``context`` it inspects, and Python source is tokenized once (via
`lup.codescan.common.LineProjections`) so "code" rules scan lines with string
literals and comments blanked while "comment" directive rules see comments
intact. The detectors themselves stay regexes because that is the primitive
form the hermetic hook runtime can carry (ruff has no plugin API, and engines
that do — flake8, pylint, semgrep — could not run inside the hook); AST
refiners such as `empty_collection_exempt_lines` sharpen individual rules, and
regex alone remains only where a rule is genuinely text-shaped. The
`lup.codescan.registry` index and the generated `docs/rules.md` reference list
this family beside the boundary, spelling, and architecture rules.

Each entry pairs a stable id and a compiled regex with the message the hook and
auditor show. This module imports only the standard library and `pydantic`
(directly and through `lup.codescan.common`) so the auditor can load it cheaply;
`# lup:` marker detection stays in `lup.codescan.markers`, and the shared scan
core — ignore matching, comment-column tokenization, the masked line
projections, the line cursor — in `lup.codescan.common`, which this set's
consumers and the auditor import directly.
"""

import re

from pydantic import BaseModel

from lup.codescan.boundaries import (
    LIBRARY_DEFAULT_RULE_ID,
    NATIVE_SPELLING_RULE_ID,
    RULE_ID as SEAM_BOUNDARY_RULE_ID,
)
from lup.codescan.capabilities import RULE_ID as ABC_CAPABILITY_RULE_ID
from lup.codescan.common import (
    IGNORE_RE,
    LineProjections,
    PythonContext,
    RuleContext,
    file_level_ignore,
    ignore_rule_ids,
)
from lup.policy.kernel.edit import empty_collection_exempt_lines


class AntiPattern(BaseModel):
    """One forbidden code shape: a stable id, the regex that detects it, and why.

    ``id`` is a stable kebab-case name a typed `# lup: ignore[id]` directive
    targets, so a single site can silence exactly one rule without opting out
    of the rest. Ids are pinned alongside the pattern and message by
    ``tests/unit/test_antipatterns.py`` and must stay in step with the hook.

    ``context`` declares the syntactic surface the pattern inspects. A "code"
    rule is matched against token-masked source — string literals and comments
    both blanked — so an identifier quoted in prose never trips it; a
    "comment" rule targets comment directives (`# type: ignore`, `# noqa`) and
    is matched with comments intact. Where no tokenizer applies (the
    TypeScript-family table, text that fails to tokenize) every rule scans the
    raw line — those rules are genuinely text-shaped.
    """

    model_config = {"arbitrary_types_allowed": True}

    id: str
    pattern: re.Pattern[str]
    message: str
    context: RuleContext = "code"


PYTHON_ANTI_PATTERNS: list[AntiPattern] = [
    AntiPattern(
        id="any-type",
        pattern=re.compile(r"\bAny\b"),
        message="Never use Any — use specific types, TypedDict, or BaseModel",
    ),
    AntiPattern(
        id="type-ignore",
        pattern=re.compile(r"#\s*type:\s*ignore"),
        message="Never use # type: ignore — fix the type error properly",
        context="comment",
    ),
    AntiPattern(
        id="pyright-ignore",
        pattern=re.compile(r"#\s*pyright:\s*ignore"),
        message="Never use # pyright: ignore — fix the type error properly",
        context="comment",
    ),
    AntiPattern(
        id="noqa",
        pattern=re.compile(r"#\s*noqa\b"),
        message="Never use # noqa — fix the lint issue properly",
        context="comment",
    ),
    AntiPattern(
        id="generic-base",
        pattern=re.compile(r"\bGeneric\["),
        message="Use Python 3.12+ class[T] syntax instead of Generic[T]",
    ),
    AntiPattern(
        id="typing-union",
        pattern=re.compile(r"\b(?:Optional|Union)\["),
        message="Use PEP 604 unions — X | None instead of Optional, X | Y instead of Union",
    ),
    AntiPattern(
        id="typing-generics",
        pattern=re.compile(r"\b(?:List|Dict|Tuple|Set)\["),
        message="Use lowercase builtin generics — list, dict, tuple, set — "
        "instead of the capitalized typing aliases",
    ),
    AntiPattern(
        id="all-export",
        pattern=re.compile(r"__all__\s*[=:]"),
        message="No __all__ — import directly from the defining module",
    ),
    AntiPattern(
        id="dict-str-object",
        pattern=re.compile(r"\b(?:dict|Mapping)\[\s*str\s*,\s*object\s*\]"),
        message="Never use dict[str, object] or Mapping[str, object] — use TypedDict or BaseModel",
    ),
    AntiPattern(
        # Flags a string-keyed dict/Mapping only when the VALUE is a scalar/
        # payload type (str, int, float, bool, bytes, complex, or a union that
        # opens with one). Concrete class and callable value types are left
        # alone: `dict[str, SessionFactory]`, `dict[str, LupMcpTool]`, `dict[str,
        # Callable[...]]` are registries/routers whose open, data-driven key
        # set IS the point. The smell is a CLOSED, enumerable key set with a
        # scalar value (config-shaped) — that wants a BaseModel or
        # dict[Literal[...], V]; JsonValue stays the escape for arbitrary JSON.
        id="dict-str-payload",
        pattern=re.compile(
            r"\b(?:dict|Mapping|MutableMapping)\[\s*str\s*,"
            r"\s*(?:str|int|float|bool|bytes|complex)\b"
        ),
        message="String-keyed dict with a scalar value hides shape when the keys are a "
        "CLOSED, enumerable set — use a BaseModel or dict[Literal[...], V]. When the keys "
        "are open and data-driven (a registry/cache/counter keyed by external data) this is "
        "legitimate: add `# lup: ignore[dict-str-payload]`. Concrete class/callable value "
        "types (dict[str, SessionFactory]) are already accepted; JsonValue covers arbitrary JSON",
    ),
    AntiPattern(
        # Flags every `.get(` — the user's explicit broad choice over a narrow
        # rule. On payload/TypedDict-shaped data use typed attribute access; on
        # a genuinely open dict (a registry or cache) it is one comment.
        # lup: refute whole-file dict-get findings by receiver type — ask
        # pyright (textDocument/definition on the matched attribute) whether it
        # resolves into the mapping family's stubs, and drop confirmed
        # non-mapping sites (HTTP clients, route decorators). Audit-side only;
        # the hook kernel keeps this broad line rule because edit fragments
        # have no types.
        id="dict-get",
        pattern=re.compile(r"\.get\s*\("),
        message="`.get(` on payload/TypedDict-shaped data hides the schema — use typed "
        "attribute access (BaseModel/TypedDict). On a genuinely open dict (registry, cache) "
        "add `# lup: ignore[dict-get]`",
    ),
    AntiPattern(
        id="bare-object",
        pattern=re.compile(r"(?:(?<!\w)(?!_)\w+\s*:|->)\s*object\b"),
        message="Bare `object` says nothing about the value — use a concrete type, "
        "TypedDict, or BaseModel, and narrow at untyped boundaries",
    ),
    AntiPattern(
        id="bare-basemodel",
        pattern=re.compile(r"(?:(?<!\[)\b\w+\s*:|->)\s*BaseModel\b(?!\s*[\]|])"),
        message="A parameter or return annotated exactly BaseModel accepts any model — "
        "name the concrete union of models or make the function generic",
    ),
    AntiPattern(
        id="tuple-shape",
        pattern=re.compile(r"\btuple\["),
        message="A declared `tuple[...]` shape hides what each position means — name the "
        "fields with a TypedDict or BaseModel, a `type Alias = ...` for a reused shape, or "
        "`list` for a variable-length sequence",
    ),
    AntiPattern(
        # Mirrors tuple-shape for frozenset: every declared frozenset annotation
        # or constructed constant. A fixed name set constant wants a dict or a
        # purpose-built structure; an immutable-default-argument use is the one
        # legitimate site — `# lup: ignore[frozenset-shape]` marks it.
        id="frozenset-shape",
        pattern=re.compile(r"\bfrozenset\b"),
        message="A declared `frozenset[...]` shape or constant is usually overkill — use "
        "a dict or a purpose-built structure. For a genuinely immutable default argument "
        "add `# lup: ignore[frozenset-shape]`",
    ),
    AntiPattern(
        # A declared or constructed set — `set(...)`/`set[...]` (no space
        # before the bracket; ruff never formats one in) or a `: set`/`-> set`
        # annotation. The dot lookbehind keeps `.set()` method calls out, and
        # prose about "set" never carries the bracket or annotation shape.
        # `frozenset` is caught by frozenset-shape and never trips this, since
        # its "set" is not a standalone word.
        id="set-shape",
        pattern=re.compile(r"(?<!\.)\bset[\[(]|(?::|->)\s*set\b"),
        message="A declared `set` is usually better as a dict (keyed lookup) or a "
        "purpose-built structure. For a genuinely set-shaped value add "
        "`# lup: ignore[set-shape]`",
    ),
    AntiPattern(
        # Broad regex trigger, refined by the AST: empty_collection_exempt_lines
        # exempts deliberate defaults (__init__ state, call kwargs, annotated
        # class fields), so what reaches a verdict is the build-then-append
        # seed. The lookbehind keeps `==`/`!=`/`<=`/`>=` comparisons out.
        id="empty-collection",
        pattern=re.compile(r"(?<![=!<>])=\s*(?:\{\}|\[\]|set\(\))"),
        message="Empty-collection literals (`= {}`, `= []`, `= set()`) usually seed an "
        "append/mutate loop — build the collection with a comprehension instead, or add "
        "`# lup: ignore[empty-collection]` for a fold no comprehension can express",
    ),
    AntiPattern(
        id="cast",
        pattern=re.compile(r"\bcast\s*\("),
        message="`cast(...)` is a code smell — narrow with isinstance or a type guard, "
        "or fix the annotation so the cast is unnecessary",
    ),
    AntiPattern(
        id="import-re",
        pattern=re.compile(r"\bimport\s+re\b|\bfrom\s+re\s+import\b"),
        message="`import re` / `from re import` is a code smell — parse structured data with "
        "its own API instead: JSON -> json.loads, paths -> pathlib.Path, URLs -> urllib.parse, "
        "XML/HTML -> xml.etree.ElementTree / lxml, dates -> datetime",
    ),
    AntiPattern(
        id="re-call",
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
        # codebase's path-named receivers out of the net. os.replace as an atomic
        # rename is steered toward pathlib by os-file-ops instead, so the two
        # rules stay coherent: this one is only about string surgery.
        id="string-replace",
        pattern=re.compile(r"(?<!\bos)(?<![Pp]ath)\.replace\s*\("),
        message="Avoid .replace() for structured data — edit it through its parser instead "
        "(pathlib.Path for paths, urllib.parse for URLs, json for JSON)",
    ),
    AntiPattern(
        # Only separator-form `.split(sep)` is flagged — `.rsplit` and
        # `.partition`/`.rpartition` included, so the variants are not a dodge
        # (partition always takes a separator, so it always trips). A separator
        # implies structure with a real parser alternative (csv, pathlib,
        # urllib, json, datetime). Argument-less `.split()` is whitespace
        # tokenization of free text, for which no parser exists — the negative
        # lookahead exempts it.
        id="string-split",
        pattern=re.compile(r"\.r?split\s*\((?!\s*\))|\.r?partition\s*\("),
        message="Avoid .split(sep)/.rsplit/.partition for structured data — parse it "
        "instead (urllib.parse for URLs, pathlib.Path for paths, json for JSON, "
        "datetime for dates)",
    ),
    AntiPattern(
        # Only separator-form `.strip(chars)` is flagged — `.lstrip`/`.rstrip`
        # included, so the variants are not a dodge. Naming the characters to
        # strip implies field extraction from structured text; argless
        # stripping is whitespace framing, for which no parser exists — the
        # negative lookahead exempts it, mirroring string-split's argless rule.
        id="string-strip",
        pattern=re.compile(r"\.[lr]?strip\s*\((?!\s*\))"),
        message="Avoid .strip(chars)/.lstrip/.rstrip for structured data — parse it "
        "instead (urllib.parse for URLs, pathlib.Path for paths, json for JSON, "
        "datetime for dates)",
    ),
    AntiPattern(
        id="bare-except",
        pattern=re.compile(r"\bexcept\s*:"),
        message="Bare `except:` catches SystemExit/KeyboardInterrupt — name the exception",
    ),
    AntiPattern(
        id="except-baseexception",
        pattern=re.compile(r"\bexcept\s+BaseException\b"),
        message="except BaseException catches KeyboardInterrupt — use Exception or narrower",
    ),
    AntiPattern(
        id="suppress",
        pattern=re.compile(r"\bcontextlib\.suppress\b"),
        message="contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    AntiPattern(
        id="suppress-import",
        pattern=re.compile(r"\bfrom\s+contextlib\s+import\b.*\bsuppress\b"),
        message="contextlib.suppress silently swallows exceptions — log, handle, or re-raise",
    ),
    AntiPattern(
        id="dataclass",
        pattern=re.compile(
            r"@dataclass|\bimport\s+dataclasses\b|\bfrom\s+dataclasses\s+import\b"
        ),
        message="Use Pydantic BaseModel (or TypedDict) instead of dataclasses",
    ),
    AntiPattern(
        # Same dodge as dataclass: a typed record that ducks pydantic
        # validation. Catches the typing.NamedTuple class form and the
        # collections.namedtuple factory alike.
        id="namedtuple",
        pattern=re.compile(r"\bNamedTuple\b|\bnamedtuple\b"),
        message="Use Pydantic BaseModel (or TypedDict) instead of NamedTuple/namedtuple",
    ),
    AntiPattern(
        id="subprocess",
        pattern=re.compile(r"\bimport\s+subprocess\b|\bfrom\s+subprocess\s+import\b"),
        message="Use the `sh` library instead of subprocess",
    ),
    AntiPattern(
        id="os-shell",
        pattern=re.compile(r"\bos\.(?:system|popen|exec[lv]\w*)\s*\("),
        message="Use the `sh` library instead of os.system()/os.popen()/os.exec*()",
    ),
    AntiPattern(
        id="argparse",
        pattern=re.compile(r"\bimport\s+argparse\b|\bfrom\s+argparse\s+import\b"),
        message="Use `typer` instead of argparse",
    ),
    AntiPattern(
        id="rich-progress",
        pattern=re.compile(r"\brich\.progress\b|\bfrom\s+rich\.progress\s+import\b"),
        message="Use `tqdm` instead of rich progress bars",
    ),
    AntiPattern(
        id="os-path",
        pattern=re.compile(r"\bos\.path\b"),
        message="Use pathlib.Path instead of os.path",
    ),
    AntiPattern(
        # A scoped list of os file/dir operations that all have a pathlib.Path
        # equivalent (iterdir, mkdir, unlink, rename, replace, stat, ...).
        # Config access (os.environ/os.getenv) and process launching (os.system/
        # os.exec*/os.popen) are covered by os-environ and os-shell instead.
        id="os-file-ops",
        pattern=re.compile(
            r"\bos\.(?:getcwd|chdir|listdir|scandir|walk|mkdir|makedirs|rmdir|"
            r"removedirs|remove|unlink|rename|renames|replace|link|symlink|"
            r"readlink|stat|lstat|chmod|chown)\s*\("
        ),
        message="Use pathlib.Path for file/dir operations instead of os.* "
        "(Path.iterdir/mkdir/unlink/rename/replace/stat/...)",
    ),
    AntiPattern(
        id="os-environ",
        pattern=re.compile(r"\bos\.(?:environ|getenv)\b"),
        message="Read configuration through pydantic-settings, not os.environ/os.getenv",
    ),
    AntiPattern(
        id="eval-exec",
        pattern=re.compile(r"(?<![.\w])(?:eval|exec)\s*\("),
        message="Never use eval()/exec() — parse the data (ast.literal_eval for "
        "literals) or dispatch explicitly",
    ),
    AntiPattern(
        id="utcnow",
        pattern=re.compile(r"\butcnow\s*\("),
        message="datetime.utcnow() is naive and deprecated — use datetime.now(timezone.utc)",
    ),
    AntiPattern(
        id="global-statement",
        pattern=re.compile(r"^global\s+\w"),
        message="No `global` statements — mutate a module-level holder object or pass "
        "state explicitly",
    ),
    AntiPattern(
        id="private-function",
        pattern=re.compile(r"\bdef\s+_[a-zA-Z]"),
        message="No `_` prefix on functions/methods — nothing is private (nest inside caller if needed)",
    ),
    AntiPattern(
        id="private-class",
        pattern=re.compile(r"\bclass\s+_[A-Z]"),
        message="No `_` prefix on classes — nothing is private",
    ),
    AntiPattern(
        id="private-variable",
        pattern=re.compile(r"^_[a-zA-Z]\w*\s*(?::[^=]*)?=(?!=)(?!.*,\s*$)"),
        message="No `_` prefix on variables/constants — nothing is private "
        "(unused `_` function parameters are exempt)",
    ),
]
"""Anti-patterns checked against added lines of `.py` files (mirrors the hook)."""


TS_ANTI_PATTERNS: list[AntiPattern] = [
    AntiPattern(
        id="as-any",
        pattern=re.compile(r"\bas\s+any\b"),
        message="Never use `as any` — use proper types or type guards",
    ),
    AntiPattern(
        id="as-unknown",
        pattern=re.compile(r"\bas\s+unknown\b"),
        message="Never use `as unknown` — use type guards or proper types",
    ),
    AntiPattern(
        id="any-annotation",
        pattern=re.compile(r":\s*any\b"),
        message="Never use `any` type annotation — use specific types, generics, or `unknown`",
    ),
    AntiPattern(
        id="any-assertion",
        pattern=re.compile(r"<any>"),
        message="Never use `<any>` type assertion — use proper types",
    ),
    AntiPattern(
        id="ts-ignore",
        pattern=re.compile(r"@ts-ignore"),
        message="Never use @ts-ignore — fix the type error properly",
        context="comment",
    ),
    AntiPattern(
        id="ts-expect-error",
        pattern=re.compile(r"@ts-expect-error"),
        message="Never use @ts-expect-error — fix the type error properly",
        context="comment",
    ),
    AntiPattern(
        id="ts-nocheck",
        pattern=re.compile(r"@ts-nocheck"),
        message="Never use @ts-nocheck — fix the type errors in the file",
        context="comment",
    ),
    AntiPattern(
        id="eslint-disable",
        pattern=re.compile(r"//\s*eslint-disable"),
        message="Never use eslint-disable — fix the lint issue properly",
        context="comment",
    ),
    AntiPattern(
        id="eslint-disable-block",
        pattern=re.compile(r"/\*\s*eslint-disable"),
        message="Never use eslint-disable — fix the lint issue properly",
        context="comment",
    ),
    AntiPattern(
        id="tslint-disable",
        pattern=re.compile(r"//\s*tslint:disable"),
        message="Never use tslint:disable — migrate to eslint and fix the issue",
        context="comment",
    ),
    AntiPattern(
        id="non-null-assertion",
        pattern=re.compile(r"[\w\)\]]!\."),
        message="Postfix `!.` non-null assertion hides a possible null/undefined — "
        "narrow the type or handle the missing case",
    ),
    AntiPattern(
        id="var-declaration",
        pattern=re.compile(r"\bvar\s+[A-Za-z_$]"),
        message="Use `const` or `let` instead of `var` — var is function-scoped and hoisted",
    ),
    AntiPattern(
        id="function-object-type",
        pattern=re.compile(r":\s*(?:Function|Object)\b"),
        message="Never use `Function` or `Object` as a type — declare the call "
        "signature or the object shape",
    ),
    AntiPattern(
        id="console-log",
        pattern=re.compile(r"\bconsole\.log\s*\("),
        message="console.log is a debug leftover — remove it or route through a logger",
    ),
]
"""Anti-patterns checked against added lines of TypeScript/JavaScript files."""


# lup: ignore[library-default] — Python's own source suffixes
PY_SUFFIXES = (".py", ".pyi")
# lup: ignore[library-default] — the suffixes those ecosystems compile
TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte")

FOREIGN_RULE_IDS: frozenset[str] = frozenset(  # lup: ignore[frozenset-shape]
    {
        ABC_CAPABILITY_RULE_ID,
        LIBRARY_DEFAULT_RULE_ID,
        NATIVE_SPELLING_RULE_ID,
        SEAM_BOUNDARY_RULE_ID,
    }
)
"""Rule ids owned by other codescan scanners.

A typed ``# lup: ignore[...]`` naming one of these is judged by that
scanner (the boundary scan honors its own id), so this auditor never
reports it spurious — while an id no scanner owns still is.
"""


EMPTY_COLLECTION_RULE_ID = "empty-collection"


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


def line_hits(
    lines: LineProjections, line_no: int, patterns: list[AntiPattern]
) -> list[AntiPattern]:
    """Every anti-pattern one line trips, each matched in its declared context.

    Tokenized Python is scanned per rule context: a "code" rule sees string
    literals and comments blanked, so identifiers in prose never match, while
    a "comment" directive rule sees comments intact — a standalone `# noqa`
    line included. Untokenized text (a non-Python file, a fragment) keeps the
    conservative whole-line scan, skipping blank lines and pure comments that
    carry no `type:` directive — aligned with what the hook would decide.
    """
    if not lines.tokenized:
        raw = lines.commented[line_no - 1].strip()
        if not raw or (raw.startswith("#") and "type:" not in raw):
            return []
        return [ap for ap in patterns if ap.pattern.search(raw)]
    return [
        ap
        for ap in patterns
        if (text := lines.scan_text(line_no, ap.context)) and ap.pattern.search(text)
    ]


class AntiPatternFinding(BaseModel):
    """One auditor result about a single line's anti-pattern guarding.

    ``kind`` is:
    - "missing": the line trips a rule with no `# lup: ignore` covering it.
    - "spurious": a `# lup: ignore[id]` (or a bare one) guards a rule the line
      does not trip — a dead directive to delete.
    - "untyped": a bare `# lup: ignore` validly silences the line but names no
      rule; it stays valid, and is surfaced so migration to typed directives is
      gradual (advisory, not a blocker).

    ``rule_id`` is the rule the finding concerns (empty for a bare marker that
    guards nothing). ``line`` is 1-based.
    """

    kind: str
    line: int
    text: str
    message: str
    rule_id: str = ""


def audit_text(text: str, patterns: list[AntiPattern]) -> list[AntiPatternFinding]:
    """Audit one file's current text for per-rule ignore-marker health.

    A bare file-level `# lup: ignore` opts the whole file out (matching the
    hook); the audit reports it as a single advisory "untyped" finding and
    scans nothing else. A typed file-level `# lup: ignore[id]` opts out only
    the named rule file-wide — and when nothing in the file still needs an
    id (no line trips it that an inline directive would not already cover),
    that id reports "spurious" at the directive line, so refiner and rule
    evolution cannot leave dead file-wide opt-outs behind. Docstring lines are skipped
    entirely: prose is not code, and no inline directive could ever guard it —
    a comment cannot open inside a string. (The hook still scans docstring
    lines at edit time; it sees only text fragments it cannot tokenize, so the
    hook stays strictly stricter than this audit.) Then, per line and per rule:

    - a tripped rule with no covering ignore -> "missing";
    - a typed `# lup: ignore[id]` naming a rule the line does not trip, or a
      bare ignore on a line that trips nothing -> "spurious";
    - a bare `# lup: ignore` that does silence the line -> "untyped".

    An empty-collection hit on a line the AST refiner exempts (see
    :func:`empty_collection_exempt_lines`) is not a trip at all, so a
    directive naming the rule there reports "spurious" — the audit drives
    the cleanup of markers the refiner made unnecessary.

    An ignore counts as a guard only where a comment actually starts (per the
    tokenizer), so a docstring or string literal that merely *mentions*
    `# lup: ignore` — and a note whose prose quotes it — guards nothing. Text
    that does not tokenize as Python falls back to a plain substring check.
    """
    file_ignore = file_level_ignore(text)
    file_disabled: set[str] = set()
    if file_ignore is not None:
        if file_ignore.rule_ids is None:
            return [  # bare file-level opt-out disables every rule — surface it
                AntiPatternFinding(
                    kind="untyped",
                    line=file_ignore.line,
                    text="# lup: ignore",
                    message="bare file-level `# lup: ignore` opts the whole file out of "
                    "every rule — name the rules it needs: `# lup: ignore[rule, ...]`",
                )
            ]
        file_disabled = file_ignore.rule_ids

    context = PythonContext.parse(text)
    refined = any(ap.id == EMPTY_COLLECTION_RULE_ID for ap in patterns)
    exempt = empty_collection_exempt_lines(text) if refined else set()

    def inline_directive(line_no: int, line: str) -> re.Match[str] | None:
        match = IGNORE_RE.search(line)
        if match is None:
            return None
        if not context.comment_at(line_no, match.start()):
            return None
        return match

    file_ignore_line = file_ignore.line if file_ignore is not None else 0
    original_lines = text.splitlines()
    projections = LineProjections.parse(text)

    file_live: set[str] = set()
    findings: list[AntiPatternFinding] = []
    for index, line in enumerate(original_lines, start=1):
        if index == file_ignore_line:
            continue  # the file-level directive line is not itself audited
        if index in context.docstring_lines:
            continue  # docstring prose is not code, and no comment can guard it
        preview = line.strip()[:80]
        hits = line_hits(projections, index, patterns)
        if index in exempt:
            hits = [ap for ap in hits if ap.id != EMPTY_COLLECTION_RULE_ID]
        hit_ids = {ap.id for ap in hits}
        directive = inline_directive(index, line)
        inline_ids = ignore_rule_ids(directive) if directive is not None else None

        silenced_by_bare = False
        for ap in hits:
            if ap.id in file_disabled:
                # Live only when the file-level directive is the sole silencer;
                # an inline-covered hit does not keep the file-wide id alive.
                if directive is None or not (inline_ids is None or ap.id in inline_ids):
                    file_live.add(ap.id)
                continue
            if directive is not None and (inline_ids is None or ap.id in inline_ids):
                silenced_by_bare = silenced_by_bare or inline_ids is None
                continue
            findings.append(
                AntiPatternFinding(
                    kind="missing",
                    line=index,
                    text=preview,
                    message=ap.message,
                    rule_id=ap.id,
                )
            )

        if directive is None:
            continue
        if inline_ids is None:
            if silenced_by_bare:
                covered = sorted(i for i in hit_ids if i not in file_disabled)
                findings.append(
                    AntiPatternFinding(
                        kind="untyped",
                        line=index,
                        text=preview,
                        message="`# lup: ignore` is untyped — name the rule(s) it silences: "
                        f"`# lup: ignore[{', '.join(covered)}]`",
                        rule_id=covered[0] if covered else "",
                    )
                )
            else:
                findings.append(
                    AntiPatternFinding(
                        kind="spurious",
                        line=index,
                        text=preview,
                        message="`# lup: ignore` guards a line that matches no anti-pattern — remove it",
                    )
                )
        else:
            for rid in sorted(inline_ids - hit_ids - FOREIGN_RULE_IDS):
                findings.append(
                    AntiPatternFinding(
                        kind="spurious",
                        line=index,
                        text=preview,
                        message=f"`# lup: ignore[{rid}]` guards a line that does not trip `{rid}` — remove it",
                        rule_id=rid,
                    )
                )

    if file_ignore is not None:
        directive_text = text.splitlines()[file_ignore.line - 1].strip()[:80]
        for rid in sorted(file_disabled - file_live - FOREIGN_RULE_IDS):
            findings.append(
                AntiPatternFinding(
                    kind="spurious",
                    line=file_ignore.line,
                    text=directive_text,
                    message=f"file-level `# lup: ignore[{rid}]` names a rule nothing "
                    "in the file needs — remove it",
                    rule_id=rid,
                )
            )
    return findings
