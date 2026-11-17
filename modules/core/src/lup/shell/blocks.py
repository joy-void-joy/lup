"""The blocks a module's views are laid out from, and what a view answers: `Blocks`.

A module's Python lays out each of its views from these, and the dashboard's page
only draws them: so a module needs no TypeScript for what it shows, every view is
drawn, folded and commented on the same way, and a view's text form, which its
command prints and agents read, comes from the same blocks (`Blocks.text`), so an
agent reads what the operator saw (`README.md` here, *Blocks*).

They hold nothing of any module: a span that names something another view
shows refers to that view (`Viewing`), a mark on a file's lines is of a kind its
module declares (`MarkKind`), and who a comment on a block reaches is a party
(`Shown.reaches`).
"""

from datetime import datetime
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field, JsonValue, SerializeAsAny

from lup.doors.action import ActionDoor
from lup.doors.door import Annotation, is_model
from lup.doors.parties import Party
from lup.errors import LupError
from lup.types import Model

if TYPE_CHECKING:
    from collections.abc import Iterator

    from lup.doors.door import Method

lazy from lup.shell.draft import Commenting
lazy from lup.shell.view import ViewDoor


class BlockError(LupError):
    """A block can't say what it was asked to: it offers what isn't an action, or reads what isn't a view, or not with what it takes."""


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


class Viewing(Model):
    """A view, and what it's given: what a span refers to, and what a fold reads as it opens.

    The shell knows nothing of what a view shows: following a span that names
    a concern, an agent or a file opens the view that shows it.
    """

    module: str | None = None
    """The module serving the view, by its name; none for the module whose view
    names it."""
    view: str
    """The view's name: its method's."""
    given: dict[str, JsonValue] = {}
    """What the view takes, as JSON."""

    @classmethod
    def of(
        cls, view: Method, given: BaseModel, *, module: str | None = None
    ) -> Viewing:
        """Return `view`, a view read through its class, given `given`; of the module named `module`, where it's another's than the view naming it.

        Raise `BlockError` where `view` isn't a view, or doesn't take `given`'s type.
        """
        if not isinstance(view.door, ViewDoor):
            message = f"a block reads `{view.taken.name}`, which isn't a view"
            raise BlockError(message, about=[view.taken.qualified])
        taken = view.taken.given().annotation
        if not (is_model(taken) and isinstance(given, taken)):
            message = (
                f"a block reads `{view.taken.name}` with a `{type(given).__name__}`, "
                "which it doesn't take"
            )
            raise BlockError(message, about=[view.taken.qualified])
        return cls(
            module=module, view=view.taken.name, given=given.model_dump(mode="json")
        )

    def said(self) -> str:
        """Say the view and what it's given, as a fold read as it opens says them, so a reader knows which view's command shows it.

        >>> Viewing(module="piles", view="concern", given={"number": 12}).said()
        'piles concern number=12'
        """
        given = " ".join(
            f"{key}={value}" for key, value in self.given.items() if value is not None
        )
        return " ".join(part for part in [self.module, self.view, given] if part)


class Span(Model):
    """A run of a line's text, in a tone, and what it says beyond its text, where it does: a time, a measure, or a view it refers to."""

    text: str
    tone: str = "plain"
    """One of the shell's tones (`SHELL_TONES`), or one its module declares."""
    ticking: Ticking | None = None
    """How it says the time since a moment: its text is what it said as the
    view was answered, and the page says it again as the time passes, so
    nothing is answered again for a clock."""
    gauge: Gauge | None = None
    """What it measures, as a context's tokens of its window: its text says
    it, and the page may draw it."""
    refers: Viewing | None = None
    """The view its text names, which following it opens: a concern, an agent,
    a file."""


