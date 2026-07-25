# lup: ignore[empty-collection, string-split, tuple-shape]
# A line-oriented decoder accumulates into empty lists and speaks in the
# marker/text pairs the envelope format itself is written in.
"""Codex apply_patch envelope parsing for the hook dispatcher.

Codex hands a hook one opaque envelope covering any number of files where
Claude's edit tools hand over structured before/after text. Decoding it
back into per-file documents is what lets the canonical edit policy judge
a Codex patch at all, instead of refusing every one of them unread.

Rendered verbatim into each plugin's ``hooks/runtime`` as
``codex_patch.py``, so it imports only the standard library.
"""

from collections.abc import Callable

# lup: Why do we have # lup: ignore[tuple-shape] and empty-collection?  This file feels very patchy
BEGIN = "*** Begin Patch"
END = "*** End Patch"
ADD = "*** Add File: "
DELETE = "*** Delete File: "
UPDATE = "*** Update File: "
MOVE = "*** Move to: "
SECTION = "*** "
HUNK = "@@"


class PatchedFile:
    """One file's documents on either side of a patch, ready for decide_edit."""

    path: str
    before: str | None
    after: str | None

    def __init__(self, path: str, before: str | None, after: str | None) -> None:
        self.path = path
        self.before = before
        self.after = after


def locate(source: list[str], preimage: list[str], start: int) -> int:
    """Find the hunk's preimage as a contiguous run at or after ``start``."""
    if not preimage:
        return start
    for index in range(start, len(source) - len(preimage) + 1):
        if source[index : index + len(preimage)] == preimage:
            return index
    raise ValueError("patch context does not match the file on disk")


def apply_hunks(current: str, hunks: list[list[tuple[str, str]]]) -> str:
    """Replay context-anchored hunks over the current document."""
    source = current.split("\n")
    result: list[str] = []
    cursor = 0
    for hunk in hunks:
        preimage = [text for marker, text in hunk if marker in (" ", "-")]
        index = locate(source, preimage, cursor)
        result.extend(source[cursor:index])
        cursor = index
        for marker, text in hunk:
            match marker:
                case " ":
                    result.append(text)
                    cursor += 1
                case "-":
                    cursor += 1
                case _:
                    result.append(text)
    result.extend(source[cursor:])
    return "\n".join(result)


def take_added(lines: list[str], index: int) -> tuple[str, int]:
    """Collect the ``+``-prefixed body introducing a new file."""
    body: list[str] = []
    while index < len(lines) and lines[index].startswith("+"):
        body.append(lines[index][1:])
        index += 1
    return "\n".join(body), index


def take_hunks(lines: list[str], index: int) -> tuple[list[list[tuple[str, str]]], int]:
    """Collect hunks until the next section marker ends this file."""
    hunks: list[list[tuple[str, str]]] = []
    hunk: list[tuple[str, str]] = []
    while index < len(lines):
        line = lines[index]
        if line.startswith(SECTION):
            break
        if line.startswith(HUNK):
            if hunk:
                hunks.append(hunk)
            hunk = []
            index += 1
            continue
        if line[:1] in (" ", "-", "+"):
            hunk.append((line[:1], line[1:]))
            index += 1
            continue
        if line == "":
            hunk.append((" ", ""))
            index += 1
            continue
        break
    if hunk:
        hunks.append(hunk)
    return hunks, index


def patched_files(
    text: str, read_document: Callable[[str], str | None]
) -> list[PatchedFile]:
    """Decode an apply_patch envelope into per-file before/after documents.

    ``read_document`` supplies a path's current text, or None when it does
    not exist; injecting it keeps the decode testable away from a disk.
    Anything the format does not account for raises, so an envelope this
    parser cannot vouch for reaches the caller's conservative branch
    rather than a decision made on a misread patch.
    """
    lines = text.split("\n")
    starts = [index for index, line in enumerate(lines) if line.strip() == BEGIN]
    if not starts:
        raise ValueError("patch envelope is missing its Begin Patch header")
    index = starts[0] + 1
    files: list[PatchedFile] = []
    while index < len(lines):
        line = lines[index]
        if line.startswith(END):
            break
        if line.startswith(ADD):
            body, index = take_added(lines, index + 1)
            files.append(PatchedFile(line[len(ADD) :].strip(), None, body))
            continue
        if line.startswith(DELETE):
            path = line[len(DELETE) :].strip()
            files.append(PatchedFile(path, read_document(path), None))
            index += 1
            continue
        if line.startswith(UPDATE):
            path = line[len(UPDATE) :].strip()
            index += 1
            destination = path
            if index < len(lines) and lines[index].startswith(MOVE):
                destination = lines[index][len(MOVE) :].strip()
                index += 1
            hunks, index = take_hunks(lines, index)
            current = read_document(path)
            if current is None:
                raise ValueError(f"patch updates a file that does not exist: {path}")
            files.append(PatchedFile(destination, current, apply_hunks(current, hunks)))
            continue
        index += 1
    if not files:
        raise ValueError("patch envelope declares no file changes")
    return files
