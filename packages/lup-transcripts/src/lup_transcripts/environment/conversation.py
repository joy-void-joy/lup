"""A conversation laid out in lup's building blocks: the drawer under its agent's banner, one earlier exchange, and one call read whole.

`docs/dashboard.md`, *The drawers*, its **Conversation** entry. Each is a pure
layout answering `Blocks`, the layout of one of `Transcripts`' views:
- `conversation_blocks`, the drawer: its summary line counting the steps and
  those new to the operator, each exchange before their last words folded under
  the first line of their words that opened it, the latest open under its own,
  what came before their first words under a line of its own, and everything
  since they last read it open and new, from the drawer's review mark or their
  own last words, whichever is later (`Read`), but for at most the agent's last
  20 words (`EARLIER_KIND.keeps_open`) with what follows them, what came before
  folded under one line saying how much (`capped`);
- `exchange_blocks`, one earlier exchange's steps, or those its fold of what
  came before the agent's last words holds, or what the operator had read of
  the latest, which the fold reads as it opens (`OfExchange`), itself capped
  the same way, so the drawer's answer stays small however long the
  conversation grows, and each fold opened brings in 20 more of the agent's
  words;
- `call_blocks`, one call as its fold reads it as it opens (`OfCall`), since a
  call is read from the record only on asking: what it was given, straight away,
  each long argument and what it returned folded under a line of its own, each
  read whole as that opens.

Within an exchange, the operator's words come after `you:`, each of the agent's
words as Markdown folded under a line saying how they start, open but for a
turn's last words, which the review shows as an item and which fold under its
line; each call as a line saying what it was given (`Called.gist`), a run of
calls under one line saying how many of which, and each item of lup's inbox the
conversation sent or was sent as a line where it happened, its text folded under
it (`merged`). A call whose sending an item is all it did goes under that item's
line (`turned`). Each such line is one row (`cut`).

Each block's id names what it shows, so it stays from one answer to the next as
the conversation grows, and a fold's id is never a line's: a fold is
`exchange 5` (or `exchange before`), `exchange 5 until last 20` for what came
before the agent's last 20 words in it, `exchange 5 through 40` for what the
operator had read of it up to step 40, `said 6` for the agent's words at step 6,
`calls 2`, `call <the call's id>` or `item 51`; a line is `step 6` (`step 6.1` on, for the
operator's further lines), `item 64 line` for an item with no text, `text 51` for
an item's text, and in a call's view, `input <id> <name>` for an argument
(`.1` on), `output <id>` where it returned nothing or hasn't yet, and `unread <id>`,
its folds `argument <id> <name>` and `output <id>` read as lines `.1` on. The
agent's words are a block `step 6` under their fold, so a comment on them stays on
them whether they're open or folded.
"""

import json
import textwrap
from collections import Counter
from datetime import datetime
from itertools import accumulate, groupby, pairwise
from math import ceil
from typing import TYPE_CHECKING

from pydantic import Field

from lup.blocks import (
    Block,
    Blocks,
    Fold,
    FoldKind,
    Line,
    Load,
    Markdown,
    OfAgent,
    Offer,
    Span,
    Tone,
    kept_open,
)
from lup.types import Model
from lup_dev.host.records import Called, Entry, Said
from lup_transcripts.errors import LupTranscriptsError

if TYPE_CHECKING:
    from pydantic import JsonValue

    from lup.doors import Method
    from lup_dev.host.records import Call
    from lup_dev.inbox.marks import ReviewMark
    from lup_dev.inbox.protocol import Exchange, Exchanged


CALL_TONE = Tone(name="call", colour="orange")
"""A call's line, saying what it was given."""
SENT_TONE = Tone(name="sent", like="call")
"""An item the conversation sent: in the orange of the call that made it."""
RECEIVED_TONE = Tone(name="received", like="operator")
"""An item the conversation was sent: in the blue of the operator's words."""
RUN_TONE = Tone(name="run", like="muted")
"""A run of calls' line, saying how many of which."""

TONES = [CALL_TONE, SENT_TONE, RECEIVED_TONE, RUN_TONE]
"""The tones `Transcripts` declares beside the shell's, which its conversation's
lines are drawn in; the operator's words are in the shell's `operator`, and
what's set back in its `muted`."""

