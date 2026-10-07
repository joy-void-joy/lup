"""The `# lup:` comments the engine reads out of a file, as models.

A directive is written as a call (`# lup: ignore("tuple-shape", why="…")`); anything
that isn't a call is a note. The engine parses each comment with pyright's own
expression parser and reports it in one of these shapes, told apart by `kind`. The
grammar and what each directive means are in `docs/judging-writes.md`, *The `# lup:`
directives*.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from lup.types import Model


class Ignore(Model):
    """`# lup: ignore("<rule>", why="<reason>")`: keep one finding, with the reason why.

    It covers the line it's on when it follows code there, or the next line when
    it stands alone.
    """

    kind: Literal["ignore"] = "ignore"
    line: int
    """The line the comment is on, counted from 1."""
    covers: int
    """The line whose finding it keeps."""
    rule: str
    why: str


class Defer(Model):
    """`# lup: defer(issue=12, why="…")`: work knowingly left undone, on its code.

    It sits on that code, so the next reader sees the gap is known and tracked
    rather than fixing it blind or calling it pre-existing. It needs a way to come
    back: an issue that tracks it, a condition that wakes it when it holds, or
    both. A deferral with neither is reported as malformed, since nothing would
    ever close it; one whose issue is closed is reported by the gate.
    """

    kind: Literal["defer"] = "defer"
    line: int
    why: str
    """What's left undone here, in one line."""
    issue: int | str | None = None
    """An issue number in this repository, or `owner/repo#7` elsewhere."""
    when: str | None = None
    """The name of a `Condition` declared in Python.

    The gate checks it, and when it holds, the deferral is due.
    """

    @model_validator(mode="after")
    def tracked(self) -> Self:
        """Refuse a deferral that nothing could bring back."""
        if self.issue is None and self.when is None:
            message = "a defer needs an issue, a condition (`when=`), or both"
            raise ValueError(message)
        return self


class Note(Model):
    """A `# lup:` comment that isn't a call: a note for whoever reads the code next."""

    kind: Literal["note"] = "note"
    line: int
    text: str


class Malformed(Model):
    """A `# lup:` call the grammar refuses: unknown, or missing what it needs."""

    kind: Literal["malformed"] = "malformed"
    line: int
    text: str
    """The comment as written, after `lup:`."""
    problem: str
    """What's wrong with it, in one line."""


type Directive = Annotated[
    Ignore | Defer | Note | Malformed, Field(discriminator="kind")
]
"""Any `# lup:` comment, as the engine reports it."""
