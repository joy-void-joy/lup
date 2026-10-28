"""The building blocks a module's views are laid out from, and what a view answers: `Blocks`.

`docs/declaration.md`, *Views and blocks*. A module's Python lays out each of
its views from these, and the dashboard's page only draws them: so a module
needs no TypeScript for what it shows, the page has one way of drawing, and a
view's text form, which its command prints and agents read, comes from the
same blocks (`Blocks.text`), so an agent reads what the operator saw.

- `Line`: one line of text in spans, each in a tone (`Span`), a span naming a
  conversation or an item referring to it, one saying the time since a moment
  said again as it passes (`Ticking`), one measuring how full something is
  (`Gauge`).
- `Markdown`: text the page shows as Markdown, in a tone.
- `Fold`: a summary line and what folds under it, of one of the module's fold
  kinds (`FoldKind`), open or closed: its content given, or read as it opens
  from another of the module's views (`Load`). What came before the operator's
  review mark on what a view shows folds under one of them, and a fold kind may
  cap how much stays open after it, so one left unreviewed for long doesn't
  fill the screen (`kept_open`, `FoldKind.keeps_open`).
- `Diff`: a file's change, whole, what matters in it marked (`Mark`); `Code`: a
  file as it stands. The page lays out their lines, folds the runs of unchanged
  ones and each function's and class's body by the file's syntax, and
  highlights them.

Each block has an id its module chooses and keeps from one answer to the next,
as a step's number or a call's id: the page keeps a fold open, the cursor and a
comment where they were, by it; and, where a comment records what it was
written on, a version (`version`). A tone is one of the shell's (`SHELL_TONES`)
or one the module declares (`Tone`), each drawn in a colour of the shell's
palette (`Colour`), so every module's lines read in one palette. The shell's
own fold kinds (`SHELL_FOLDS`) are the review's and the files', which every
repository's looks carry.
"""

from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import BaseModel, Field, JsonValue, model_validator

from lup.errors import LupError
from lup.events import Event
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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


class Offer(Model):
    """What a block offers the operator to do with what it shows: one of its module's actions, what it's given, the verb whose key reaches it or a chord of its own, when it runs, and whether a comment on the block implies it.

    `docs/declaration.md`, *Views and blocks*. A verb's key, Space and its
    letter, does what the innermost block under the cursor offering that verb
    offers, so one key approves a held change, marks a file reviewed or holds
    an agent's writes, as the block it's on says. From the offer come the line
    of keys and the stack's word on what the key does (`says`).
    """

    action: str
    """The action, by its name: the method's of the module whose view the block
    is in; for a view the page lays out itself until its module serves it, the
    request the page sends (`inbox-answer-approval`)."""
    argument: dict[str, JsonValue] = {}
    """What the action is given, as JSON."""
    verb: str | None = None
    """The verb it answers, by its name (`Verb`): the core's `done`, `decline`,
    `send` or `comment`, which apply to anything, or one a module declares, as
    the judge's `hold`; none where it takes a chord of its own."""
    chord: str | None = None
    """Its own keys, as vim's keymap writes them, where it answers no verb: a
    module's view key, changing only what its view shows."""
    runs: Literal["send", "once"] = "send"
    """When it runs: as the reply is sent, recorded in the draft until
    Ctrl+Enter, refused where what it's on changed since it was shown; or at
    once, as a key changing only the view does, and as each of the page's own
    views' does until each moves to its module (#247)."""
    commented: bool = False
    """Whether a comment written on its block implies it, as one on a held
    change approves it with the comment, and one on a file of "since you
    approved" marks it reviewed."""
    says: str
    """What it does, as the line of keys and the stack say it after its key:
    `approve`, `mark it reviewed`."""

    @model_validator(mode="after")
    def reached(self) -> Self:
        """Refuse an offer that answers a verb and takes a chord of its own too, or neither: one key reaches it.

        >>> Offer(action="hold", verb="hold", says="hold its writes").runs
        'send'
        """
        if (self.verb is None) == (self.chord is None):
            message = (
                "an offer answers a verb or takes a chord of its own, one of "
                f"them: `{self.action}` gives {'neither' if self.verb is None else 'both'}"
            )
            raise ValueError(message)
        return self


