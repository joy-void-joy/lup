"""What the command line prints: a view's blocks and a command's line, in colour in a terminal as the dashboard draws them, plain where it's piped, and a refusal in red.

Everything printed is `Blocks`, a view's answer or what a command did
(`lup.Done.shown`), said as lines of runs (`Blocks.runs`), so the plain text an
agent reads is the text form exactly (`Blocks.text`), and colour only adds to
it. Each run is drawn in what it names: a span's tone as its module declares it
(`Looks`, which the plan carries), a fold's marker in its kind's colour, how a
block stands in its meaning's colour. Colours are the terminal's own palette, by
name, so they follow the operator's theme; rich, which typer brings, writes
them, and writes none where the output isn't a terminal.
"""

from typing import TYPE_CHECKING, TextIO

from rich.console import Console
from rich.style import Style
from rich.text import Text

from lup.shell.blocks import Blocks, Run, Standing
from lup.shell.kinds import Colour
from lup.shell.looks import Looks

if TYPE_CHECKING:
    from lup.shell.kinds import Tone


def painted(colour: Colour) -> str:
    """Return the terminal's colour, by rich's name for it, that the shell's `colour` is drawn in: the palette's meaning kept, its value the terminal's.

    >>> painted("err"), painted("ok")
    ('red', 'blue')
    """
    match colour:
        case "fg":
            return "default"
        case "muted":
            return "bright_black"
        case "link":
            return "bright_blue"
        case "ok":
            return "blue"
        case "err":
            return "red"
        case "warn":
            return "yellow"
        case "info":
            return "bright_cyan"
        case "purple":
            return "magenta"
        case "cyan":
            return "cyan"
        case "orange":
            return "dark_orange"


def meant(standing: Standing) -> Colour:
    """Return the colour a block standing so is marked in, as the page's palette means it (`page/src/shell/palette.ts`, `meanings`).

    >>> meant("waiting")
    'orange'
    """
    match standing:
        case "waiting":
            return "orange"
        case "new":
            return "link"
        case "done":
            return "muted"
        case "held":
            return "warn"


class Drawing(Looks):
    """The looks a project's modules declare, read to draw each run in what it names."""

    def tone(self, name: str) -> Style:
        """Return the style a span of the tone named `name` is drawn in: its colour and weight, or those of the tone it's like, as far as it's declared; plain where nothing declares it."""
        found: dict[str, Tone] = {each.kind.name: each.kind for each in self.tones}
        style = Style()
        seen: list[str] = []
        current = found.get(name)
        while current is not None and current.name not in seen:
            seen = [*seen, current.name]
            weight = Style(
                bold=current.weight == "bold" or None,
                dim=current.weight == "dim" or None,
            )
            colour = (
                Style(color=painted(current.colour))
                if current.colour is not None
                else Style()
            )
            style = colour + weight + style
            current = None if current.like is None else found.get(current.like)
        return style

    def kind(self, name: str) -> Style:
        """Return the style a fold's marker of the kind named `name` is drawn in: its colour; set back where nothing declares it."""
        found: dict[str, Colour] = {
            each.kind.name: each.kind.colour for each in self.folds
        }
        return Style(color=painted(found.get(name, "muted")))

    def drawn(self, run: Run) -> Style:
        """Return the style `run` is drawn in: how its block stands, its fold's kind, or its tone; plain where it names none."""
        if run.standing is not None:
            return Style(color=painted(meant(run.standing)))
        if run.kind is not None:
            return self.kind(run.kind)
        if run.tone is not None:
            return self.tone(run.tone)
        return Style()


def draw(blocks: Blocks, looks: Looks, out: TextIO) -> None:
    """Print `blocks` to `out` as their text form, each run in what it names where `out` is a terminal; where it isn't, their text form exactly (`Blocks.text`), as an agent reads it."""
    if not out.isatty():
        text = blocks.text()
        out.write(f"{text}\n" if text else "")
        return
    drawing = Drawing.model_validate(looks.model_dump())
    console = Console(file=out, highlight=False, soft_wrap=True, emoji=False)
    for line in blocks.runs():
        text = Text()
        for run in line:
            text.append(run.text, drawing.drawn(run))
        console.print(text, markup=False)


def refuse(name: str, reason: str, out: TextIO) -> None:
    """Print why a call was refused to `out`, after the command line's name: in red where `out` is a terminal."""
    if not out.isatty():
        out.write(f"{name}: {reason}\n")
        return
    console = Console(file=out, highlight=False, soft_wrap=True, emoji=False)
    console.print(Text(f"{name}: {reason}", Style(color="red")), markup=False)


def note(name: str, said: str, out: TextIO) -> None:
    """Print what lup itself says beside an answer to `out`, after the command line's name: set back where `out` is a terminal."""
    if not out.isatty():
        out.write(f"{name}: {said}\n")
        return
    console = Console(file=out, highlight=False, soft_wrap=True, emoji=False)
    console.print(Text(f"{name}: {said}", Style(dim=True)), markup=False)