class Offer(Model):
    """What a block offers the operator to do with what it shows: one of its module's actions, what it's given, and the verb whose key reaches it.

    A verb's key, Space and its letter, does what the innermost block under the
    cursor offering that verb offers, so one key marks a file reviewed or clears
    a concern, as the block it's on says.
    """

    action: str
    """The action, by its method's name."""
    module: str | None = None
    """The module serving it, by its name; none for the module whose view
    offers it."""
    given: dict[str, JsonValue] = {}
    """What the action is given, as JSON."""
    verb: str
    """The verb whose key reaches it: the action's own."""
    says: str
    """What it does, as the line of keys says it after its key: `clear it`."""
    draws: str | None = None
    """What the first characters of its block's line read while it's marked,
    in place of what they read: a box ticked (`[x]`) rather than a line struck
    through; none draws the mark as its verb's."""

    @classmethod
    def of(
        cls,
        action: Method,
        given: BaseModel,
        *,
        says: str | None = None,
        draws: str | None = None,
    ) -> Offer:
        """Return the offer of `action`, an action read through its class, given `given`: its verb and what it does are the action's own, what the block offering it says closer to what it's on (`says`), and what its line reads marked (`draws`).

        An action taking `Commented[G]`, as one offered under the `comment` verb
        does, is given a `G`, the comment written with it as it's sent. Raise
        `BlockError` where `action` isn't an action, or doesn't take `given`'s type.
        """
        door = action.door
        if not isinstance(door, ActionDoor):
            message = f"a block offers `{action.taken.name}`, which isn't an action"
            raise BlockError(message, about=[action.taken.qualified])
        one = commented_on(action.taken.one())
        if not (is_model(one) and isinstance(given, one)):
            message = (
                f"a block offers `{action.taken.name}` with a "
                f"`{type(given).__name__}`, which it doesn't take"
            )
            raise BlockError(message, about=[action.taken.qualified])
        return cls(
            action=action.taken.name,
            given=given.model_dump(mode="json"),
            verb=door.verb,
            says=door.says if says is None else says,
            draws=draws,
        )


def commented_on(taken: Annotation) -> Annotation:
    """Return what an action taking `taken` is offered with: `G` for `Commented[G]`, as a comment action takes, else `taken` itself.

    >>> from lup.types import Model
    >>> class OnItem(Model):
    ...     item: int
    >>> from lup.shell.draft import Commented
    >>> commented_on(Commented[OnItem]) is OnItem, commented_on(OnItem) is OnItem
    (True, True)
    """
    match taken:
        case type() if issubclass(taken, Commenting):
            given: type[BaseModel] = taken.__pydantic_generic_metadata__["args"][0]
            return given
        case _:
            return taken


class Shown(Model):
    """What every block has: the id its module keeps from one answer to the next, the version of what it shows, what it offers, and who a comment on it reaches.

    The page keeps a fold open, the cursor and a comment where they were by the
    block's id, so a module chooses one that stays put as its view changes, as
    a step's number or a call's id.
    """

    id: str
    version: str | None = None
    """The version of what it shows, which a comment written on it records, so
    its party is told what changed since: a file's as git names its content;
    none where the page goes by its text."""
    offers: list[Offer] = []
    """What it offers the operator to do with what it shows, each under its
    verb's key."""
    reaches: SerializeAsAny[Party] | None = None
    """The party a comment on it reaches; none for whoever the block it's in
    says, and none at all where nothing does, so it takes no comment."""


class Line(Shown):
    """One line of text, in spans."""

    block: Literal["line"] = "line"
    spans: list[Span] = []

    @classmethod
    def of(cls, key: str, text: str, tone: str = "plain") -> Line:
        """Return a line of `text` in one tone, its id `key`.

        >>> Line.of("1", "hello").said()
        'hello'
        """
        return cls(id=key, spans=[Span(text=text, tone=tone)])

    def said(self) -> str:
        """Say the line as text."""
        return "".join(span.text for span in self.spans)


class Markdown(Shown):
    """Text the page shows as Markdown, in a tone; its text form is the Markdown itself."""

    block: Literal["markdown"] = "markdown"
    text: str
    tone: str = "plain"