class Verb(Model):
    """A verb the operator's keys say, Space and its key, which the innermost block under the cursor offering it answers (`Offer.verb`).

    The shell's apply to anything (`SHELL_VERBS`); a module declares its own
    beside them, as the judge's `hold`, each a field of its module so a
    person's layer gives it another key. Two taking one key fail the load.
    """

    name: str
    key: str
    """The key after Space: `d`."""
    called: str
    """What the list of keys calls it: `done`, `send to`."""


SHELL_VERBS = [
    Verb(name="done", key="d", called="done"),
    Verb(name="decline", key="x", called="decline"),
    Verb(name="send", key="s", called="send to"),
    Verb(name="comment", key="c", called="comment"),
]
"""The verbs every block may offer, which the core's module declares so a
person's layer may give each another key: marking something done, as an item
read, a file reviewed or a change approved; declining it; sending it to
another party; and commenting on it."""


class Ticking(Model):
    """How a span says the time since a moment, said again as the time passes: `waiting 5m`, `3s ago`."""

    since: datetime
    said: str = "{}"
    """What it says, `{}` standing for the time since `since` as the page says a
    time (`3s`, `5m`, `2h`, `4d`): `waiting {}`, `{} ago`."""
    first: str | None = None
    """What it says instead for its first minute, where that's other: `just in`."""


class Gauge(Model):
    """How full what a span measures is: how much of it is used, of how much there is, as a context's tokens of its window."""

    used: int
    of: int | None = None
    """How much there is; none where it isn't known."""


class Span(Model):
    """A run of a line's text, in a tone, and what it names or measures, where it does."""

    text: str
    tone: str = "plain"
    """One of the shell's tones (`SHELL_TONES`), or one its module declares."""
    conversation: OfAgent | None = None
    """The conversation its text names, by their runtime's ids, which never
    change as they're renamed: the text names them as the core calls them, by
    their path (`lup-impl/parser`), and the page can go to them by these,
    whatever they're called by then."""
    item: int | None = None
    """The item of lup's inbox its text names, by its number, as `@51` says it:
    the page can go to it."""
    ticking: Ticking | None = None
    """How it says the time since a moment, where it does: its text is what it
    said as the view was answered, and the page says it again as the time
    passes, so nothing is answered again for a clock."""
    gauge: Gauge | None = None
    """What it measures, where it's a gauge, as a context's ring: its text says
    it, and the page may draw it."""


class Line(Model):
    """One line of text, in spans."""

    block: Literal["line"] = "line"
    id: str
    version: str | None = None
    """The version of what it shows, which a comment written on it records so
    the agent is told what changed since: a file's, as git names its content;
    none where the page goes by its text."""
    offers: list[Offer] = []
    """What it offers the operator to do with what it shows, each answering a
    verb's key or a chord of its own (`Offer`)."""
    spans: list[Span] = []

    @classmethod
    def of(cls, key: str, text: str, tone: str = "plain") -> Line:
        """Return a line of `text` in one tone, its id `key`.

        >>> [span.text for span in Line.of("1", "hello").spans]
        ['hello']
        """
        return cls(id=key, spans=[Span(text=text, tone=tone)])

    def said(self) -> str:
        """Say the line as text."""
        return "".join(span.text for span in self.spans)


class Markdown(Model):
    """Text the page shows as Markdown, in a tone; its text form is the Markdown itself."""

    block: Literal["markdown"] = "markdown"
    id: str
    version: str | None = None
    """The version of what it shows, which a comment written on it records so
    the agent is told what changed since: a file's, as git names its content;
    none where the page goes by its text."""
    offers: list[Offer] = []
    """What it offers the operator to do with what it shows, each answering a
    verb's key or a chord of its own (`Offer`)."""
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
    version: str | None = None
    """The version of what it shows, which a comment written on it records so
    the agent is told what changed since: a file's, as git names its content;
    none where the page goes by its text."""
    offers: list[Offer] = []
    """What it offers the operator to do with what it shows, each answering a
    verb's key or a chord of its own (`Offer`)."""
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


