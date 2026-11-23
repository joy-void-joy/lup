"""The kinds a module declares for what its views show: its tones, its fold kinds and its mark kinds, beside the shell's own.

A block names a kind by its name, and the kind says how it's drawn and how it
behaves, so every module's views read in one palette and fold by one mechanism:
whether a fold starts open, and what `zr` and `zm` reach, is its kind's rule,
never one view's (`README.md` here, *Kinds*). A module declares each as a field,
a selection a project's or the operator's layer changes as any field; the core
declares the shell's own (`SHELL_TONES`, `SHELL_FOLDS`).
"""

from typing import Literal, override

from lup.declaration.grammar import Named
from lup.types import Model

type Colour = Literal[
    "fg", "muted", "link", "ok", "err", "warn", "info", "purple", "cyan", "orange"
]
"""A colour of the shell's palette: each reads at 7:1 or more on the black it's
drawn on, so a module picks among them rather than giving a value of its own."""


class Tone(Model):
    """How a span is drawn: its name, and the look it takes from another tone or its own colour, bolder or dimmer."""

    name: str
    like: str | None = None
    """A tone whose look it takes: one of the shell's, or another its module declares."""
    colour: Colour | None = None
    """Its own colour, where it takes none from `like`."""
    weight: Literal["bold", "dim"] | None = None
    """Bolder or dimmer than the look it takes; none keeps it."""


class Tones(Named[Tone]):
    """The tones a module's spans may name, beside the shell's, each by its name."""

    @override
    def named(self, entry: Tone) -> str:
        return entry.name


SHELL_TONES = [
    Tone(name="plain", colour="fg"),
    Tone(name="muted", colour="muted"),
    Tone(name="strong", colour="fg", weight="bold"),
    Tone(name="operator", colour="info"),
]
"""The tones every module's spans may name: plain text, text set back, text set
forward, and the operator's own words."""


class FoldKind(Model):
    """A kind of fold: its name, the letter the fold keys take it by, what it's called, the level `zr` and `zm` open and close it at, whether its folds start open, and its colour.

    Every fold of a kind behaves as its kind says, whichever view laid it out:
    `zf` and its letter opens or closes the nearest fold of the kind, `Space f`
    and it selects that fold, `Space F` and it every fold of the kind in the
    selection. Context, a run of unchanged lines or an earlier exchange, is a
    kind like any other, at a level `zr` opens last.
    """

    name: str
    letter: str
    """The key the fold keys take it by: `f` for a file."""
    called: str
    """What the line of keys and the outline call it: `file`."""
    level: int = 1
    """The level `zr` opens it at and `zm` closes it at, counted from the
    outermost: a party's section 0, a context fold high, opening last."""
    starts_open: bool = False
    """Whether its folds start open, before the operator opens or closes one."""
    colour: Colour = "muted"
    """The colour its summary's marker and its bar are drawn in."""
    outlined: bool = False
    """Whether its folds show in the outline beside the document, each under
    its summary: what's worth finding from there, as a party, a concern or an
    item, and not what's fine-grained, as a function's body or a call."""


class Folds(Named[FoldKind]):
    """The fold kinds a module's views may name, beside the shell's, each by its name."""

    @override
    def named(self, entry: FoldKind) -> str:
        return entry.name


SHELL_FOLDS = [
    FoldKind(
        name="party",
        letter="a",
        called="party",
        level=0,
        starts_open=True,
        colour="cyan",
        outlined=True,
    ),
    FoldKind(
        name="file",
        letter="f",
        called="file",
        level=2,
        starts_open=True,
        colour="link",
        outlined=True,
    ),
    FoldKind(
        name="body",
        letter="b",
        called="body",
        level=3,
        starts_open=True,
        colour="muted",
    ),
    FoldKind(name="lines", letter="l", called="unchanged lines", level=4),
    FoldKind(
        name="sent-to",
        letter="t",
        called="where parts go",
        level=1,
        starts_open=True,
        colour="warn",
    ),
]
"""The fold kinds every view may name: a party's section of the document, which
holds what's shown of an agent or a pile; a file a `Code` or a `Diff` shows; a
function's or a class's body in it; a run of a file's unchanged lines, the
context around a change, which `zr` opens last; and, in the review of the
draft, each place its parts go."""


class Verb(Model):
    """A verb: what the operator does to a thing, by one word on the command line and one key on the dashboard, whatever module's thing it is.

    A block offers a command under a verb (`@lup.command(verb=…)`), and the
    verb's key on that block, or `lup <verb> <thing>` naming it, runs what it
    offers: one verb, done to a concern, clears it, to a landing, puts it on
    trial. A module declares a verb of its own as it declares a fold kind.
    """

    name: str
    """Its word: what's typed, `lup done @12`, and what a command names it by."""
    letter: str | None = None
    """The key the dashboard takes it by, after Space: `d` for done; none for
    a verb no key runs, as being seen runs `seen`."""
    says: str
    """What it does, in a line, as help lists it: `do what's done with it`."""


class Verbs(Named[Verb]):
    """The verbs a module's commands may be offered under, beside the core's, each by its name."""

    @override
    def named(self, entry: Verb) -> str:
        return entry.name


SHELL_VERBS = [
    Verb(name="show", says="Show it: what its block opens."),
    Verb(name="done", letter="d", says="Do what's done with it: clear it, approve it."),
    Verb(name="decline", letter="x", says="Decline it: nothing more is done with it."),
    Verb(name="toggle", letter="t", says="Toggle it: put it in, or take it out."),
    Verb(name="tell", letter="c", says="Say something to it, or on it."),
    Verb(name="seen", says="Say it's been on your screen."),
]
"""The verbs every module's commands may be offered under: what's done with a
thing, declining it, toggling it, telling it something, and saying it's been
seen; and `show`, which runs no command but shows what a thing's block opens,
as following it does on the dashboard."""


class MarkKind(Model):
    """A kind of mark on a file's lines: its name, its colour, and what a line of it says it is, as a judge's `held`."""

    name: str
    colour: Colour = "warn"
    """The colour its lines are barred and tinted in."""
    says: str
    """What its marked line says it is, before what the mark itself says:
    `held`, then `adds an ignore`."""


class Marks(Named[MarkKind]):
    """The mark kinds a module's views may name, each by its name."""

    @override
    def named(self, entry: MarkKind) -> str:
        return entry.name