class Fold(Shown):
    """A summary line, and what folds under it, of a fold kind: its content given, or read from a view as it opens.

    Whether it starts open is its kind's (`FoldKind.starts_open`), but where its
    view says otherwise, as a call that failed opened by its module.
    """

    block: Literal["fold"] = "fold"
    kind: str
    """A fold kind, by its name: one of the shell's (`SHELL_FOLDS`), or one its
    module declares."""
    summary: list[Span]
    open: bool | None = None
    """Whether it's open; none for as its kind says."""
    content: list[Block] | Viewing = []
    """What's under it: given, or read from a view as it opens, so a long view
    sends only what's open."""

    def said(self, indent: str = "", *, opened: bool) -> list[str]:
        """Say the fold as text, each line after `indent`: its summary, marked open or closed, then, open, its content, indented further.

        Content read as it opens isn't said: its summary is, with the view it
        reads, so a reader knows which view's command shows it.

        >>> loaded = Viewing(view="call", given={"call": "c1"})
        >>> Fold(id="1", kind="call", summary=[Span(text="Bash: ls")], content=loaded).said(opened=False)
        ['▸ Bash: ls  [call call=c1]']
        """
        summary = "".join(span.text for span in self.summary)
        if isinstance(self.content, Viewing):
            return [f"{indent}▸ {summary}  [{self.content.said()}]"]
        if not opened:
            return [f"{indent}▸ {summary}"]
        return [f"{indent}▾ {summary}", *lines(self.content, f"{indent}  ")]


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
"""What one side of a file holds, as a `Diff` shows it."""


class Mark(Model):
    """A stretch of a file's lines that matters, of a mark kind its module declares, and what it says: said at the end of its first line, each of its lines barred in its kind's colour."""

    kind: str
    """A mark kind its module declares (`MarkKind`), by its name."""
    says: str
    """What it says after its kind's word at its first line's end: `adds an ignore`."""
    side: Literal["before", "after"] = "after"
    """Which side of a `Diff` its lines are counted in: what the file becomes,
    or, for lines the change removes, what it was."""
    first: int
    """Its first line, counted from 1 on its side."""
    last: int | None = None
    """Its last line, where it marks a stretch; none for its first line alone."""


class Row(Model):
    """One line of a file as a `Diff` or a `Code` shows it: how the change takes it, the side it's counted in, its number there from 1, and its text."""

    change: Literal["added", "removed", "same"]
    side: Literal["before", "after"]
    number: int
    text: str

    def noted(self, marks: list[Mark]) -> str:
        """Say, at the row's end, what the marks starting on it say, each after its kind; nothing where none starts there."""
        said = " · ".join(
            f"{mark.kind}: {mark.says}"
            for mark in marks
            if mark.first == self.number
            and mark.side == self.side
            and (mark.side == "after" or self.change == "removed")
        )
        return f"  ◂ {said}" if said else ""


def counted(count: int, one: str) -> str:
    """Say how many of a thing there are.

    >>> counted(1, "line"), counted(5, "line")
    ('1 line', '5 lines')
    """
    return f"{count} {one}{'' if count == 1 else 's'}"


def sides(side: FileContent | None) -> list[str]:
    """Return the lines of a side of a file shown as text; none where it isn't there, or isn't text."""
    return side.text.splitlines() if isinstance(side, FileText) else []


class Code(Shown):
    """A file shown whole as it stands, under a fold of the shell's `file` kind: each function's and class's body folding under the line declaring it, in the shell's `body` kind, and what matters marked (`Mark`)."""

    block: Literal["code"] = "code"
    path: str
    """From the root of the worktree or the repository it's in."""
    text: str
    says: list[str] = []
    """What its header says after how many lines the file has."""
    marks: list[Mark] = []
    open: bool | None = None
    """Whether it's open under its header; none for as the `file` kind says."""

    def said(self, indent: str = "", *, opened: bool) -> list[str]:
        r"""Say the file as text, each line after `indent`: its header, marked open or closed, then, open, each of its lines, what its marks say at their first line's end.

        >>> print("\n".join(Code(id="a", path="a.py", text="a = 1\n").said(opened=True)))
        ▾ a.py · 1 line
            a = 1
        """
        rows = [
            Row(change="same", side="after", number=at + 1, text=text)
            for at, text in enumerate(self.text.splitlines())
        ]
        header = " · ".join([self.path, counted(len(rows), "line"), *self.says])
        if not opened:
            return [f"{indent}▸ {header}"]
        return [
            f"{indent}▾ {header}",
            *(f"{indent}    {row.text}{row.noted(self.marks)}" for row in rows),
        ]


