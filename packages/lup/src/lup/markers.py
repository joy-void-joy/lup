# lup: ignore
"""Inline marker scanning for the repo's two marker families.

- Review notes (`# lup:` / `// lup:`): actionable feedback left in the code;
  the `ignore` keyword — inline or standalone file-level — is the
  anti-pattern escape hatch, never a note and never a reason to hide one. The
  `lup-devtools dev comments` scanner uses this to list unresolved feedback;
  the edit-permission hook mirrors `MARKER_RE` to prompt whenever an edit
  adds or removes a marker.
- Customization todos (`# TEMPLATE:` in comments, bare `TEMPLATE:` in
  docstrings): the template's domain decision points, gathered by
  `lup-devtools dev todos` so `/lup:init` walks every one.

Both families share one scan (:func:`find_markers`, parameterized over the
marker regex); :func:`find_feedback` binds it to the review-note rules.

Detection is deliberately liberal — `#` or `//`, any case, optional spaces — so
the same note reads naturally in Python, shell, TypeScript, JSON, or Markdown.
A colon is required so prose like a `## Claude` heading does not match. A marker
is a feedback note unless its keyword is `ignore`, which stays the anti-pattern
escape hatch.

How a file is scanned depends on its language, because where a note can live
does. Python source is parsed so a marker counts only where prose belongs — in a
comment or a docstring. A ``# lup:`` inside an ordinary string literal (such
as a tool's own "no notes" message) is code, not a note, and must not be
reported. Other text has no Python parser to lean on, so it is line-scanned;
Markdown additionally skips fenced and inline code so notes quoted in
documentation examples are not flagged.
"""

import ast
import re
import tokenize
from io import StringIO
from pathlib import Path

from pydantic import BaseModel

# lup: This feels like a duplicate of antipattern? Probably both files should be in a common folder (like markers/ or something) and dedup the commonalities
MARKER_RE = re.compile(r"(#|//)\s*lup\s*:", re.IGNORECASE)
# An `ignore` directive is bare (`# lup: ignore`, silences every rule) or typed
# pyright-style (`# lup: ignore[rule-id, other-rule]`, silences only the named
# rules). The optional `ids` group captures the comma-separated list when typed.
IGNORE_RE = re.compile(
    r"(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?", re.IGNORECASE
)
FILE_IGNORE_RE = re.compile(
    r"^\s*(#|//)\s*lup\s*:\s*ignore\b(?:\s*\[(?P<ids>[^\]]*)\])?\s*$", re.IGNORECASE
)
# Customization todos are shouty and case-sensitive (like TODO:/FIXME:), so
# prose about "the template" never matches. The comment prefix is optional
# because a docstring todo carries no `#`; group 1 still captures the
# introducer when present, as the scan expects.
TEMPLATE_MARKER_RE = re.compile(r"(?:(#|//)\s*)?TEMPLATE\s*:")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
COMMENT_PREFIX_RE = re.compile(r"^\s*(#|//)")

PYTHON_SUFFIXES = {".py", ".pyi"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}
# Languages where `#` does not open a comment (`//` does), so a `# lup:` is
# always string content (e.g. a Python marker quoted inside a JS template) —
# only `//` markers count as notes there.
JS_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

CONTEXT_BEFORE = 2
CONTEXT_AFTER = 25


class ScanMode:
    """How a file's text is searched for markers, chosen by its language."""

    PYTHON = "python"
    MARKDOWN = "markdown"
    JS = "js"
    TEXT = "text"


def scan_mode_for(path: Path) -> str:
    """Pick the scan mode for a path from its suffix.

    The single source of truth for routing each tracked file: Python source is
    parsed (comments and docstrings only), Markdown is line-scanned with code
    skipped, everything else is plain line-scanned.
    """
    suffix = path.suffix.lower()
    if suffix in PYTHON_SUFFIXES:  # lup: Should be a match
        return ScanMode.PYTHON
    if suffix in MARKDOWN_SUFFIXES:
        return ScanMode.MARKDOWN
    if suffix in JS_SUFFIXES:
        return ScanMode.JS
    return ScanMode.TEXT


class MarkerComment(BaseModel):
    """One actionable note: the source span plus a window worth reading."""

    start_line: int
    end_line: int
    read_start: int
    read_end: int
    text: str


def marker_count(text: str) -> int:
    """Count markers (feedback or ignore) — drives the hook's add/remove check."""
    return len(MARKER_RE.findall(text))


def ignore_rule_ids(match: re.Match[str]) -> set[str] | None:
    """Rule ids a matched `IGNORE_RE`/`FILE_IGNORE_RE` directive names.

    ``None`` is the bare, untyped `# lup: ignore` that silences every rule; a
    set names exactly the rules a typed `# lup: ignore[a, b]` silences (empty
    brackets yield an empty set — a typed directive that names nothing).
    """
    raw = match.group("ids")
    if raw is None:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


class FileIgnore(BaseModel):
    """A file-level `# lup: ignore` near a file's top and what it disables.

    ``rule_ids`` is ``None`` for a bare `# lup: ignore` that disables every
    rule for the whole file; a set names the rules a typed
    `# lup: ignore[rule-id]` disables file-wide. ``line`` is 1-based.
    """

    line: int
    rule_ids: set[str] | None


