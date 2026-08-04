# lup: ignore[import-re, re-call, empty-collection]
"""Inline marker scanning for the repo's two marker families.

- Review notes (`# lup:` / `// lup:`): actionable feedback left in the code;
  the `ignore` keyword — inline or standalone file-level — is the
  anti-pattern escape hatch, never a note and never a reason to hide one. A
  `defer[<wake condition>]:` head marks the note as parked work rather than
  open feedback; the scanner classifies it and parses the condition out. The
  `lup-devtools dev comments` scanner uses this to list unresolved feedback;
  the edit-permission hook makes the same note/suppression split, prompting
  whenever an edit changes the note count or adds a suppression.
- Customization todos (`# TEMPLATE:` in comments, bare `TEMPLATE:` in
  docstrings): the template's domain decision points, gathered by
  `lup-devtools dev todos` so `/lup:init` walks every one.

Both families share one scan (:func:`find_markers`, parameterized over the
marker regex); :func:`find_feedback` binds it to the review-note rules. The
tokenization, docstring detection, ignore matching, and line cursor the scan
stands on live in :mod:`lup.codescan.common`, shared with the anti-pattern
auditor.

Detection is deliberately liberal — `#` or `//`, any case, optional spaces — so
the same note reads naturally in Python, shell, TypeScript, JSON, or Markdown.
A colon is required so prose like a `## Notes` heading does not match. A marker
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

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from lup.codescan.common import IGNORE_RE, LineCursor, PythonContext

MARKER_RE = re.compile(r"(#|//)\s*lup\s*:", re.IGNORECASE)
# A deferral note parks work until a stated wake condition is met:
# `# lup: defer[<wake condition>]: <text>`. The bracket syntax deliberately
# mirrors the typed `# lup: ignore[rule-id]` escape hatch — which means a
# condition may itself contain brackets (`defer[when ignore[dict-get] sites
# migrate]: ...`), so the head ends at the first `]` that is followed by a
# colon, and the colon is required. A head that never closes with `]:` is
# malformed and the note stays an ordinary (red, visible) review note. The
# head is matched against a note's text (the part after the marker), so the
# `ignore` keyword — which never reaches note classification — is untouched.
DEFER_HEAD_RE = re.compile(r"^defer\s*\[(?P<condition>.+?)\]\s*:\s*", re.IGNORECASE)
# Customization todos are shouty and case-sensitive (like TODO:/FIXME:), so
# prose about "the template" never matches. The comment prefix is optional
# because a docstring todo carries no `#`; group 1 still captures the
# introducer when present, as the scan expects.
TEMPLATE_MARKER_RE = re.compile(r"(?:(#|//)\s*)?TEMPLATE\s*:")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
COMMENT_PREFIX_RE = re.compile(r"^\s*(#|//)")

# lup: ignore[library-default] — Python's own source suffixes
PYTHON_SUFFIXES = {".py", ".pyi"}
# lup: ignore[library-default] — Markdown's own suffixes
MARKDOWN_SUFFIXES = {".md", ".markdown"}
# Languages where `#` does not open a comment (`//` does), so a `# lup:` is
# always string content (e.g. a Python marker quoted inside a JS template) —
# only `//` markers count as notes there.
# lup: ignore[library-default] — the suffixes where `#` opens no comment, a language fact
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
    match path.suffix.lower():
        case suffix if suffix in PYTHON_SUFFIXES:
            return ScanMode.PYTHON
        case suffix if suffix in MARKDOWN_SUFFIXES:
            return ScanMode.MARKDOWN
        case suffix if suffix in JS_SUFFIXES:
            return ScanMode.JS
        case _:
            return ScanMode.TEXT


# The closed vocabulary of review-note flavors: an ordinary actionable note,
# or deferred work parked behind an explicit wake condition.
type NoteKind = Literal["note", "defer"]


class MarkerComment(BaseModel):
    """One actionable note: the source span plus a window worth reading.

    ``kind`` classifies the note; a ``defer`` note carries its wake
    ``condition`` parsed out of the `defer[...]` head, and ``text`` holds only
    the message that follows it. An ordinary note has no condition.
    """

    start_line: int
    end_line: int
    read_start: int
    read_end: int
    text: str
    kind: NoteKind = "note"
    condition: str | None = None

    @model_validator(mode="after")
    def coherent_kind(self) -> Self:
        match (self.kind, self.condition):
            case ("defer", None) | ("defer", ""):
                raise ValueError("a defer note requires a wake condition")
            case ("note", str()):
                raise ValueError("an ordinary note carries no wake condition")
            case _:
                return self

    def marker_text(self) -> str:
        """The note body as written after its marker, defer head included."""
        match self.kind:
            case "defer":
                return f"defer[{self.condition}]: {self.text}"
            case "note":
                return self.text


def inside_inline_code(line: str, pos: int) -> bool:
    """Whether character `pos` falls inside a backtick code span (a doc example).

    Odd single-backtick parity catches a marker mid-span; a backtick run
    directly before the marker catches rst-style double-backtick quoting,
    whose even-length run defeats the parity check.
    """
    prefix = line[:pos]
    return prefix.count("`") % 2 == 1 or prefix.endswith("`")


class MarkerScan:
    """One left-to-right pass over a file's lines, yielding each marker note.

    A note is a marker line plus the contiguous same-style comment lines below
    it, merged into one item; the run ends at a decoration line (no letters or
    digits, e.g. the edge of a `# ====` banner), a foreign comment style, a new
    marker, or prose outside a comment. Lines whose marker also matches
    `ignore`, fenced code, and backtick spans are skipped. In Python mode a
    marker counts only inside a comment or docstring, so marker text in an
    ordinary string literal is left alone.
    """

    def __init__(
        self,
        text: str,
        mode: str,
        *,
        marker: re.Pattern[str],
        ignore: re.Pattern[str] | None,
    ) -> None:
        self.mode = mode
        self.marker = marker
        self.ignore = ignore
        self.is_markdown = mode == ScanMode.MARKDOWN
        self.context = PythonContext.parse(text) if mode == ScanMode.PYTHON else None
        self.lines = text.splitlines()
        self.total = len(self.lines)
        self.cursor = LineCursor(self.lines)
        self.in_fence = False

    def in_note_context(self, line_no: int, col: int) -> bool:
        return self.context is None or self.context.is_note_context(line_no, col)

    def opens_note(self, line_no: int, line: str, match: re.Match[str]) -> bool:
        """Whether a marker at `match` starts a real note under the active mode."""
        if self.in_fence:
            return False
        if self.ignore is not None and self.ignore.match(line, match.start()):
            return False
        if self.mode == ScanMode.JS and match.group(1) == "#":
            return False
        if inside_inline_code(line, match.start()):
            return False
        return self.in_note_context(line_no, match.start())

    def continuation(self, intro: str) -> Callable[[int, str], str | None]:
        """A mapper yielding a continuation line's text, or ``None`` to end the run."""

        def content_of(line_no: int, line: str) -> str | None:
            prefix = COMMENT_PREFIX_RE.match(line)
            if prefix is None or prefix.group(1) != intro:
                return None
            if not self.in_note_context(line_no, prefix.start(1)):
                return None
            if self.marker.search(line) is not None:
                return None
            content = line[prefix.end() :].strip()
            if content and not any(ch.isalnum() for ch in content):
                return None
            return content

        return content_of

    def notes(self) -> list[MarkerComment]:
        found: list[MarkerComment] = []
        for line_no, line in self.cursor:
            if self.is_markdown and FENCE_RE.match(line):
                self.in_fence = not self.in_fence
                continue

            match = self.marker.search(line)
            if match is None or not self.opens_note(line_no, line, match):
                continue

            parts = [line[match.end() :].strip()]
            end_line = line_no

            if not self.is_markdown and line[: match.start()].strip() == "":
                for cont_no, content in self.cursor.take_mapping(
                    self.continuation(match.group(1))
                ):
                    parts.append(content)
                    end_line = cont_no

            found.append(
                MarkerComment(
                    start_line=line_no,
                    end_line=end_line,
                    read_start=max(1, line_no - CONTEXT_BEFORE),
                    read_end=min(self.total, end_line + CONTEXT_AFTER),
                    text=" ".join(part for part in parts if part),
                )
            )
        return found