class FileText(Model):
    """A side of a file, as text."""

    kind: Literal["text"] = "text"
    text: str


class FileBytes(Model):
    """A side of a file that isn't text, which isn't shown: its size alone."""

    kind: Literal["binary"] = "binary"
    size: int
    """In bytes."""


type FileContent = Annotated[FileText | FileBytes, Field(discriminator="kind")]
"""What one side of a file holds, as a `Diff` shows it: as the inbox keeps a
changed file's, so the one reads as the other."""


class Mark(Model):
    """A stretch of a file's lines that matters, and what it triggered: said at the end of its first line, each of its lines barred in the colour of how it's taken."""

    taken: Literal["held", "flagged", "told"]
    """Held for the operator's answer, flagged for their review, or told to the
    agent alone."""
    said: str
    """What it triggered, said after how it's taken at its first line's end:
    `adds an ignore`."""
    side: Literal["before", "after"] = "after"
    """Which side of a `Diff` its lines are counted in: what the file becomes,
    or, for lines the change removes, what it was."""
    first: int | None = None
    """Its first line, counted from 1 on its side; none for what's about the
    file whole, which makes its header matter."""
    last: int | None = None
    """Its last line, where it marks a stretch: those of its lines shown are
    marked, and nothing where none is; none for its first line alone, which
    makes the header matter where no line shows it."""


class Diff(Model):
    """A file's change, shown whole: what it becomes, each line it removes in place, the runs of unchanged lines far from a change folding, each function's and class's body folding under the line declaring it, and what matters marked (`Mark`).

    Its header says the file's path and what the change did to it (created,
    deleted, or how many lines it adds and removes), then what it `says`. Its
    fold is of the shell's `file` kind, its bodies' of `body`, its runs' of
    `lines` (`SHELL_FOLDS`).
    """

    block: Literal["diff"] = "diff"
    id: str
    version: str | None = None
    """The version of what it shows, which a comment written on it records so
    the agent is told what changed since: a file's, as git names its content;
    none where the page goes by its text."""
    offers: list[Offer] = []
    """What it offers the operator to do with what it shows, each answering a
    verb's key or a chord of its own (`Offer`)."""
    path: str
    """From the root of the worktree or the repository it's in."""
    before: FileContent | None = None
    """What it held; none for a file the change creates."""
    after: FileContent | None = None
    """What it holds once changed; none for a file the change deletes."""
    says: list[str] = []
    """What its header says after what the change did to it: why it's open, or
    why it folds whole under its header (`test`)."""
    marks: list[Mark] = []
    open: bool = True
    """Whether it's open under its header; folded whole where not, as a test or
    a file asking nothing."""
    automatic: bool = False
    """Whether it asks the operator nothing, held or flagged: its header is set
    back."""
    design: bool = False
    """Whether its bodies fold until opened, so its design shows, as a new
    module's does: but a body holding a line that matters."""

    def rows(self) -> list[Row]:
        r"""Return its lines as the page shows them: what it becomes, each line it removes in place before those replacing it.

        >>> diff = Diff(id="a.py", path="a.py", before=FileText(text="a\nb\n"),
        ...     after=FileText(text="a\nc\n"))
        >>> [(row.change, row.text) for row in diff.rows()]
        [('same', 'a'), ('removed', 'b'), ('added', 'c')]
        """
        before = sides(self.before)
        after = sides(self.after)
        matched = SequenceMatcher(a=before, b=after, autojunk=False)

        def shown() -> Iterator[Row]:
            for tag, i, j, k, m in matched.get_opcodes():
                if tag == "equal":
                    yield from (
                        Row(change="same", side="after", number=at + 1, text=after[at])
                        for at in range(k, m)
                    )
                    continue
                yield from (
                    Row(change="removed", side="before", number=at + 1, text=before[at])
                    for at in range(i, j)
                )
                yield from (
                    Row(change="added", side="after", number=at + 1, text=after[at])
                    for at in range(k, m)
                )

        return list(shown())

    def header(self) -> str:
        r"""Say its header: the file's path, what the change did to it, then what it says.

        >>> Diff(id="a", path="a.py", after=FileText(text="x\n"), says=["new file"]).header()
        'a.py · created · 1 line · new file'
        >>> Diff(id="b", path="b.png", before=FileBytes(size=1200),
        ...     after=FileBytes(size=1300)).header()
        'b.png · changed · binary, not shown · 1,200 bytes → 1,300 bytes'
        """

        def sized(side: FileContent | None) -> str:
            return f"{side.size:,} bytes" if isinstance(side, FileBytes) else "none"

        def told(rows: list[Row]) -> str:
            match self.before, self.after:
                case FileBytes(), None:
                    return f"deleted · binary, not shown · {sized(self.before)}"
                case None, FileBytes():
                    return f"created · binary, not shown · {sized(self.after)}"
                case (FileBytes(), _) | (_, FileBytes()):
                    sizes = f"{sized(self.before)} → {sized(self.after)}"
                    return f"changed · binary, not shown · {sizes}"
                case None, _:
                    return f"created · {counted(len(rows), 'line')}"
                case _, None:
                    return f"deleted · {counted(len(rows), 'line')}"
                case _:
                    added = sum(row.change == "added" for row in rows)
                    removed = sum(row.change == "removed" for row in rows)
                    if added + removed == 0:
                        return "changed · no line differs"
                    return f"changed · +{added} \N{MINUS SIGN}{removed}"

        return " · ".join([f"{self.path} · {told(self.rows())}", *self.says])

    def said(self, indent: str = "") -> list[str]:
        r"""Say the change as text, each line after `indent`: its header, marked open or closed, then, open, each of its lines after how the change takes it, what matters said at its end.

        >>> diff = Diff(id="a.py", path="a.py", after=FileText(text="a\nb\n"),
        ...     marks=[Mark(taken="held", said="adds an ignore", first=2)])
        >>> print("\n".join(diff.said()))
        ▾ a.py · created · 2 lines
          + a
          + b  ◂ held: adds an ignore
        """
        head = [f"{indent}{'▾' if self.open else '▸'} {self.header()}"]
        if not self.open:
            return head
        signs = {"added": "+", "removed": "-", "same": " "}
        return [
            *head,
            *(
                f"{indent}  {signs[row.change]} {row.text}{noted(self.marks, row)}"
                for row in self.rows()
            ),
        ]


