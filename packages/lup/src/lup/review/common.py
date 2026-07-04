# lup: ignore
"""Shared scanning core for the review-marker and anti-pattern scanners.

Both `lup.review.markers` and `lup.review.antipatterns` walk a file line by
line and must tell prose from code: a `#` that opens a real comment, or a
docstring, is where a review note or an `# lup: ignore` directive can live,
while the same characters inside an ordinary string literal are code.
Tokenizing and parsing the Python source answers that question once, here, so
neither scanner re-implements the other's mechanics.

The `# lup: ignore` escape hatch — inline, or as a standalone file-level
opt-out — is matched here too, and `LineCursor` is the shared line walk that
lets a scanner absorb a note's continuation lines without index bookkeeping.
"""

import ast
import re
import tokenize
from collections.abc import Callable
from io import StringIO
from typing import Self

from pydantic import BaseModel

IGNORE_RE = re.compile(r"(#|//)\s*lup\s*:\s*ignore\b", re.IGNORECASE)
FILE_IGNORE_RE = re.compile(r"^\s*(#|//)\s*lup\s*:\s*ignore\s*$", re.IGNORECASE)


def has_file_level_ignore(text: str, max_lines: int = 10) -> bool:
    """Whether a standalone `# lup: ignore` sits in the first `max_lines`.

    Such a directive opts the whole file out of anti-pattern checks (never out
    of feedback-note gathering — see `lup.review.markers.find_feedback`).
    """
    for i, line in enumerate(text.splitlines()):
        if i >= max_lines:
            break
        if FILE_IGNORE_RE.match(line):
            return True
    return False


def python_comment_columns(text: str) -> dict[int, int] | None:
    """Map each 1-based line to the column where its real `#` comment starts.

    Tokenizing tells apart a `#` that opens a comment from one inside a string
    literal, so a scanner can reject markers that are actually code. Returns
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


class PythonContext(BaseModel):
    """Where prose can live in a Python file: comment columns and docstrings.

    Built once per file by :meth:`parse`. ``comment_columns is None`` means the
    source did not tokenize; both queries then fall back to treating a position
    as prose so a note is never missed.
    """

    comment_columns: dict[int, int] | None
    docstring_lines: set[int]

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls(
            comment_columns=python_comment_columns(text),
            docstring_lines=python_docstring_lines(text),
        )

    def comment_at(self, line_no: int, col: int) -> bool:
        """Whether a real `#` comment opens at (`line_no`, `col`)."""
        if self.comment_columns is None:
            return True
        return self.comment_columns.get(line_no) == col

    def is_note_context(self, line_no: int, col: int) -> bool:
        """Whether (`line_no`, `col`) sits in a comment or inside a docstring."""
        return self.comment_at(line_no, col) or line_no in self.docstring_lines


class LineCursor:
    """Forward cursor over a file's lines with a take-a-run helper.

    Iterating yields ``(line_no, line)`` with a 1-based number.
    :meth:`take_mapping` pulls the run of following lines a mapper accepts,
    stopping before the first it rejects so iteration resumes there — the shape
    a marker note uses to absorb its continuation lines with no index
    bookkeeping in the caller.
    """

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.pos = 0

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> tuple[int, str]:
        if self.pos >= len(self.lines):
            raise StopIteration
        line = self.lines[self.pos]
        self.pos += 1
        return self.pos, line

    def take_mapping[T](
        self, mapper: Callable[[int, str], T | None]
    ) -> list[tuple[int, T]]:
        """Consume and map following lines until `mapper` returns ``None``.

        The rejecting line is left unconsumed for the next `__next__`. A mapper
        may return a falsy-but-not-``None`` value (an empty continuation line),
        which is kept; only ``None`` ends the run.
        """
        taken: list[tuple[int, T]] = []
        while self.pos < len(self.lines):
            line_no = self.pos + 1
            mapped = mapper(line_no, self.lines[self.pos])
            if mapped is None:
                break
            self.pos += 1
            taken.append((line_no, mapped))
        return taken