def find_markers(
    text: str,
    mode: str = ScanMode.TEXT,
    *,
    marker: re.Pattern[str],
    ignore: re.Pattern[str] | None = None,
) -> list[MarkerComment]:
    """Extract one marker family's notes from a file's text under a `ScanMode`."""
    return MarkerScan(text, mode, marker=marker, ignore=ignore).notes()


def classify_deferral(note: MarkerComment) -> MarkerComment:
    """Split a `defer[<wake condition>]:` head off one review note, if present.

    A matching note comes back with kind ``defer``, its wake condition parsed
    out, and ``text`` reduced to the message after the head. Any other note —
    including prose that merely starts with the word "defer", a head whose
    condition is empty, or a head that never closes with `]:` — is returned
    unchanged as an ordinary ``note``, so a malformed deferral degrades to
    visible open feedback instead of a silently mangled condition.
    """
    head = DEFER_HEAD_RE.match(note.text)
    if head is None:
        return note
    condition = head.group("condition").strip()
    if not condition:
        return note
    return note.model_copy(
        update={
            "kind": "defer",
            "condition": condition,
            "text": note.text[head.end() :],
        }
    )


def find_feedback(text: str, mode: str = ScanMode.TEXT) -> list[MarkerComment]:
    """Extract `# lup:` review notes from a file's text.

    Binds :func:`find_markers` to the review-note rules: `ignore` directives
    are skipped — they are the anti-pattern escape hatch, not feedback. That
    covers the standalone file-level `# lup: ignore` too: it disables
    anti-pattern checks (see `lup.codescan.antipatterns`), never note gathering,
    so feedback in an opted-out file still surfaces. Each surviving note is
    then classified through :func:`classify_deferral`, so deferred work carries
    its wake condition as data.
    """
    notes = find_markers(text, mode, marker=MARKER_RE, ignore=IGNORE_RE)
    return [classify_deferral(note) for note in notes]