EARLIER_KIND = FoldKind(
    name="earlier",
    letter="e",
    called="earlier exchanges and steps",
    one="what came earlier",
    level=1,
    opens="back",
    colour="ok",
    keeps_open=20,
)
"""Each exchange before the operator's last words, under the first line of their
words that opened it, and, in an exchange, what came before the agent's last 20
words in it, under one line saying how much: `zr` opens the latest still
folded, each one a step further back. A person's layer keeps more or fewer of
the agent's words open (`keeps_open`; `packages/lup-transcripts/README.md`,
*The conversation, live*)."""
ITEMS_KIND = FoldKind(
    name="items",
    letter="m",
    called="messages",
    one="the message",
    level=2,
    colour="cyan",
)
"""A message: the agent's words at a step, under a line saying how they start,
open but for those an item repeats; and an item of lup's inbox the conversation
sent or was sent, its text under its line."""
CALLS_KIND = FoldKind(
    name="calls",
    letter="k",
    called="runs of calls",
    one="the run of calls",
    level=3,
    colour="purple",
    counts=False,
)
"""A run of calls, under one line saying how many of which, each a row of its own
set off under it: open, so what the agent did reads without opening anything, and
one key from being skipped, the run's own or, deepest of those `zm` closes, every
run of the drawer at once, its messages still open. A person's layer starts every
run closed (`starts_open`)."""
CALL_KIND = FoldKind(
    name="call",
    letter="d",
    called="calls' input and output",
    one="the call's input and output",
    level=4,
    opens="deep",
    colour="orange",
)
"""A call's input and output, under its line: opened only by its own keys, since
each is read from the record as it opens."""
DETAIL_KIND = FoldKind(
    name="detail",
    letter="x",
    called="calls' outputs and long arguments",
    one="the output or long argument",
    level=5,
    opens="deep",
    colour="muted",
    counts=False,
)
"""What a call returned, and each argument too long to read at a glance, under a
line of its own in an opened call: so opening a call shows what it was given, and
what it returned, however long, is one key further. Opened only by its own keys,
since each is read from the record as it opens; its line says how much it holds."""

FOLD_KINDS = [EARLIER_KIND, ITEMS_KIND, CALLS_KIND, CALL_KIND, DETAIL_KIND]
"""The fold kinds `Transcripts` declares, which its conversation folds under."""


class ConversationError(LupTranscriptsError):
    """An exchange asked for isn't one of the conversation's: the step named isn't the operator's words."""


class OfExchange(OfAgent):
    """One exchange of an agent's conversation, as its fold in the drawer reads it: by the operator's words that open it; or what came in it before the agent's last words, or what the operator had read of it, which its fold of what came earlier reads."""

    step: int | None = Field(
        default=None,
        description="The step of your words that open it; left out, what came before your first words.",
    )
    through: int | None = Field(
        default=None,
        description="Only what came in it up to step `through`, which you had read; left out, as far as it goes.",
    )
    until_last: int | None = Field(
        default=None,
        description="Only what came in it before the agent's last `until_last` words, which show open after it; left out, the exchange whole.",
    )


class OfCall(OfAgent):
    """One call of an agent's conversation, as its fold in the drawer reads it opening: what it was given; or, as a fold of that opens, what it returned, or one argument, whole."""

    id: str = Field(description="The runtime's id for the call.")
    output: bool | None = Field(
        default=None, description="Only what it returned, whole."
    )
    argument: str | None = Field(
        default=None,
        description="Only this argument, whole, by its name; `input` where it was given a text rather than arguments.",
    )


class Inboxed(Model):
    """An item of lup's inbox as the conversation shows it: its line, its text folded under it, and where it goes among the steps."""

    number: int
    sent: bool
    """Whether the conversation sent it, rather than was sent it."""
    line: list[Span]
    """Its line as the core words it, in the tone of its way, each conversation
    it names a span of its own referring to it (`Span.conversation`)."""
    text: str
    """Its text as it's folded under its line, with the operator's comment on
    deciding it after it; empty where there's none."""
    call: str | None = None
    """The call that made it, for one the conversation sent where the record
    keeps the call's id: it goes just after it."""
    call_sends_it: bool = False
    """Whether sending it is all that call did: its line stands for the call's,
    which goes under it (`turned`)."""
    echoes: bool = False
    """Whether it repeats the conversation's own words: it stands for the step
    saying them, where one does (`merged`)."""
    at: datetime
    """When it was told the conversation, or made: where it goes among the steps
    when no call places it."""


class Spoken(Model):
    """Something said at one step: the operator's words, or the agent's."""

    step: int
    said: Said
    repeated: Inboxed | None = None
    """The item repeating the agent's words here, a turn's last words lup made a
    note of, which the review shows as an item: they fold, under its line."""


class Calling(Model):
    """A tool called at one step."""

    step: int
    called: Called


type Turn = Spoken | Calling | Inboxed
"""One step of the conversation, or an item of lup's inbox between its steps."""


