"""What leaves under the operator's name, as lup's `Publishing` event tells a module's hooks, and what a hook answers.

lup's `Publishing` event (`lup.events`) comes before anything leaves under the
operator's name: a push through git's remote helper (`lup_dev.remote.protocol`,
`PushHandler`) and a post through lup's GitHub tools that write
(`lup.github.serving`). Every module's hooks at it may refuse, each refusal
naming what it found and where, never what it found itself: one refusal keeps
the push or the post from leaving. A hook that fails there refuses too, since a
check that didn't run let nothing through.
"""

from typing import Annotated, Literal

from pydantic import Field

from lup.types import Model


class Updating(Model):
    """One ref a push would update: the object it's to name, and the ref."""

    source: str
    """The object, by its id, as the room resolved what git named."""
    destination: str
    """The ref's full name, such as `refs/heads/feat`."""


class Push(Model):
    """A push through lup's remote helper: what it would update, and what the remote holds already."""

    kind: Literal["push"] = "push"
    remote: str
    """The remote, by its name in the repository's `config`."""
    updates: list[Updating]
    """Each ref it would update; a deletion publishes nothing, so it isn't here."""
    has: list[str]
    """The objects the remote's refs name, as the host listed them: what they
    reach is published already."""


class Part(Model):
    """One part of a post, by the name the tool gives it."""

    name: str
    """`title`, `body`."""
    text: str


class Post(Model):
    """A post through lup's GitHub tools: what it is, and each part of it."""

    kind: Literal["post"] = "post"
    what: str
    """What it is, in a few words: `an issue`, `a comment on #12`."""
    parts: list[Part]


type Published = Annotated[Push | Post, Field(discriminator="kind")]
"""What `Publishing` is about: a push, or a post."""


class Place(Model):
    """Where in what's published a hook found what it refuses."""

    within: str
    """What holds it: a file of a commit (`4e1f2a3 docs/notes.md`), a commit's
    message (`4e1f2a3's message`), the path of a file a commit adds, the ref a
    push updates, or a post's part (`the body`)."""
    line: int | None = None
    """Its line, counted from 1."""
    column: int | None = None
    """Its column on that line, counted from 1 in characters, as Python counts them."""
    byte: int | None = None
    """Its offset, in a file that isn't text."""

    def text(self) -> str:
        """Say where, as a compiler's message does.

        >>> Place(within="4e1f2a3 docs/notes.md", line=12, column=9).text()
        '4e1f2a3 docs/notes.md:12:9'
        >>> Place(within="4e1f2a3 logo.png", byte=40).text()
        '4e1f2a3 logo.png, at byte 40'
        >>> Place(within="the ref it updates", column=12).text()
        'the ref it updates, at column 12'
        """
        if self.byte is not None:
            return f"{self.within}, at byte {self.byte}"
        if self.line is None and self.column is not None:
            return f"{self.within}, at column {self.column}"
        if self.line is None:
            return self.within
        if self.column is None:
            return f"{self.within}:{self.line}"
        return f"{self.within}:{self.line}:{self.column}"


class Refusal(Model):
    """A hook's refusal of what would be published: what it found, where, and how it's written instead."""

    what: str
    """What it found, by its kind, never the value: `the operator's home path`."""
    place: Place
    steer: str
    """How to write it instead, or what to do."""

    def lines(self) -> list[str]:
        """Say it as the judge says a finding: where, what, then the steer beneath.

        >>> at = Place(within="the body", line=3, column=5)
        >>> Refusal(what="the host's name", place=at, steer="leave it out").lines()
        ["  the body:3:5 - the host's name", '      steer: leave it out']
        """
        return [f"  {self.place.text()} - {self.what}", f"      steer: {self.steer}"]


def told(refusals: list[Refusal], publishing: str) -> str:
    """Say why lup refused to publish something, `publishing` naming it (`this push`), each refusal beneath.

    >>> at = Place(within="the title", line=1, column=7)
    >>> print(told([Refusal(what="the host's name", place=at, steer="leave it out")], "this issue"))
    lup refused to publish this issue: a module's check at `Publishing` found what isn't published, at each place below.
      the title:1:7 - the host's name
          steer: leave it out
    """
    header = (
        f"lup refused to publish {publishing}: a module's check at `Publishing` "
        "found what isn't published, at each place below."
    )
    return "\n".join([header, *(line for each in refusals for line in each.lines())])