def file_level_ignore(text: str, max_lines: int = 10) -> FileIgnore | None:
    """The file-level `# lup: ignore` in the first `max_lines`, or ``None``.

    A standalone bare `# lup: ignore` opts the whole file out of anti-pattern
    checks; the typed `# lup: ignore[rule-id]` form opts out only the named
    rules. Feedback-note scanning never consults this — an opted-out file still
    surfaces its `# lup:` notes.
    """
    for i, line in enumerate(text.splitlines()):
        if i >= max_lines:
            break
        match = FILE_IGNORE_RE.match(line)
        if match is not None:
            return FileIgnore(line=i + 1, rule_ids=ignore_rule_ids(match))
    return None


def inside_inline_code(line: str, pos: int) -> bool:
    """Whether character `pos` falls inside a backtick code span (a doc example).

    Odd single-backtick parity catches a marker mid-span; a backtick run
    directly before the marker catches rst-style double-backtick quoting,
    whose even-length run defeats the parity check.
    """
    prefix = line[:pos]
    return prefix.count("`") % 2 == 1 or prefix.endswith("`")


def python_comment_columns(text: str) -> dict[int, int] | None:
    """Map each 1-based line to the column where its real `#` comment starts.

    Tokenizing tells apart a `#` that opens a comment from one inside a string
    literal, so the scanner can reject markers that are actually code. Returns
    ``None`` when the source cannot be tokenized (a syntax error in some tracked
    file), signalling the caller to fall back to line scanning rather than miss
    a note.
    """
    columns: dict[int, int] = {}
    try:
        for token in tokenize.generate_tokens(StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                line_no, col = token.start
                columns[line_no] = col
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return columns


def python_docstring_lines(text: str) -> set[int]:
    """Lines (1-based) covered by a module, class, or function docstring.

    Docstrings are the one string literal where prose — and so a real note —
    belongs, unlike an ordinary string such as an echoed message. Returns an
    empty set when the source cannot be parsed; the comment scan still runs.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()

    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
        ):
            lines.update(range(first.lineno, first.end_lineno + 1))
    return lines


def find_markers(
    text: str,
    mode: str = ScanMode.TEXT,
    *,
    marker: re.Pattern[str],
    ignore: re.Pattern[str] | None = None,
) -> list[MarkerComment]:  # lup: Yeah, this feels very duplicated from antipatterns.py
    """Extract one marker family's notes from a file's text under a `ScanMode`.

    A note is a marker line plus the contiguous same-style comment lines below
    it, merged into one item; a decoration line (no letters or digits, e.g. the
    edge of a `# ====` banner) ends the note. Lines whose marker also matches
    `ignore`, fenced code, and backtick spans are skipped. In Python mode a
    marker counts only inside a comment or docstring, so marker text in an
    ordinary string literal is left alone.
    """
    is_python = mode == ScanMode.PYTHON
    is_markdown = mode == ScanMode.MARKDOWN
    comment_columns = python_comment_columns(text) if is_python else None
    docstring_lines = python_docstring_lines(text) if is_python else set()

    def in_note_context(line_no: int, col: int) -> bool:
        if comment_columns is None:
            return True
        return comment_columns.get(line_no) == col or line_no in docstring_lines

    lines = text.splitlines()
    total = len(lines)
    found: list[MarkerComment] = []
    in_fence = False
    i = 0

    # lup: Why do it this way? This seems a bit ugly
    while i < total:
        line = lines[i]

        if is_markdown and FENCE_RE.match(line):
            in_fence = not in_fence
            i += 1
            continue

        match = marker.search(line)
        if (
            match is None
            or in_fence
            or (ignore is not None and ignore.match(line, match.start()) is not None)
            or (mode == ScanMode.JS and match.group(1) == "#")
            or inside_inline_code(line, match.start())
            or not in_note_context(i + 1, match.start())
        ):
            i += 1
            continue

        parts = [line[match.end() :].strip()]
        end = i

        if not is_markdown and line[: match.start()].strip() == "":
            intro = match.group(1)
            j = i + 1
            while j < total:
                prefix = COMMENT_PREFIX_RE.match(lines[j])
                if prefix is None or prefix.group(1) != intro:
                    break
                if not in_note_context(j + 1, prefix.start(1)):
                    break
                if marker.search(lines[j]) is not None:
                    break
                content = lines[j][prefix.end() :].strip()
                if content and not any(ch.isalnum() for ch in content):
                    break
                parts.append(content)
                j += 1
            end = j - 1

        start_line = i + 1
        end_line = end + 1
        found.append(
            MarkerComment(
                start_line=start_line,
                end_line=end_line,
                read_start=max(1, start_line - CONTEXT_BEFORE),
                read_end=min(total, end_line + CONTEXT_AFTER),
                text=" ".join(part for part in parts if part),
            )
        )
        i = end + 1

    return found


def find_feedback(text: str, mode: str = ScanMode.TEXT) -> list[MarkerComment]:
    """Extract `# lup:` review notes from a file's text.

    Binds :func:`find_markers` to the review-note rules: `ignore` directives
    are skipped — they are the anti-pattern escape hatch, not feedback. That
    covers the standalone file-level `# lup: ignore` too: it disables
    anti-pattern checks (see `lup.antipatterns`), never note gathering, so
    feedback in an opted-out file still surfaces.
    """
    return find_markers(text, mode, marker=MARKER_RE, ignore=IGNORE_RE)
