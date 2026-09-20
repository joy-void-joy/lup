"""What a parked question actually proposes to do to each file.

A question carries the operation whole and, where a native hook captured them,
the preimage of every file it would touch. What it does not carry is the
*result*: that is implied by the tool's own arguments, and unless something
works it out, a reviewer answering a whole-file write reads a JSON payload
with the new contents inside it and the old contents printed underneath, and
compares them by eye.

So the pair is derived here rather than stored. Deriving it keeps the record
append-only and keeps an approval bound to the operation it was given — the
same arguments produce the same pair, and a record that stored a rendering
could disagree with the arguments beside it.

The arithmetic is per tool and most of it is neutral: a whole-file write
carries its result, and a fragment edit is a splice against the preimage the
hook captured. The one shape this cannot do alone is a patch envelope, whose
format a provider owns — so a caller that has one hands in the reader for it,
and a caller that does not gets the rest.
"""

import difflib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from lup.policy.relay import PersistentQuestion

type FileOperation = Literal["create", "modify", "overwrite", "delete"]

type PatchReader = Callable[
    [str, Path, dict[Path, str | None], bool], list["ReviewedFile"]
]
"""Decode one provider's patch envelope into the pairs it would produce.

Taken as an argument rather than imported, because the envelope's grammar is
that provider's word and this module is read by both. A caller with no patch
to decode passes nothing and loses only that one shape.
"""


class ReviewedFile(BaseModel, frozen=True):
    """One file's documents on either side of an operation waiting for review.

    ``None`` on either side is absence rather than emptiness, and the two are
    worth keeping apart: a file created where nothing stood and a file
    truncated to nothing are different acts, and a reviewer shown "" for both
    is being asked to approve the wrong one.
    """

    path: Path
    before: str | None = None
    after: str | None = None
    overwrite: bool = False
    """Whether the call replaced the whole document rather than a fragment of it.

    Carried rather than derived, because the documents cannot answer it: a
    fragment edit that happens to rewrite every line and a whole-file write
    produce the same pair, and the difference is in how the call was
    expressed. It is also the difference the gate cares about most, so
    guessing it from the text is exactly where a guess costs something.
    """

    def operation(self) -> FileOperation:
        """Which class of change this is, the reading `PatchedFile` also takes.

        Absence on either side settles the two ends, and the flag settles the
        middle — so nothing here re-reads the documents to decide a verb the
        caller already knew.
        """
        if self.after is None:
            return "delete"
        if self.before is None:
            return "create"
        return "overwrite" if self.overwrite else "modify"

    def unchanged(self) -> bool:
        """Whether this operation would leave the file exactly as it stands."""
        return self.before == self.after

    def lines(self, document: str | None) -> list[str]:
        """One side as diff input, with absence read as no lines at all."""
        return document.splitlines(keepends=True) if document else []

    def unified(self, context: int = 3) -> str:
        """This change as a unified diff, labelled with what it does.

        Trailing newlines are normalized onto every line so a file whose last
        line has none does not end the diff with the marker `difflib` emits
        mid-hunk, which reads as content.
        """
        rendered = difflib.unified_diff(
            self.lines(self.before),
            self.lines(self.after),
            fromfile=f"{self.path} (before)"
            if self.before is not None
            else "/dev/null",
            tofile=f"{self.path} (after)" if self.after is not None else "/dev/null",
            n=context,
        )
        return "".join(
            line if line.endswith("\n") else line + "\n" for line in rendered
        )


def spliced(before: str, old: str, new: str, every: bool) -> str | None:
    """The document one fragment edit produces, or None where it cannot apply.

    ``None`` rather than a raise, because this runs over a record: a question
    parked against a preimage the edit no longer fits is a question to report
    as unapplyable, not an error to take the whole listing down with.
    """
    occurrences = before.count(old)
    if occurrences == 0 or (occurrences != 1 and not every):
        return None
    if every:
        # The Edit tool's own splice, over a literal the caller already chose.
        return before.replace(old, new)  # lup: ignore[string-replace]
    position = before.find(old)
    return before[:position] + new + before[position + len(old) :]


def written_file(path: Path, content: str, before: str | None) -> list[ReviewedFile]:
    """The pair a whole-file write produces: its argument is the result.

    An overwrite wherever something stood, which is the classification the
    edit gate turns on and the reason this surface was worth building.
    """
    return [
        ReviewedFile(
            path=path, before=before, after=content, overwrite=before is not None
        )
    ]


def edited_file(
    path: Path,
    old: str,
    new: str,
    every: bool,
    before: str | None,
) -> list[ReviewedFile]:
    """The pair a fragment edit produces, against the preimage that was captured.

    Against the captured preimage and never the file as it stands now. What a
    reviewer is answering is the operation as it was submitted, and a splice
    recomputed from a file that has since moved would show them a change
    nobody proposed.
    """
    if before is None:
        return []
    after = spliced(before, old, new, every)
    if after is None:
        return []
    return [ReviewedFile(path=path, before=before, after=after)]


def reviewed_files(
    question: PersistentQuestion, patches: PatchReader | None = None
) -> list[ReviewedFile]:
    """Every file change one parked question proposes, as before/after pairs.

    Empty is a real answer and the common one: a shell command that names no
    file it will write has nothing to diff, and what a reviewer needs there is
    the command, which the question already prints. An empty list means "this
    is not a file change", never "the diff failed".
    """
    payload = question.operation.payload
    cwd = question.operation.cwd

    def resolved(path: str) -> Path:
        """One payload path against the directory the operation ran in.

        Resolved rather than passed through, because a reviewer answering from
        another terminal has no reason to share the agent's working directory
        — and `docs/plan.md` names a different file in each of the worktrees
        this repository keeps open at once.
        """
        named = Path(path)
        return named if named.is_absolute() else cwd / named

    def captured(path: str) -> str | None:
        """The preimage the hook recorded for one path, keyed as it recorded it."""
        return question.preconditions.get(resolved(path))

    def text(key: str) -> str:
        """One payload field as text, with a missing or non-string field empty."""
        value = payload.get(key)
        return value if isinstance(value, str) else ""

    def flag(key: str) -> bool:
        """One payload field as a flag, with anything but a true absent.

        `True` rather than truthiness: a payload is whatever the runtime put
        on the wire, and reading `"false"` or `1` as "yes, every occurrence"
        would widen an edit nobody asked to widen.
        """
        return payload.get(key) is True

    match question.operation.tool:
        case "Write" if text("file_path"):
            named = text("file_path")
            return written_file(resolved(named), text("content"), captured(named))
        case "Edit" if text("file_path"):
            named = text("file_path")
            return edited_file(
                resolved(named),
                text("old_string"),
                text("new_string"),
                flag("replace_all"),
                captured(named),
            )
        case "apply_patch" | "Bash" if patches is not None and text("command"):
            return patches(
                text("command"),
                cwd,
                question.preconditions,
                question.operation.tool == "Bash",
            )
    return []
