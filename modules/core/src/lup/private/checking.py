"""What's asked of `Withholding`, the machine part holding the list of what never leaves under the operator's name, and what it answers: where it found something, by its kind, never the value."""

from pydantic import Field

from lup.publishing.events import Line
from lup.types import Model


class Text(Model):
    """A text to check, line by line, each with its number where it's read: a commit's message, a file's added lines, a ref's name, a post's part."""

    within: str
    """What holds it, as a refusal names it: `4e1f2a3's message`,
    `4e1f2a3 docs/notes.md`, `the ref it updates`, `the body`."""
    lines: list[Line]
    prose: bool = False
    """Whether it's prose, where an inbox item's number is looked for too: a
    commit's message or a post's part, never a file."""


class Binary(Model, ser_json_bytes="base64", val_json_bytes="base64"):
    """A file that isn't text, checked as bytes."""

    within: str
    content: bytes


class Checking(Model):
    """What's about to leave, to check: its texts and its files that aren't text, and the project it's of where the caller isn't a project's own code."""

    texts: list[Text] = []
    binaries: list[Binary] = []
    repository: str | None = None
    """The project, as lup names it, for a caller that isn't one of its
    parts: the gate's step, run where it's typed."""


class Place(Model):
    """Where something that never leaves was found, and what it is, never the value."""

    within: str
    line: int | None = None
    column: int | None = None
    byte: int | None = None
    what: str
    """What was found, by its kind: `the operator's home path`."""
    steer: str
    """How to write it instead."""

    def text(self) -> str:
        """Say where and what, as a compiler's message does, the steer beneath.

        >>> print(Place(within="the body", line=3, column=5, what="the host's name", steer="leave it out").text())
          the body:3:5 - the host's name
              steer: leave it out
        """
        match self:
            case Place(byte=int() as byte):
                where = f"{self.within}, at byte {byte}"
            case Place(line=int() as line, column=int() as column):
                where = f"{self.within}:{line}:{column}"
            case _:
                where = self.within
        return f"  {where} - {self.what}\n      steer: {self.steer}"


class Checked(Model):
    """Every place something that never leaves was found, in the order they come; none where nothing was."""

    places: list[Place] = Field(default=[])

    def told(self, publishing: str) -> str:
        """Say why lup refuses to publish something, `publishing` naming it (`this push`), each place beneath.

        >>> place = Place(within="the title", line=1, column=7, what="the host's name", steer="leave it out")
        >>> print(Checked(places=[place]).told("this issue"))
        lup refused to publish this issue: it holds what never leaves under the operator's name, at each place below.
          the title:1:7 - the host's name
              steer: leave it out
        """
        header = (
            f"lup refused to publish {publishing}: it holds what never leaves under "
            "the operator's name, at each place below."
        )
        return "\n".join([header, *(each.text() for each in self.places)])