class Code(Model):
    """A file shown whole as it stands: each function's and class's body folding under the line declaring it, and what matters marked (`Mark`).

    Its header says the file's path and how many lines it has, then what it
    `says`. Its fold is of the shell's `file` kind, its bodies' of `body`
    (`SHELL_FOLDS`).
    """

    block: Literal["code"] = "code"
    id: str
    version: str | None = None
    """The version of what it shows, which a comment written on it records so
    the agent is told what changed since: a file's, as git names its content;
    none where the page goes by its text."""
    offers: list[Offer] = []
    """What it offers the operator to do with what it shows, each answering a
    verb's key or a chord of its own (`Offer`)."""
    path: str
    """From the root of the worktree or the repository it's in."""
    text: str
    says: list[str] = []
    """What its header says after how many lines the file has."""
    marks: list[Mark] = []
    open: bool = True
    """Whether it's open under its header; folded whole where not."""
    design: bool = False
    """Whether its bodies fold until opened, so its design shows: but a body
    holding a line that matters."""

    def said(self, indent: str = "") -> list[str]:
        r"""Say the file as text, each line after `indent`: its header, marked open or closed, then, open, each of its lines, what matters said at its end.

        >>> print("\n".join(Code(id="a", path="a.py", text="a = 1\n").said()))
        ▾ a.py · 1 line
            a = 1
        """
        rows = [
            Row(change="same", side="after", number=at + 1, text=text)
            for at, text in enumerate(self.text.splitlines())
        ]
        header = " · ".join([self.path, counted(len(rows), "line"), *self.says])
        head = [f"{indent}{'▾' if self.open else '▸'} {header}"]
        if not self.open:
            return head
        return [
            *head,
            *(f"{indent}    {row.text}{noted(self.marks, row)}" for row in rows),
        ]