class NoteTarget(BaseModel):
    """One note a caller means to remove, by recorded position and body.

    ``text`` is the body as :meth:`MarkerComment.marker_text` spells it.
    Supplying it makes the match identity-bearing: the target still finds its
    note after surrounding lines drifted, and never removes a different note
    that merely sits at the recorded line. Omitting it matches on position
    alone, which is all a `file:line` caller can offer.
    """

    line: int
    text: str | None = None


class NoteRemoval(BaseModel):
    """Rewritten text, the notes actually removed, and the targets not found."""

    text: str
    removed: list[MarkerComment]
    missing: list[NoteTarget]


def without_note(lines: list[str], note: MarkerComment) -> None:
    """Drop a standalone note whole; leave an inline note's code behind."""
    head = lines[note.start_line - 1]
    match = MARKER_RE.search(head)
    head_code = head[: match.start()] if match is not None else ""
    if match is not None and head_code.strip():
        lines[note.start_line - 1] = head_code.rstrip()
    else:
        del lines[note.start_line - 1 : note.end_line]


def resolve_note(
    candidates: list[MarkerComment], target: NoteTarget
) -> MarkerComment | None:
    """Find the note a target names, tolerating drift when it carries text.

    A text-bearing target picks the nearest candidate whose body matches
    exactly, so an unchanged line scores zero and wins outright while a note
    pushed up or down by an earlier edit is still found.
    """
    if target.text is None:
        return next(
            (note for note in candidates if note.start_line == target.line), None
        )
    return min(
        [note for note in candidates if note.marker_text() == target.text],
        key=lambda note: abs(note.start_line - target.line),
        default=None,
    )


def remove_notes(
    text: str, mode: str, targets: list[NoteTarget], *, wake: bool = False
) -> NoteRemoval:
    """Strip each target's note from one file's text.

    A `defer[...]` note is parked work rather than open feedback, so a target
    landing on one leaves it in place unless *wake* is set. A target whose
    note is absent is reported rather than raised — the code a note sat on may
    already be gone, which is an outcome to record, not a failure.
    """
    candidates = find_feedback(text, mode)
    lines = text.splitlines()
    claimed: list[MarkerComment] = []
    missing: list[NoteTarget] = []
    for target in targets:
        note = resolve_note(
            [note for note in candidates if note not in claimed], target
        )
        if note is None or (note.kind == "defer" and not wake):
            missing.append(target)
            continue
        claimed.append(note)
    for note in sorted(claimed, key=lambda note: note.start_line, reverse=True):
        without_note(lines, note)
    trailing = "\n" if text.endswith("\n") else ""
    return NoteRemoval(
        text="\n".join(lines) + trailing, removed=claimed, missing=missing
    )
