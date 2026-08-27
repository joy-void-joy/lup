"""What a launch says, and how urgently it means it.

A session's opening is thirty lines long and every one of them arrives in the
same weight. Somewhere in that block is the sentence that decides whether the
session can do its work -- no forge token, a boundary that did not come up,
a capability the host lacks -- and it sits between a version number and a
path, indistinguishable from both. Colour is not decoration here: it is the
only thing that makes the block skimmable, and skimmable is the difference
between a warning read and a warning scrolled past.

So urgency travels with the sentence rather than being chosen where it is
printed. A caller says what kind of thing it is saying; this decides what
that looks like, once, for every runtime and every surface. The alternative
was `typer.secho` at fifty call sites, which puts the judgement in fifty
places and makes it unreadable by anything that is not a terminal.

Colour is the terminal's business alone: :func:`typer.echo` strips styling
when its stream is not a tty and honours ``NO_COLOR``, so a redirected launch
records the same text with no escapes in it.
"""

from typing import Literal

import typer
from pydantic import BaseModel, Field

type Urgency = Literal[
    "refusal",
    "warning",
    "progress",
    "ready",
    "artifact",
    "boundary",
    "detail",
]
"""What kind of thing a line is, which is what decides how it is painted.

Seven rather than three, because the three that carry alarm are useless
without the ones they have to stand out *from*. A block where only errors are
coloured is a block where everything else is one undifferentiated wall, and
the eye has no anchor to find the error against.

Which is why each one states its test, and why the pair that decides the
block's temperature states it twice. ``warning`` is for something wrong:
this launch cannot do its work through it, or it is a misconfiguration that
will fail later somewhere that names neither the cause nor the remedy.
``boundary`` is for a capability the boundary does not grant, said with what
grants it -- a posture working exactly as declared. The two read alike from
inside the module that prints one, which is how a healthy launch ends up
orange from top to bottom: every author of a notice knows their line is
worth reading, and ``warning`` is the only urgency that says so. It is not.
A reader who has learned that the opening block is orange whatever happened
has been trained out of the one thing the colour is for.
"""


class Ink(BaseModel, frozen=True):
    """How one urgency is painted, in the terminal's own vocabulary."""

    colour: str | int = Field(
        default="",
        description=(
            "A named colour, or a 256-colour index where the sixteen names "
            "have nothing close enough -- orange is the case that forces "
            "this, being the shade a warning wants and one no ANSI name "
            "offers. Empty leaves the foreground alone, for a weight that "
            "is carried by dimming rather than by hue"
        ),
    )
    bold: bool = False
    dim: bool = False

    def paint(self, text: str) -> str:
        """This text in this ink, saying only what this ink actually asks for.

        ``None`` rather than ``False`` for the attributes this ink does not
        want, because the two are different instructions: ``False`` emits the
        turn-it-off code, so every plain line carried two redundant resets
        and a bold line carried a bold and an un-dim. Nothing renders
        differently for it, and everything downstream that reads the escapes
        -- a diff of captured output, a terminal recording -- reads twice the
        noise.
        """
        return typer.style(
            text,
            fg=self.colour or None,
            bold=self.bold or None,
            dim=self.dim or None,
        )


class Palette(BaseModel, frozen=True):
    """Which ink each urgency is written in, as one overridable declaration.

    A default rather than a constant, because a palette is a judgement about
    somebody else's terminal: a light background, a colour-vision difference,
    or a house style are all reasons to disagree, and none of them should
    require forking the code that decides what is a warning.
    """

    refusal: Ink = Ink(colour="red", bold=True)
    warning: Ink = Ink(colour=208)
    progress: Ink = Ink(colour="blue")
    ready: Ink = Ink(colour="green")
    artifact: Ink = Ink(colour="cyan")
    boundary: Ink = Ink(colour="magenta")
    detail: Ink = Ink(dim=True)

    def ink(self, urgency: Urgency) -> Ink:
        """The ink this palette writes one urgency in."""
        match urgency:
            case "refusal":
                return self.refusal
            case "warning":
                return self.warning
            case "progress":
                return self.progress
            case "ready":
                return self.ready
            case "artifact":
                return self.artifact
            case "boundary":
                return self.boundary
            case "detail":
                return self.detail


class Notice(BaseModel, frozen=True):
    """One line a launch says, carrying what kind of thing it is.

    ``indent`` is here rather than baked into the text because a continuation
    line is subordinate *and* still has its own urgency -- the cause under a
    failed requirement is part of a refusal, and reading it as a separate
    sentence at full weight is how a three-line finding becomes three
    findings.
    """

    text: str = Field(description="The sentence, without leading whitespace")
    urgency: Urgency = Field(
        default="detail", description="What kind of thing this line is"
    )
    indent: int = Field(
        default=0, description="Levels of subordination to the line above"
    )

    def painted(self, palette: Palette = Palette()) -> str:
        """This notice as a terminal receives it, indentation included."""
        return "    " * self.indent + palette.ink(self.urgency).paint(self.text)

    def say(self, palette: Palette = Palette()) -> None:
        """Print it, letting the stream decide whether the colour survives."""
        typer.echo(self.painted(palette))
