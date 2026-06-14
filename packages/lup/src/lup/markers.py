# claude: ignore
"""Inline review-comment markers (`# claude:` / `// claude:`).

Single source of truth for what counts as an actionable feedback note, an
`ignore` directive, and a file-level opt-out. The `lup-devtools dev comments`
scanner uses this to list unresolved feedback; the edit-permission hook mirrors
`MARKER_RE` to prompt whenever an edit adds or removes a marker.

Detection is deliberately liberal — `#` or `//`, any case, optional spaces — so
the same note reads naturally in Python, shell, TypeScript, JSON, or Markdown.
A colon is required so prose like a `## Claude` heading does not match. A marker
is a feedback note unless its keyword is `ignore`, which stays the anti-pattern
escape hatch.
"""

import re

from pydantic import BaseModel

MARKER_RE = re.compile(r"(#|//)\s*claude\s*:", re.IGNORECASE)
IGNORE_RE = re.compile(r"(#|//)\s*claude\s*:\s*ignore\b", re.IGNORECASE)
FILE_IGNORE_RE = re.compile(r"^\s*(#|//)\s*claude\s*:\s*ignore\s*$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
COMMENT_PREFIX_RE = re.compile(r"^\s*(#|//)")

CONTEXT_BEFORE = 2
CONTEXT_AFTER = 25


class FeedbackComment(BaseModel):
    """One actionable note: the source span plus a window worth reading."""

    start_line: int
    end_line: int
    read_start: int
    read_end: int
    text: str


def marker_count(text: str) -> int:
    """Count markers (feedback or ignore) — drives the hook's add/remove check."""
    return len(MARKER_RE.findall(text))


def has_file_level_ignore(text: str, max_lines: int = 10) -> bool:
    """Whether a standalone `# claude: ignore` sits in the first `max_lines`."""
    for i, line in enumerate(text.splitlines()):
        if i >= max_lines:
            break
        if FILE_IGNORE_RE.match(line):
            return True
    return False


def inside_inline_code(line: str, pos: int) -> bool:
    """Whether character `pos` falls inside a backtick code span (a doc example)."""
    return line[:pos].count("`") % 2 == 1


def find_feedback(text: str, is_markdown: bool = False) -> list[FeedbackComment]:
    """Extract feedback notes from a file's text.

    A note is a marker line plus the contiguous same-style comment lines below
    it, merged into one item. Ignore directives, fenced code, and backtick spans
    are skipped; a file-level ignore opts the whole file out.
    """
    if has_file_level_ignore(text):
        return []

    lines = text.splitlines()
    total = len(lines)
    found: list[FeedbackComment] = []
    in_fence = False
    i = 0

    while i < total:
        line = lines[i]

        if is_markdown and FENCE_RE.match(line):
            in_fence = not in_fence
            i += 1
            continue

        match = MARKER_RE.search(line)
        if (
            match is None
            or in_fence
            or IGNORE_RE.search(line) is not None
            or inside_inline_code(line, match.start())
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
                if MARKER_RE.search(lines[j]) is not None:
                    break
                parts.append(lines[j][prefix.end() :].strip())
                j += 1
            end = j - 1

        start_line = i + 1
        end_line = end + 1
        found.append(
            FeedbackComment(
                start_line=start_line,
                end_line=end_line,
                read_start=max(1, start_line - CONTEXT_BEFORE),
                read_end=min(total, end_line + CONTEXT_AFTER),
                text=" ".join(part for part in parts if part),
            )
        )
        i = end + 1

    return found