class Diff(Shown):
    """A file's change, shown whole under a fold of the shell's `file` kind: what it becomes, each line it removes in place, the runs of unchanged lines far from a change folding in the shell's `lines` kind, each body in its `body` kind, and what matters marked (`Mark`)."""

    block: Literal["diff"] = "diff"
    path: str
    """From the root of the worktree or the repository it's in."""
    before: FileContent | None = None
    """What it held; none for a file the change creates."""
    after: FileContent | None = None
    """What it holds once changed; none for a file the change deletes."""
    says: list[str] = []
    """What its header says after what the change did to it."""
    marks: list[Mark] = []
    open: bool | None = None
    """Whether it's open under its header; none for as the `file` kind says."""

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

    def said(self, indent: str = "", *, opened: bool) -> list[str]:
        r"""Say the change as text, each line after `indent`: its header, marked open or closed, then, open, each of its lines after how the change takes it, what its marks say at their first line's end.

        >>> diff = Diff(id="a.py", path="a.py", after=FileText(text="a\nb\n"),
        ...     marks=[Mark(kind="held", says="adds an ignore", first=2)])
        >>> print("\n".join(diff.said(opened=True)))
        ▾ a.py · created · 2 lines
          + a
          + b  ◂ held: adds an ignore
        """
        if not opened:
            return [f"{indent}▸ {self.header()}"]
        signs = {"added": "+", "removed": "-", "same": " "}
        return [
            f"{indent}▾ {self.header()}",
            *(
                f"{indent}  {signs[row.change]} {row.text}{row.noted(self.marks)}"
                for row in self.rows()
            ),
        ]


type Block = Annotated[
    Line | Markdown | Fold | Code | Diff, Field(discriminator="block")
]
"""One of the blocks."""


def lines(blocks: list[Block], indent: str = "") -> list[str]:
    """Say `blocks` as lines of text, each after `indent` but a blank one, a fold whose open state its view leaves to its kind said open."""

    def said(block: Block) -> list[str]:
        match block:
            case Line():
                return [f"{indent}{block.said()}"]
            case Markdown():
                return [
                    f"{indent}{line}" if line else ""
                    for line in block.text.splitlines()
                ]
            case Fold() | Code() | Diff():
                return block.said(indent, opened=block.open is not False)

    return [line for block in blocks for line in said(block)]


class Blocks(Model):
    """What a view answers: its blocks, the summary line said of it where it's folded or listed, and what it offers as a whole."""

    blocks: list[Block] = []
    summary: list[Span] = []
    """What's said of the view where it's folded or listed, as in the outline;
    none where it's never said in a line."""
    offers: list[Offer] = []
    """What the view offers as a whole: what a verb's key does where no block
    within offers it."""

    @classmethod
    def of(cls, *blocks: Block, summary: list[Span] | None = None) -> Blocks:
        """Return a view of `blocks`, said in `summary` where it's folded or listed.

        >>> len(Blocks.of(Line.of("1", "a"), Line.of("2", "b")).blocks)
        2
        """
        return cls(blocks=list(blocks), summary=summary or [])

    def text(self) -> str:
        """Say the view as text, as its command prints it and an agent reads it: its summary, then its blocks, a fold closed as its view says as its summary line.

        >>> view = Blocks(summary=[Span(text="conversation · 2 steps")],
        ...     blocks=[Line.of("1", "you: hi"),
        ...         Fold(id="2", kind="calls", summary=[Span(text="called Bash, Read")],
        ...             open=False, content=[Line.of("3", "Bash: ls")])])
        >>> print(view.text())
        conversation · 2 steps
        you: hi
        ▸ called Bash, Read
        """
        summary = "".join(span.text for span in self.summary)
        return "\n".join([*([summary] if summary else []), *lines(self.blocks)])

    def every(self) -> list[Block]:
        """Return every block the view holds, a fold's given content among them, in the order they're shown."""

        def within(block: Block) -> list[Block]:
            match block:
                case Fold(content=list() as content):
                    return [block, *(each for one in content for each in within(one))]
                case _:
                    return [block]

        return [each for block in self.blocks for each in within(block)]
