"""The `# lup:` comments the engine reads out of a file, as models: how code speaks to its next reader.

A comment is a directive where it starts `# lup:`, and what follows is read
as a call (`README.md` here, *`# lup:` comments*):
- `ignore("<rule>", why="…")` keeps one finding of that rule, on its own line
  or, standing alone, on the next line holding code;
- `defer(issue=12, why="…")` or `defer(when=condition, why="…")` marks work
  knowingly left undone, with what brings it back;
- anything else is a note, `note("…")` or free text alike.

An `ignore` or a `defer` written wrong is `Malformed`, never read as a note, so
a mistyped one can't sit there doing nothing.
"""

from typing import Annotated, Literal

from pydantic import Field

from lup import Model


class Placed(Model):
    """Where a comment is: its line, and the column its `#` is at, each counted from 1."""

    line: int
    column: int


class Ignore(Placed):
    """`# lup: ignore("<rule>", why="…")`: one finding of `rule` kept, on the line it covers."""

    kind: Literal["ignore"] = "ignore"
    covers: int
    """The line whose finding it keeps: its own where it follows code, else
    the next line holding code, so ignores stacked above a line keep that
    line's."""
    rule: str
    why: str
    issue: int | str | None = None
    """An issue the `ignore` waits on, a fix to the rule say: here by its
    number, elsewhere as `owner/repo#7`. Once it closes, the `ignore` is due."""


class Defer(Placed):
    """`# lup: defer(issue=…, when=…, why="…")`: work knowingly left undone here, and what brings it back."""

    kind: Literal["defer"] = "defer"
    why: str
    issue: int | str | None = None
    """The issue tracking what's left: here by its number, elsewhere as
    `owner/repo#7`."""
    when: str | None = None
    """A condition a module declares, by its name, whose holding makes the
    deferral due."""


class Note(Placed):
    """A note left on the code for whoever works there next: `note("…")`, or any other text after `# lup:`."""

    kind: Literal["note"] = "note"
    text: str


class Malformed(Placed):
    """An `ignore` or a `defer` the grammar refuses, or a call of another name passing what only those take, with what's wrong."""

    kind: Literal["malformed"] = "malformed"
    text: str
    problem: str


type Directive = Annotated[
    Ignore | Defer | Note | Malformed, Field(discriminator="kind")
]
"""One `# lup:` comment, told apart by its `kind`."""
