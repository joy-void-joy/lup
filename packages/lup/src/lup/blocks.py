"""The building blocks a module's views are laid out from, and what a view answers: `Blocks`.

`docs/declaration.md`, *Views and blocks*. A module's Python lays out each of
its views from these, and the dashboard's page only draws them: so a module
needs no TypeScript for what it shows, the page has one way of drawing, and a
view's text form, which its command prints and agents read, comes from the
same blocks (`Blocks.text`), so an agent reads what the operator saw.

- `Line`: one line of text in spans, each in a tone (`Span`), a span naming a
  conversation referring to it by its runtime's ids.
- `Markdown`: text the page shows as Markdown, in a tone.
- `Fold`: a summary line and what folds under it, of one of the module's fold
  kinds (`FoldKind`), open or closed: its content given, or read as it opens
  from another of the module's views (`Load`).

Each block has an id its module chooses and keeps from one answer to the next,
as a step's number or a call's id: the page keeps a fold open, the cursor and a
comment where they were, by it. A tone is one of the shell's (`SHELL_TONES`)
or one the module declares (`Tone`), each drawn in a colour of the shell's
palette (`Colour`), so every module's lines read in one palette.
"""

from datetime import timedelta
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field, JsonValue

from lup.errors import LupError
from lup.events import Event
from lup.types import Model

if TYPE_CHECKING:
    from lup.doors import Method

type Colour = Literal[
    "fg", "muted", "link", "ok", "err", "warn", "info", "purple", "cyan", "orange"
]
"""A colour of the shell's palette, as the page names it (`page/src/theme.css`):
each reads at 7:1 or more on the black it's drawn on, so a module picks among
them rather than giving a value of its own."""


class Tone(Model):
    """How a span is drawn: its name, and the look it takes from another tone or its own colour, bolder or dimmer.

    A module declares its own (`Module.tones`) beside the shell's
    (`SHELL_TONES`); a span naming none of them fails the module's load.
    """

    name: str
    like: str | None = None
    """A tone whose look it takes: one of the shell's, or another of its module's."""
    colour: Colour | None = None
    """Its own colour, where it takes none from `like`."""
    weight: Literal["bold", "dim"] | None = None
    """Bolder or dimmer than the look it takes; none keeps it."""


SHELL_TONES = [
    Tone(name="plain", colour="fg"),
    Tone(name="muted", colour="muted"),
    Tone(name="strong", colour="fg", weight="bold"),
    Tone(name="operator", colour="info"),
]
"""The tones every module's spans may name: plain text, text set back, text set
forward, and the operator's own words."""


class Span(Model):
    """A run of a line's text, in a tone, and the conversation it names, where it names one."""

    text: str
    tone: str = "plain"
    """One of the shell's tones (`SHELL_TONES`), or one its module declares."""
    conversation: OfAgent | None = None
    """The conversation its text names, by its runtime's ids, which never change
    as it's renamed: its text says it as the core calls it, its path
    (`lup-impl/parser`), and the page can go to it by these, whatever it's
    called by then."""


class Line(Model):
    """One line of text, in spans."""

    block: Literal["line"] = "line"
    id: str
    spans: list[Span] = []

    @classmethod
    def of(cls, key: str, text: str, tone: str = "plain") -> Line:
        """Return a line of `text` in one tone, its id `key`.

        >>> Line.of("1", "hello").spans
        [Span(text='hello', tone='plain', conversation=None)]
        """
        return cls(id=key, spans=[Span(text=text, tone=tone)])

    def said(self) -> str:
        """Say the line as text."""
        return "".join(span.text for span in self.spans)


class Markdown(Model):
    """Text the page shows as Markdown, in a tone; its text form is the Markdown itself."""

    block: Literal["markdown"] = "markdown"
    id: str
    text: str
    tone: str = "plain"


class Load(Model):
    """What a fold reads as it opens: another view of its module's, and what it's given."""

    view: str
    """The view's name: its method's."""
    argument: dict[str, JsonValue]
    """What the view takes, as JSON."""

    @classmethod
    def of(cls, view: Method, argument: BaseModel) -> Load:
        """Return the content `view`, a view read through its class, answers for `argument`, read as the fold opens.

        Raise `BlockError` where `view` isn't a view, or doesn't take `argument`'s type.
        """
        if view.viewing() is None:
            message = f"a fold loads `{view.taken.name}`, which isn't a view"
            raise BlockError(message)
        if not isinstance(argument, view.taken.model.annotation):
            message = (
                f"a fold loads `{view.taken.name}` with a "
                f"`{type(argument).__name__}`, which it doesn't take"
            )
            raise BlockError(message)
        return cls(view=view.taken.name, argument=argument.model_dump(mode="json"))