class Read(Model):
    """How far the operator has read a conversation: up to the step their review mark on its drawer names, or their own last words typed to it, whichever is later, and when they moved the mark; none read where neither.

    Their words typed to the agent count as a review of what came before them,
    as a comment sent on a file does: they were reading it in the agent's
    terminal.
    """

    step: int | None = None
    """The last step they've read; none where they've read none."""
    marked: datetime | None = None
    """When they moved the drawer's mark, which an item of the inbox told the
    conversation by then is read with; none where they never did."""

    @classmethod
    def of(cls, mark: ReviewMark | None, entries: list[Entry]) -> Read:
        """Return how far the operator has read the conversation of `entries`, by its drawer's review `mark` and their own words in it."""
        typed = [
            step
            for step, entry in enumerate(entries)
            if isinstance(entry, Said) and entry.by == "operator"
        ]
        marked = None if mark is None or mark.up_to is None else int(mark.up_to)
        steps = [*typed, *([] if marked is None else [marked])]
        return cls(
            step=max(steps, default=None), marked=None if mark is None else mark.at
        )

    def covers(self, turn: Turn) -> bool:
        """Say whether the operator has read `turn`: a step up to theirs, an item told by the time they moved the mark."""
        match turn:
            case Inboxed():
                return self.marked is not None and turn.at <= self.marked
            case Spoken() | Calling():
                return self.step is not None and turn.step <= self.step

    def reviewed(self, turns: list[Turn]) -> int:
        """Return how many of `turns`, from the first, the operator has read: up to the first they haven't."""
        return next(
            (at for at, turn in enumerate(turns) if not self.covers(turn)), len(turns)
        )

    def new(self, entries: list[Entry]) -> int:
        """Return how many of the steps of `entries` came after what the operator has read."""
        return len(entries) - (
            0 if self.step is None else min(self.step + 1, len(entries))
        )


class Part(Model):
    """One part of a conversation: an exchange, from the operator's words that open it to their next, or what came before their first words."""

    opening: Spoken | None = None
    """The operator's words that open it; none for what came before their first
    words."""
    turns: list[Turn]
    """What comes after its opening words, in order."""

    def step(self) -> int | None:
        """Return the step of the operator's words that open it, which names it; none for what came before their first words."""
        return None if self.opening is None else self.opening.step

    def key(self) -> str:
        """Return its fold's id in the drawer."""
        step = self.step()
        return "exchange before" if step is None else f"exchange {step}"


def cut(line: str, width: int = 100) -> str:
    """Say `line` in at most `width` characters, at a word where it can, marked where it's cut: 100 keeps a line saying what's folded under it, a call's or a message's, to one row of the review in a window 1280 pixels wide, the overview and the margin beside it (`docs/dashboard.md`, *The page*); what's cut is whole under its fold.

    >>> cut("Found the four kinds of line.", 16)
    'Found the four…'
    >>> cut("short", 16)
    'short'
    """
    return textwrap.shorten(line, width, placeholder="…")


def kept(text: str) -> list[str]:
    r"""Return the lines `text` is shown in: each without its trailing space, one blank line between paragraphs, none before the first or after the last.

    >>> kept("\nTwenty kinds of line.\n\n\nFour carry what was said.  \n")
    ['Twenty kinds of line.', '', 'Four carry what was said.']
    """
    lines = [line.rstrip() for line in text.splitlines()]
    paragraphs = [
        list(run)
        for blank, run in groupby(lines, key=lambda line: not line)
        if not blank
    ]
    return [
        line
        for at, paragraph in enumerate(paragraphs)
        for line in ([""] if at else []) + paragraph
    ]


def lined(text: str, indent: str) -> list[str]:
    r"""Return `text`'s lines as they are, each set in by `indent` and without its trailing space, but for a blank one; none for no text.

    >>> lined("2 failed\n\n3 passed  \n", "  ")
    ['  2 failed', '', '  3 passed']
    """
    return [
        f"{indent}{line.rstrip()}" if line.strip() else "" for line in text.splitlines()
    ]


def said_as(value: JsonValue, inline: int = 100) -> list[str]:
    r"""Return a value a call was given as the lines it's shown in: text as it is, any other value as JSON, spread over lines where it's longer than `inline`.

    >>> said_as("uv run pytest -q"), said_as(3), said_as(["a"])
    (['uv run pytest -q'], ['3'], ['["a"]'])
    >>> said_as("Which?\nOr neither?")
    ['Which?', 'Or neither?']
    >>> said_as({"text": "A model per kind"}, inline=10)
    ['{', '  "text": "A model per kind"', '}']
    >>> said_as(None)
    ['null']
    """
    if isinstance(value, str):
        return lined(value, "")
    compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(compact) <= inline:
        return [compact]
    return lined(json.dumps(value, ensure_ascii=False, indent=2), "")


def rows_of(lines: list[str], row: int = 100) -> int:
    """Return how many rows of `row` characters `lines` take, a long line wrapping.

    >>> rows_of(["a", "", "b" * 250])
    5
    """
    return sum(max(1, ceil(len(line) / row)) for line in lines)