class Row(Model):
    """One line of a file as a `Diff` or a `Code` shows it: how the change takes it, the side it's counted in, its number there from 1, and its text."""

    change: Literal["added", "removed", "same"]
    side: Literal["before", "after"]
    number: int
    text: str


def counted(count: int, one: str) -> str:
    """Say how many of a thing there are: `1 line`, `5 lines`."""
    return f"{count} {one}{'' if count == 1 else 's'}"


def sides(side: FileContent | None) -> list[str]:
    """Return the lines of a side of a file shown as text; none where it isn't there, or isn't text."""
    return side.text.splitlines() if isinstance(side, FileText) else []


def noted(marks: list[Mark], row: Row) -> str:
    """Say, at the end of `row`, what the marks starting on it triggered, each after how it's taken; nothing where none starts there."""
    said = " · ".join(
        f"{mark.taken}: {mark.said}"
        for mark in marks
        if mark.first == row.number
        and mark.side == row.side
        and (mark.side == "after" or row.change == "removed")
    )
    return f"  ◂ {said}" if said else ""


type Block = Annotated[
    Line | Markdown | Fold | Diff | Code, Field(discriminator="block")
]
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
            case Fold() | Diff() | Code():
                return block.said(indent)

    return [line for block in blocks for line in said(block)]


class Blocks(Model):
    """What a view answers: its blocks, and, for a drawer, the summary line under its banner."""

    blocks: list[Block] = []
    summary: list[Span] = []
    """A drawer's line under its banner, in its kind's colour; a banner part's
    words on the banner's line; an item kind's words in its item's header,
    before the state words the core adds (`edited`, `new`, how long it has
    waited); none for a view nothing shows a line of."""
    waiting: bool = False
    """Whether it holds what waits on the operator: its summary line is bold."""
    count: int = 0
    """How many of what it holds wait on the operator, said beside its agent in
    the overview (`◇3`): none where nothing does."""
    offers: list[Offer] = []
    """What the view offers as a whole, as a drawer marking every file it
    shows reviewed: what a verb's key does where no block within offers it."""

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
                case Diff() | Code():
                    return []
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
    """The key after `zf` toggling the one the cursor is in, and after Space
    `f` selecting every one, fold-wise: two kinds of a repository's modules
    taking one letter fail the load."""
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
    chord: bool = True
    """Whether Space `f` and its letter select every one of them in the scope
    the cursor is in, fold-wise, Space `F` and the letter in the whole review:
    an item's own fold is folded by `za` on its header, and marked from it,
    alone."""
    whole: bool = False
    """Whether it's the fold holding its scope whole, as an item's or a group's
    does under its header: `zm` and `zM` never close it."""
    counts: bool = True
    """Whether one folded says how many lines it hides after its summary line:
    one whose summary says what it hides doesn't (`6 unchanged lines`)."""
    keeps_open: int | None = Field(default=None, ge=1)
    """How many of what its module counts stay open after its folds at most,
    what came before them folded under one of them (`kept_open`): the last 20
    of the agent's words in a conversation, so a long one's view stays small
    however long it runs. A person's layer changes it as any field of the
    module's; none keeps everything open."""
    starts_open: bool | None = None
    """Whether its folds start open, until the operator opens or closes one:
    none, as each one's view lays it out, a test file folded whole, a run of
    unchanged lines folded, a body open; true or false, every one of its kind,
    whatever its view says. Marking something done still folds it. A person's
    layer changes it as any field of the module's."""
    by_all: bool = True
    """Whether `zR` and `zM`, which open and close every fold of the item or
    the drawer the cursor is in, reach it: one they don't, as runs of
    unchanged lines a person keeps closed, is opened by `zr`, `za` and its own
    keys still."""


class Kept[T](Model):
    """A run of things split where what's kept open starts: those folded under one line before, the first of them those the operator had reviewed, and those shown."""

    folded: list[T]
    shown: list[T]
    reviewed: int = 0
    """How many of `folded`, from the first, came before the operator's review
    mark: those after them, up to `shown`, are new to them, folded only to keep
    the view small."""