class Fold(Model):
    """A summary line, and what folds under it, open or closed."""

    block: Literal["fold"] = "fold"
    id: str
    kind: str
    """One of its module's fold kinds (`FoldKind`), or a drawer's own, by name."""
    summary: list[Span]
    open: bool = False
    barred: bool = False
    """Whether its content is set off by a bar in its kind's colour, as a call's
    input and output are under its line."""
    content: list[Block] | Load = []
    """What's under it: given, or read from another view as it opens."""

    def said(self, indent: str = "") -> list[str]:
        """Say the fold as text, each line after `indent`: its summary, marked open or closed, then, open, its content, indented further.

        Content read as it opens isn't said: its summary is, with the view it
        reads and what it gives it beyond the agent it's of, what it leaves
        unset left out, so a reader knows which view's command reads it
        (`[exchange step=12]`).

        >>> loaded = Load(view="call", argument={"runtime": "r", "session": "s",
        ...     "call": "c1"})
        >>> Fold(id="1", kind="call", summary=[Span(text="Bash: ls")], content=loaded).said()
        ['▸ Bash: ls  [call call=c1]']
        """
        summary = "".join(span.text for span in self.summary)
        mark = "▾" if self.open else "▸"
        if isinstance(self.content, Load):
            own = OfAgent.model_fields
            given = " ".join(
                f"{key}={value}"
                for key, value in self.content.argument.items()
                if key not in own and value is not None
            )
            reads = " ".join(part for part in [self.content.view, given] if part)
            return [f"{indent}{mark} {summary}  [{reads}]"]
        head = [f"{indent}{mark} {summary}"]
        if not self.open:
            return head
        return [*head, *lines(self.content, f"{indent}  ")]


type Block = Annotated[Line | Markdown | Fold, Field(discriminator="block")]
"""One of the building blocks."""


def lines(blocks: list[Block], indent: str = "") -> list[str]:
    """Say `blocks` as lines of text, each after `indent` but a blank one."""

    def said(block: Block) -> list[str]:
        match block:
            case Line():
                return [f"{indent}{block.said()}"]
            case Markdown():
                return [
                    f"{indent}{line}" if line else ""
                    for line in block.text.splitlines()
                ]
            case Fold():
                return block.said(indent)

    return [line for block in blocks for line in said(block)]


class Blocks(Model):
    """What a view answers: its blocks, and, for a drawer, the summary line under its banner."""

    blocks: list[Block] = []
    summary: list[Span] = []
    """A drawer's line under its banner, in its kind's colour; none for a view
    no drawer shows."""
    waiting: bool = False
    """Whether it holds what waits on the operator: its summary line is bold."""

    def text(self) -> str:
        """Say the view as text, as its command prints it and an agent reads it: its summary, then its blocks, a closed fold as its summary line.

        >>> view = Blocks(summary=[Span(text="conversation · 2 steps")],
        ...     blocks=[Line.of("1", "you: hi"),
        ...         Fold(id="2", kind="calls", summary=[Span(text="called Bash, Read")],
        ...             content=[Line.of("3", "Bash: ls")])])
        >>> print(view.text())
        conversation · 2 steps
        you: hi
        ▸ called Bash, Read
        """
        summary = "".join(span.text for span in self.summary)
        return "\n".join([*([summary] if summary else []), *lines(self.blocks)])

    def tones(self) -> list[str]:
        """Return each tone the view names, once each, in the order first named.

        >>> Blocks(summary=[Span(text="a", tone="muted")],
        ...     blocks=[Fold(id="1", kind="calls", summary=[Span(text="b")],
        ...         content=[Markdown(id="2", text="c", tone="operator")])]).tones()
        ['muted', 'plain', 'operator']
        """

        def named(block: Block) -> list[str]:
            match block:
                case Line():
                    return [span.tone for span in block.spans]
                case Markdown():
                    return [block.tone]
                case Fold():
                    inside = [] if isinstance(block.content, Load) else block.content
                    return [
                        *(span.tone for span in block.summary),
                        *(tone for each in inside for tone in named(each)),
                    ]

        return list(
            dict.fromkeys(
                [
                    *(span.tone for span in self.summary),
                    *(tone for block in self.blocks for tone in named(block)),
                ]
            )
        )


class FoldKind(Model):
    """One kind of fold a module declares, as the page's fold keys know it: the letter naming it, what its folds are called, the level the keys open and close it at, how it opens, and its colour."""

    name: str
    letter: str
    """The key after `zf` closing the one the cursor is in, and after Space `z`
    `f` opening every one: two kinds of a repository's modules taking one
    letter fail the load."""
    called: str
    """What its folds are called together: `earlier exchanges`."""
    one: str
    """What the one the cursor is in is called: `the earlier exchange`."""
    level: int
    """The level `zr` and `zm` open and close it at, outermost first."""
    opens: Literal["together", "back", "deep"] = "together"
    """`together`: with every fold of its level; `back`: one at a time, the
    latest first, so each `zr` reaches one step further back; `deep`: only by
    its own keys, since what it holds is read as it opens."""
    colour: Colour


class Drawer(Model):
    """Where a view is placed: a drawer under each agent's banner, its line in the banner's group saying what it holds."""

    under: Literal["agent"] = "agent"
    letter: str
    """Its fold kind's letter, which opens and closes it."""
    called: str
    """What it's called: `the conversation`."""
    colour: Colour


class Watch(Model):
    """When a view the page shows is answered again: at these events of what it's of, and this long apart at most."""

    on: list[type[Event]] = []
    """The events, of the agent a drawer is under, after which it's answered
    again."""
    longest: timedelta | None = None
    """The longest it goes unanswered, for what no event says; none waits for
    the events alone."""


class OfAgent(Model):
    """The agent a drawer under its banner is of: its runtime, its session, and its subagent where it's one.

    Each field's description is its help on a view's command line.
    """

    runtime: str = Field(description="The runtime, by the name lup knows it by.")
    session: str = Field(description="The runtime's id for the session.")
    agent: str | None = Field(
        default=None,
        description="The runtime's id for the subagent; left out, the session's own conversation.",
    )


class BlockError(LupError):
    """A block can't be made as asked: a fold loads what isn't a view, or gives a view what it doesn't take."""