def since(start: datetime, until: datetime) -> str:
    """Say how long from `start` to `until`, roughly: in seconds, minutes, hours, then days.

    >>> from datetime import UTC
    >>> since(datetime(2026, 10, 18, 10, tzinfo=UTC), datetime(2026, 10, 18, 10, 5, tzinfo=UTC))
    '5m'
    """
    seconds = max(0, round((until - start).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def counted(count: int, one: str) -> str:
    """Say how many of a thing there are.

    >>> counted(1, "step"), counted(5, "step")
    ('1 step', '5 steps')
    """
    return f"{count} {one}{'' if count == 1 else 's'}"


def inboxed(exchanged: Exchanged) -> list[Inboxed]:
    """Return the items the agent exchanged as their conversation shows them, those they sent first, then those they were sent: each in its line as the core words it (`Exchange.line`), in the tone of its way, sent or received, its text under it with the operator's comment on deciding it after it."""

    def text(said: str, comment: str) -> str:
        parts = [said, *([f"your comment: {comment}"] if comment else [])]
        return "\n".join(kept("\n\n".join(parts)))

    def shown(each: Exchange, *, sent: bool) -> Inboxed:
        tone = SENT_TONE if sent else RECEIVED_TONE
        return Inboxed(
            number=each.item.number,
            sent=sent,
            line=[span.model_copy(update={"tone": tone.name}) for span in each.line],
            text=text(each.text, each.comment),
            call=each.item.call if sent else None,
            call_sends_it=each.call_sends_it,
            echoes=each.echoes,
            at=each.at,
        )

    return [
        *(shown(each, sent=True) for each in exchanged.sent),
        *(shown(each, sent=False) for each in exchanged.received),
    ]


def merged(entries: list[Entry], items: list[Inboxed]) -> list[Turn]:
    """Return the steps and the items in order: an item repeating the agent's words at a step on that step, the latest saying them by then; an item the conversation sent just after the call that made it, where the record holds it; any other by when it was told, or made, after the last step at or before then.

    A step its record gives no time takes the time of the last before it, and
    one before any time counts as before every item, so in a record with no
    times the items are all at its end. Items between the same two steps go in
    the order they came, then by number. An item that would repeat words no step
    says, as a turn's end saying in lup's words that it failed, or one the agent
    edited since, stands as any other.
    """

    def turn(step: int, entry: Entry) -> Spoken | Calling:
        match entry:
            case Said():
                return Spoken(step=step, said=entry)
            case Called():
                return Calling(step=step, called=entry)

    steps = [turn(step, entry) for step, entry in enumerate(entries)]
    calls = {
        each.called.id: each.step
        for each in reversed(steps)
        if isinstance(each, Calling) and each.called.id is not None
    }

    def latest(known: datetime | None, at: datetime | None) -> datetime | None:
        return known if at is None else at

    times = list(accumulate((each.at for each in entries), latest))

    def by_then(step: int, item: Inboxed) -> bool:
        time = times[step]
        return time is None or time <= item.at

    said = {
        each.step: "\n".join(kept(each.said.text))
        for each in steps
        if isinstance(each, Spoken) and each.said.by == "agent"
    }

    def repeated(item: Inboxed) -> int | None:
        """Return the step of the agent's words `item` repeats, the latest by when it was made; none where it repeats none."""
        if not item.echoes:
            return None
        return max(
            (
                step
                for step, text in said.items()
                if text == item.text and by_then(step, item)
            ),
            default=None,
        )

    # Of two items saying one step's words, as in a record with no times, the later stands for it, the other alone.
    repeating = {step: each for each in items if (step := repeated(each)) is not None}
    standing = {each.number: each for each in repeating.values()}
    steps = [
        each.model_copy(update={"repeated": repeating[each.step]})
        if each.step in repeating and isinstance(each, Spoken)
        else each
        for each in steps
    ]
    items = [each for each in items if each.number not in standing]

    def before(item: Inboxed) -> int:
        """Return the step `item` goes just after by when it was: the last at or before then, or with no time yet; -1 for before every step."""
        return max(
            (step for step in range(len(times)) if by_then(step, item)),
            default=-1,
        )

    made = {
        each.number: calls[each.call]
        for each in items
        if each.call is not None and each.call in calls
    }
    timed = {each.number: before(each) for each in items if each.number not in made}

    def ordered(placed: dict[int, int], step: int) -> list[Inboxed]:
        found = [each for each in items if placed.get(each.number) == step]
        return sorted(found, key=lambda each: (each.at, each.number))

    return [
        *ordered(timed, -1),
        *(
            turn
            for each in steps
            for turn in [each, *ordered(made, each.step), *ordered(timed, each.step)]
        ),
    ]


def parts(turns: list[Turn]) -> list[Part]:
    """Return `turns` in their parts: what came before the operator's first words, where anything did, then an exchange from each of their words to their next."""

    def opening(turn: Turn) -> Spoken | None:
        match turn:
            case Spoken(said=Said(by="operator")):
                return turn
            case _:
                return None

    starts = [at for at, turn in enumerate(turns) if opening(turn) is not None]
    bounds = [0, *starts, len(turns)]
    pieces = [turns[start:end] for start, end in pairwise(bounds) if end > start]
    return [
        Part(opening=opening(first), turns=rest)
        if opening(first) is not None
        else Part(turns=[first, *rest])
        for first, *rest in pieces
    ]


def words(spoken: Spoken) -> list[Line]:
    """Return the operator's words as the lines they're shown in: the first after `you:`, the others set in under it, a blank line between paragraphs."""
    first, *rest = kept(spoken.said.text) or [""]
    step = spoken.step
    indent = " " * len("you: ")
    return [
        Line.of(f"step {step}", f"you: {first}" if first else "you:", "operator"),
        *(
            Line.of(f"step {step}.{at}", f"{indent}{line}" if line else "", "operator")
            for at, line in enumerate(rest, start=1)
        ),
    ]


def called(call: Called) -> str:
    """Say a call in its line: its tool, and what it was given where its record says (`Called.gist`)."""
    return call.tool if call.gist is None else f"{call.tool}: {call.gist}"


def starting(text: str, width: int = 100) -> str:
    r"""Say how `text` starts, as it's written, in a line of at most `width` characters: its first line with words in it, cut where it's longer (`cut`); nothing for no text.

    >>> starting("\n\nFound it.\nHere.")
    'Found it.'
    >>> starting("")
    ''
    """
    return cut(next((line for line in kept(text) if line), ""), width)


def ran_of(calls: list[Calling], row: int = 100) -> str:
    """Say a run of calls in its line, of at most `row` characters: how many, then how many of which, most first, so what's cut is what there's least of.

    >>> ran_of([Calling(step=at, called=Called(tool=tool)) for at, tool in enumerate(["Read", "Bash", "Bash"])])
    '· 3 calls: Bash x2, Read'
    """
    tools = Counter(each.called.tool for each in calls).most_common()
    said = ", ".join(
        tool if count == 1 else f"{tool} x{count}" for tool, count in tools
    )
    return cut(f"· {counted(len(calls), 'call')}: {said}", row)


def turned(
    turns: list[Turn], of: OfAgent, view: Method, run: int = 3, row: int = 100
) -> list[Block]:
    """Lay `turns` out in blocks, in order: the operator's words; the agent's, each a fold of their own under a line saying how they start, open but for those an item repeats, which fold under its line; each call a line saying what it was given, each run of `run` calls or more under one line saying how many of which, open; and each item a line with its text folded under it; what each run, call and item folds set off by a bar (`Fold.barred`).

    A call whose record gives it an id folds its input and output under its
    line, read from `view`, one call read whole, as it opens. A call whose
    sending an item is all it did goes under that item's line, after its text,
    the item standing for it, since the call's line would say what its text says.
    Each line is at most `row` characters (`cut`).
    """
    sending = {
        each.call: each.number
        for each in reversed(turns)
        if isinstance(each, Inboxed) and each.call is not None and each.call_sends_it
    }
    calls = {
        each.called.id: each
        for each in turns
        if isinstance(each, Calling) and each.called.id in sending
    }

    def call(calling: Calling) -> Block:
        summary = [
            Span(text=f"· {cut(called(calling.called), row - 2)}", tone=CALL_TONE.name)
        ]
        ran = calling.called.id
        if ran is None:
            return Line(id=f"step {calling.step}", spans=summary)
        read = OfCall(runtime=of.runtime, session=of.session, agent=of.agent, id=ran)
        return Fold(
            id=f"call {ran}",
            kind=CALL_KIND.name,
            summary=summary,
            barred=True,
            content=Load.of(view, read),
        )

    def line_of(inboxed: Inboxed, text: str, least: int = 20) -> list[Span]:
        """Return an item's line, saying how `text` starts after it where the conversation sent it, the words of theirs it stands for, in what the row has left, nothing where that's under `least` characters."""
        room = row - sum(len(span.text) for span in inboxed.line) - len(" · ")
        start = starting(text, room) if inboxed.sent and room >= least else ""
        return [
            *inboxed.line,
            *([Span(text=f" · {start}", tone="muted")] if start else []),
        ]

    def made_by(inboxed: Inboxed) -> list[Block]:
        """Return the line of the call `inboxed` stands for, where it's the first item that call sent and the call is laid out here."""
        ran = inboxed.call
        if ran is None or sending.get(ran) != inboxed.number or ran not in calls:
            return []
        return [call(calls[ran])]

    def item(inboxed: Inboxed) -> Block:
        number = inboxed.number
        summary = line_of(inboxed, inboxed.text)
        text = [Markdown(id=f"text {number}", text=inboxed.text)]
        content = [*(text if inboxed.text else []), *made_by(inboxed)]
        if not content:
            return Line(id=f"item {number} line", spans=summary)
        return Fold(
            id=f"item {number}",
            kind=ITEMS_KIND.name,
            summary=summary,
            barred=True,
            content=content,
        )

    def message(spoken: Spoken) -> Block:
        text = "\n".join(kept(spoken.said.text))
        body = Markdown(id=f"step {spoken.step}", text=text)
        if not text:
            return body
        repeated = spoken.repeated
        return Fold(
            id=f"said {spoken.step}",
            kind=ITEMS_KIND.name,
            summary=[Span(text=starting(text, row), tone="muted")]
            if repeated is None
            else line_of(repeated, text),
            open=repeated is None,
            barred=repeated is not None,
            content=[body],
        )

    def one(turn: Turn) -> list[Block]:
        match turn:
            case Spoken(said=Said(by="operator")):
                return list(words(turn))
            case Spoken():
                return [message(turn)]
            case Calling():
                return [call(turn)]
            case Inboxed():
                return [item(turn)]

    def laid(group: list[Turn]) -> list[Block]:
        rows = [each for each in group if isinstance(each, Calling)]
        if len(rows) < run:
            return [block for each in group for block in one(each)]
        return [
            Fold(
                id=f"calls {rows[0].step}",
                kind=CALLS_KIND.name,
                summary=[Span(text=ran_of(rows, row), tone=RUN_TONE.name)],
                open=True,
                barred=True,
                content=[call(each) for each in rows],
            )
        ]

    # A call its item stands for is in that item, and no row of a run.
    shown = [
        each
        for each in turns
        if not (isinstance(each, Calling) and each.called.id in calls)
    ]
    runs = groupby(shown, key=lambda each: isinstance(each, Calling))
    return [block for _, group in runs for block in laid(list(group))]


def agent_s(turn: Turn) -> bool:
    """Say whether `turn` is the agent's words, which the cap on what's open counts: never their calls, each a line however many there are, nor an item, but those an item repeats, though they fold, so a conversation of turns' ends alone stays small too."""
    return isinstance(turn, Spoken) and turn.said.by != "operator"


def capped(
    part: Part,
    of: OfAgent,
    kind: FoldKind,
    *,
    through: int | None = None,
    until_last: int | None,
    read: Read | None = None,
    exchange: Method,
    call: Method,
    run: int,
) -> list[Block]:
    """Lay out the turns of `part`, or only those up to step `through` in it, or before the agent's last `until_last` words: what the operator has read of it (`read`) folded, and of the rest at most the agent's last `kind.keeps_open` words open, with what follows them, what came before them folded too, under one line saying how many steps and items and how many of them are new, read from `exchange` as it opens (`kept_open`).

    Where only what they'd read folds, the fold reads the exchange up to the
    last step they read, its id saying which (`exchange 12 through 40`), which
    changes only as they mark more read. Where some of what's new folds too,
    the fold reads the exchange up to the agent's last words shown here and
    those shown after, so each fold opened shows `kind.keeps_open` more of the
    agent's words, and folds what came before them the same way. Its id says
    how many of the agent's last words it comes before (`exchange 12 until
    last 20`), which a new turn of the agent's never changes, so a fold the
    operator opened stays open as the conversation grows.
    """
    # What they'd read of it is all read: only what came after it splits again.
    if through is None:
        within, marking = part.turns, read
    else:
        bound = Read(step=through, marked=None if read is None else read.marked)
        within, marking = part.turns[: bound.reviewed(part.turns)], None
    turns = (
        within if until_last is None else kept_open(within, agent_s, until_last).folded
    )
    reviewed = 0 if marking is None else marking.reviewed(turns)
    kept = kept_open(turns, agent_s, kind.keeps_open, reviewed)
    shown = turned(kept.shown, of, call, run)
    if not kept.folded:
        return shown
    steps = sum(1 for each in kept.folded if not isinstance(each, Inboxed))
    items = len(kept.folded) - steps
    new = sum(
        1 for each in kept.folded[kept.reviewed :] if not isinstance(each, Inboxed)
    )
    said = ", ".join(
        [
            *([counted(steps, "earlier step")] if steps else []),
            *([counted(items, "item" if steps else "earlier item")] if items else []),
            *([f"{new} new"] if new else []),
        ]
    )
    only_read = marking is not None and len(kept.folded) == kept.reviewed
    # What was read is named by the last step it holds; where it holds items alone, by the step they'd read.
    last = next(
        (each.step for each in reversed(kept.folded) if not isinstance(each, Inboxed)),
        None if marking is None else marking.step,
    )
    if only_read and last is not None:
        key = f"{part.key()} through {last}"
        loaded = OfExchange(
            runtime=of.runtime,
            session=of.session,
            agent=of.agent,
            step=part.step(),
            through=last,
        )
    else:
        deeper = (until_last or 0) + (kind.keeps_open or 0)
        key = f"{part.key()}{'' if through is None else f' through {through}'} until last {deeper}"
        loaded = OfExchange(
            runtime=of.runtime,
            session=of.session,
            agent=of.agent,
            step=part.step(),
            through=through,
            until_last=deeper,
        )
    fold = Fold(
        id=key,
        kind=kind.name,
        summary=[Span(text=said, tone="muted")],
        content=Load.of(exchange, loaded),
    )
    return [fold, *shown]


def conversation_blocks(
    of: OfAgent,
    entries: list[Entry],
    exchanged: Exchanged,
    *,
    exchange: Method,
    call: Method,
    earlier: FoldKind = EARLIER_KIND,
    run: int = 3,
    mark: ReviewMark | None = None,
    reading: Offer | None = None,
) -> Blocks:
    """Lay out an agent's conversation as its drawer shows it: its summary line counting its steps and those new to the operator, each exchange before their last words folded under the first line of their words, the latest open under its own, what they've read since folded under one line, and everything after it open, but for at most the agent's last words `earlier` keeps open (`capped`).

    How far they've read is the drawer's review `mark` or their own last
    words, whichever is later (`Read`); where anything came after it, the
    drawer offers `reading`, marking it read up to its last step, Space `d` on
    its line. What came before their first words folds under a line of its
    own, saying how many steps and items and how long before their words. Each
    earlier exchange, and what came before the agent's last words, is read from
    `exchange`, one exchange's view, as it opens, and each call's input and
    output from `call`, one call's view (`turned`). A conversation with no
    steps is none: an empty answer, with no summary line.
    """
    if not entries:
        return Blocks()
    *before, latest = parts(merged(entries, inboxed(exchanged)))
    read = Read.of(mark, entries)
    unread = len(latest.turns) - read.reviewed(latest.turns)

    def at(turn: Turn) -> datetime | None:
        match turn:
            case Inboxed():
                return turn.at
            case Spoken():
                return turn.said.at
            case Calling():
                return turn.called.at

    def summary(part: Part, until: Part) -> list[Span]:
        if part.opening is not None:
            return words(part.opening)[0].spans
        steps = sum(1 for each in part.turns if not isinstance(each, Inboxed))
        items = len(part.turns) - steps
        count = ", ".join(
            [counted(steps, "step"), *([counted(items, "item")] if items else [])]
        )
        start = at(part.turns[0])
        end = None if until.opening is None else until.opening.said.at
        ago = (
            ""
            if start is None or end is None
            else f", from {since(start, end)} before your first words"
        )
        return [Span(text=f"earlier · {count}{ago}", tone="muted")]

    def folded_part(part: Part, until: Part) -> Fold:
        read = OfExchange(
            runtime=of.runtime, session=of.session, agent=of.agent, step=part.step()
        )
        return Fold(
            id=part.key(),
            kind=earlier.name,
            summary=summary(part, until),
            content=Load.of(exchange, read),
        )

    shown = capped(
        latest,
        of,
        earlier,
        until_last=None,
        read=read,
        exchange=exchange,
        call=call,
        run=run,
    )

    def opening() -> list[Block]:
        """Return the latest exchange: its fold, open, as the others are folded, or what came before the operator's first words, where they've said none yet; a line alone, nothing under it yet."""
        if latest.opening is None:
            return shown
        first, *further = words(latest.opening)
        under = [*further, *shown]
        if not under:
            return [first]
        return [
            Fold(
                id=latest.key(),
                kind=earlier.name,
                summary=first.spans,
                open=True,
                content=under,
            )
        ]

    new = read.new(entries)
    said = [
        f"conversation · {counted(len(entries), 'step')}",
        *([f"{new} new"] if new else []),
    ]
    return Blocks(
        summary=[Span(text=" · ".join(said))],
        offers=[] if reading is None or not unread else [reading],
        blocks=[
            *(folded_part(part, until) for part, until in pairwise([*before, latest])),
            *opening(),
        ],
    )


def exchange_blocks(
    of: OfExchange,
    entries: list[Entry],
    exchanged: Exchanged,
    *,
    exchange: Method,
    call: Method,
    earlier: FoldKind = EARLIER_KIND,
    run: int = 3,
    mark: ReviewMark | None = None,
) -> Blocks:
    """Lay out one exchange of an agent's conversation as its fold in the drawer shows it opened: the operator's further lines of the words that open it, then each step and item up to their next words, but for at most the agent's last words `earlier` keeps open (`capped`).

    The first line of their words is the fold's summary, so it isn't laid out
    again. For what came before their first words, every step and item there;
    none where nothing came before them. With `of.through`, only what came up
    to that step, what the operator had read of it; with `of.until_last`, only
    what came before the agent's last words that many, which its fold of what
    came earlier holds, capped the same way, and, in the latest exchange, what
    they've read of it folded as in the drawer (`mark`, `Read`); none where the
    agent said no more. What came before the words kept open is read from
    `exchange`, this view, and each call's input and output from `call`, one
    call's view, as each fold opens.

    Raise `ConversationError` where `of.step` isn't a step of the operator's
    words.
    """
    every = parts(merged(entries, inboxed(exchanged)))
    found = [part for part in every if part.step() == of.step]
    match found, of.step:
        case [part], _:
            pass
        case [], None:
            return Blocks()
        case _:
            message = (
                f"step {of.step} of the conversation isn't the operator's words, "
                "which open an exchange"
            )
            raise ConversationError(message)
    further = (
        []
        if part.opening is None or of.until_last is not None or of.through is not None
        else words(part.opening)
    )[1:]
    # Only in the latest is what they've read folded apart: they read every earlier one whole.
    latest = part is every[-1]
    shown = capped(
        part,
        of,
        earlier,
        through=of.through,
        until_last=of.until_last,
        read=Read.of(mark, entries) if latest else None,
        exchange=exchange,
        call=call,
        run=run,
    )
    return Blocks(blocks=[*further, *shown])


def call_blocks(
    of: OfCall,
    call: Call | None,
    *,
    view: Method,
    inline: int = 100,
    most: int = 10,
    row: int = 100,
) -> Blocks:
    """Lay out one call as its fold shows it opened: what it was given straight away, each argument after its name, on a line, or set in under it where it's several, one taking more than `most` rows of `row` characters folded under a line saying how it starts and how long it is; then what it returned, folded under a line saying how much, or `failed` where the runtime says it failed, `none yet` while it runs.

    What's folded is read from `view`, this view, as it opens, with `of.output`
    what it returned whole, or with `of.argument` that argument whole, so opening a
    call reads no more of it than its input, and a command printing this view says
    which to ask for. A call its record doesn't hold, `call` none, says it wasn't
    read. A value longer than `inline` as JSON is spread over lines.
    """
    ran = of.id
    if call is None:
        return Blocks(
            blocks=[
                Line.of(
                    f"unread {ran}",
                    "not read: its record doesn't hold the call",
                    "muted",
                )
            ]
        )

    def numbered(part: str, lines: list[str], indent: str = "") -> list[Block]:
        return [
            Line.of(f"{part}.{at}", f"{indent}{line}" if line else "")
            for at, line in enumerate(lines, start=1)
        ]

    if of.output:
        return Blocks(blocks=numbered(f"output {ran}", lined(call.output or "", "")))
    if of.argument is not None:
        match call.input:
            case dict() as arguments:
                wanted = arguments.get(of.argument)
            case _ as given:
                wanted = given
        return Blocks(
            blocks=numbered(f"argument {ran} {of.argument}", said_as(wanted, inline))
        )

    def folded_under(name: str, value: JsonValue, lines: list[str]) -> Block:
        """Return `lines`, too long to read at a glance, folded under a line saying how `value`, called `name`, starts, and how long it is."""
        compact = (
            None if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        )
        start = next((line for line in lines if line.strip()), "")
        tail = f" · {counted(len(lines), 'line')}"
        line = cut(f"{name}: {start if compact is None else compact}", row - len(tail))
        return Fold(
            id=f"argument {ran} {name}",
            kind=DETAIL_KIND.name,
            summary=[Span(text=f"{line}{tail}")],
            barred=True,
            content=Load.of(view, of.model_copy(update={"argument": name})),
        )

    def argument(name: str, value: JsonValue) -> list[Block]:
        lines = said_as(value, inline)
        key = f"input {ran} {name}"
        if rows_of(lines, row) > most:
            return [folded_under(name, value, lines)]
        match lines:
            case [only]:
                return [Line.of(key, f"{name}: {only}")]
            case _:
                return [Line.of(key, f"{name}:"), *numbered(key, lines, "  ")]

    def inputs() -> list[Block]:
        match call.input:
            case dict() as arguments:
                return [
                    block
                    for name, value in arguments.items()
                    for block in argument(name, value)
                ]
            case _ as given:
                lines = said_as(given, inline)
                if rows_of(lines, row) > most:
                    return [folded_under("input", given, lines)]
                return numbered(f"input {ran}", lines)

    def returned() -> Block:
        if call.output is None:
            return Line.of(f"output {ran}", "output: none yet")
        said = "failed" if call.failed else "output"
        lines = lined(call.output, "")
        if not lines:
            return Line.of(f"output {ran}", f"{said}: nothing")
        return Fold(
            id=f"output {ran}",
            kind=DETAIL_KIND.name,
            summary=[Span(text=f"{said} · {counted(len(lines), 'line')}")],
            barred=True,
            content=Load.of(view, of.model_copy(update={"output": True})),
        )

    return Blocks(blocks=[*inputs(), returned()])