def kept_open[T](
    things: list[T], counted: Callable[[T], bool], most: int | None, reviewed: int = 0
) -> Kept[T]:
    """Split `things`, in order, where what's kept open starts: the first `reviewed`, those before the operator's review mark, folded whatever comes after; and of the rest, the last `most` that `counted` counts, from the earliest of them on, and everything after it, shown, what came before folded too. Nothing more is folded where `most` is none, or no more are counted.

    What a view keeps open of a long run: what came after the operator last
    reviewed it, open and new to them, but at most as much as its fold kind
    keeps open (`FoldKind.keeps_open`), so one left unreviewed for long doesn't
    fill the screen; and what came before, folded under one line saying how
    much, read as it opens. Every module folds what came before its marks
    through it, so a view's text form, which its command prints and agents
    read, folds where the operator's page does.

    >>> kept = kept_open(["you", "a", "call", "b", "call", "c"], lambda each: len(each) == 1, 2)
    >>> kept.folded, kept.shown
    (['you', 'a', 'call'], ['b', 'call', 'c'])
    >>> kept_open(["a", "b"], lambda each: True, 2).folded
    []
    >>> read = kept_open(["a", "b", "c", "d"], lambda each: True, 5, reviewed=2)
    >>> read.folded, read.shown, read.reviewed
    (['a', 'b'], ['c', 'd'], 2)
    >>> kept_open(["a", "b", "c", "d"], lambda each: True, 1, reviewed=2).folded
    ['a', 'b', 'c']
    """
    before = min(max(reviewed, 0), len(things))
    after = things[before:]
    at = [index for index, each in enumerate(after) if counted(each)]
    if most is None or len(at) <= most:
        cut = 0
    else:
        cut = at[len(at) - most] if most > 0 else len(after)
    return Kept(
        folded=things[: before + cut], shown=things[before + cut :], reviewed=before
    )


SHELL_FOLDS = [
    FoldKind(
        name="group",
        letter="a",
        called="agents' groups",
        one="the agent's group",
        level=0,
        colour="cyan",
        whole=True,
    ),
    FoldKind(
        name="item",
        letter="i",
        called="the item",
        one="the item",
        level=0,
        colour="orange",
        chord=False,
        whole=True,
    ),
    FoldKind(
        name="file", letter="f", called="files", one="the file", level=1, colour="info"
    ),
    FoldKind(
        name="body",
        letter="b",
        called="bodies",
        one="the body",
        level=2,
        colour="purple",
    ),
    FoldKind(
        name="lines",
        letter="u",
        called="unchanged lines",
        one="the unchanged lines",
        level=2,
        colour="muted",
        counts=False,
    ),
    FoldKind(
        name="context",
        letter="c",
        called="context",
        one="the context",
        level=3,
        colour="cyan",
        counts=False,
    ),
]
"""The fold kinds of the shell, which every repository's looks carry and no
module's letter may take: an agent's group whole under its banner, an item
whole under its header, and an item's context, the core's; a file, a body and a
run of unchanged lines, which `Diff` and `Code` fold under. `Core` declares
them (`Core.folds`), so a person's layer changes how each starts and whether
`zR` and `zM` reach it."""


class Drawer(Model):
    """Where a view is placed: a drawer under each agent's banner, its line in the banner's group saying what it holds."""

    under: Literal["agent"] = "agent"
    letter: str
    """Its fold kind's letter, which opens and closes it."""
    called: str
    """What it's called: `the conversation`."""
    colour: Colour


class Banner(Model):
    """Where a view is placed: on each agent's banner, its answer's summary a part of the banner's line, after what the core says of the agent.

    A part says what's said rather than drawn: what ticks (`Ticking`) and what
    measures (`Gauge`) are spans the page says again as they change; its
    blocks are left for what's drawn on the banner rather than said, as an
    embed would be.
    """

    under: Literal["agent"] = "agent"


class Watch(Model):
    """When a view the page shows is answered again: at these events of what it's of, and this long apart at most."""

    on: list[type[Event]] = []
    """The events, of the agent a drawer is under, after which it's answered
    again."""
    longest: timedelta | None = None
    """The longest it goes unanswered, for what no event says; none waits for
    the events alone."""


class OfAgent(Model):
    """The agent a drawer under their banner is of: their runtime, their session, and which subagent they are where they're one.

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
