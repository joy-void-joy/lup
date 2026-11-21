"""`Publishing`: what's about to leave under the operator's name, which a module's methods hear through `@lup.on`, and may refuse.

`remote` fires it before each push and `github` before each post, and nothing
leaves where a part hearing it refuses, raising `RefusedError` with the words
the agent reads instead: where it found what it refuses, by its kind, never the
value itself. It carries what would leave, as text, so a part hearing it reads
nothing of the repository's: a push's ref and each commit the remote lacks, one
commit an event, and a post's parts (`README.md` here).
"""

from typing import Annotated, ClassVar, Literal

from pydantic import Base64Bytes, Field

from lup.doors.events import Event
from lup.types import Model


class Line(Model):
    """A line a commit adds to a file: its number in the file the commit holds, from 1, and its text."""

    number: int = Field(ge=1)
    text: str


class Changed(Model):
    """A file a commit adds or changes, as the commit publishes it: its path, and the lines it adds against each parent, or its bytes whole where it isn't text."""

    path: str
    """Its path from the repository's root, as git writes it."""
    added: list[Line] = []
    """The lines it adds, where it's text: against a merge's every parent,
    the merge's own resolution, never what a parent brought."""
    content: Base64Bytes | None = None
    """Its bytes, where it isn't text, read whole; none for text."""


class Commit(Model):
    """A commit a push publishes: its id, its message, and each file it adds or changes."""

    id: str
    message: str
    changed: list[Changed] = []


class Push(Model):
    """A push about to leave: the remote, by its name in the repository's configuration, the ref it updates, and a commit the remote lacks, which it publishes, or none where it publishes the ref's name alone."""

    kind: Literal["push"] = "push"
    remote: str
    ref: str
    """The ref's full name, such as `refs/heads/feat`."""
    commit: Commit | None = None


class Written(Model):
    """One part of a post, by the name its tool gives it: `title`, `body`."""

    name: str
    text: str


class Post(Model):
    """A post about to leave: what it is, in a few words (`a comment on joy-void-joy/lup#12`), and each of its parts."""

    kind: Literal["post"] = "post"
    what: str
    parts: list[Written]


type Published = Annotated[Push | Post, Field(discriminator="kind")]
"""What's about to leave: a push, or a post."""


class Publishing(Event):
    """Something about to leave under the operator's name: a method hearing it may refuse it, raising `RefusedError` with where it found what isn't published, and nothing leaves."""

    answered: ClassVar[bool] = True
    kind: Literal["publishing"] = "publishing"
    published: Published
