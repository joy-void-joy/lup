"""A conversation laid out in lup's building blocks: the drawer under its agent's banner, one earlier exchange, and one call read whole.

`docs/dashboard.md`, *The drawers*, its **Conversation** entry. Each is a pure
layout answering `Blocks`, the layout of one of `Transcripts`' views:
- `conversation_blocks`, the drawer: its summary line counting the steps and
  those new to the operator, each exchange before their last words folded under
  the first line of their words that opened it, what came before their first
  words under a line of its own, and everything since they last read it open
  and new, from the drawer's review mark or their own last words, whichever is
  later (`Read`), but for at most the agent's last 20 words
  (`EARLIER_KIND.keeps_open`) with what follows them, what came before folded
  under one line saying how much (`capped`);
- `exchange_blocks`, one earlier exchange's steps, or those its fold of what
  came before the agent's last words holds, or what the operator had read of
  the latest, which the fold reads as it opens (`OfExchange`), itself capped
  the same way, so the drawer's answer stays small however long the
  conversation grows, and each fold opened brings in 20 more of the agent's
  words;
- `call_blocks`, one call's input and output, which the call's fold reads as
  it opens (`OfCall`), since each call's whole input and output is read from
  the record only on asking.

Within an exchange, the operator's words come after `you:`, the agent's as
Markdown, each call as a line saying what it did (`Called.gist`), a run of calls
folded under one line saying how many of which, and each item of lup's inbox
the conversation sent or was sent as a line where it happened, its text folded
under it (`merged`).

Each block's id names what it shows, so it stays from one answer to the next as
the conversation grows, and a fold's id is never a line's: a fold is
`exchange 5` (or `exchange before`), `exchange 5 until last 20` for what came
before the agent's last 20 words in it, `exchange 5 through 40` for what the
operator had read of it up to step 40, `calls 2`, `call <the call's id>` or
`item 51`; a line is `step 6` (`step 6.1` on, for the operator's further
lines), `item 64 line` for an item with no text, `text 51` for an item's text,
and `input <id>`, `output <id>` (`.1` on) or `unread <id>` in a call's view.
"""

import json
from datetime import datetime
from itertools import accumulate, groupby, pairwise
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
from lup_transcripts.environment.views import folded
from lup_transcripts.errors import LupTranscriptsError

if TYPE_CHECKING:
    from pydantic import JsonValue

    from lup.doors import Method
    from lup_dev.host.records import Call
    from lup_dev.inbox.marks import ReviewMark
    from lup_dev.inbox.protocol import Exchange, Exchanged


CALL_TONE = Tone(name="call", colour="orange")
"""A call's line, saying what it did."""
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
CALLS_KIND = FoldKind(
    name="calls",
    letter="k",
    called="runs of calls",
    one="the run of calls",
    level=2,
    colour="purple",
    counts=False,
)
"""A run of calls, under one line saying how many of which, set off under it."""
ITEMS_KIND = FoldKind(
    name="items",
    letter="m",
    called="items' text",
    one="the item's text",
    level=3,
    colour="cyan",
    counts=False,
)
"""An item of lup's inbox the conversation sent or was sent, its text under its
line."""
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

FOLD_KINDS = [EARLIER_KIND, CALLS_KIND, ITEMS_KIND, CALL_KIND]
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
    """One call of an agent's conversation, read whole as its fold in the drawer opens."""

    id: str = Field(description="The runtime's id for the call.")


class Spoken(Model):
    """Something said at one step: the operator's words, or the agent's."""

    step: int
    said: Said


class Calling(Model):
    """A tool called at one step."""

    step: int
    called: Called


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
    at: datetime
    """When it was told the conversation, or made: where it goes among the steps
    when no call places it."""


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


def given(value: JsonValue, indent: str = "", inline: int = 100) -> list[str]:
    r"""Return what a call was given as the lines it's shown in, set in by `indent`: each argument after its name, a value of several lines, or longer than `inline` as JSON, under it; text as it is.

    >>> given({"command": "uv run pytest -q", "limit": 3, "tags": ["a"]})
    ['command: uv run pytest -q', 'limit: 3', 'tags: ["a"]']
    >>> given({"question": "Which?\nOr neither?"})
    ['question:', '  Which?', '  Or neither?']
    >>> given(None, "  ")
    ['  null']
    """
    inner = f"{indent}  "

    def argument(name: str, each: JsonValue) -> list[str]:
        match each:
            case str() if "\n" in each:
                return [f"{indent}{name}:", *lined(each, inner)]
            case str():
                return [f"{indent}{name}: {each}"]
            case _:
                compact = json.dumps(each, ensure_ascii=False, separators=(",", ":"))
                if len(compact) <= inline:
                    return [f"{indent}{name}: {compact}"]
                spread = json.dumps(each, ensure_ascii=False, indent=2)
                return [f"{indent}{name}:", *lined(spread, inner)]

    match value:
        case str():
            return lined(value, indent)
        case dict():
            return [
                line for name, each in value.items() for line in argument(name, each)
            ]
        case _:
            return lined(json.dumps(value, ensure_ascii=False, indent=2), indent)


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
    """Return the items the agent exchanged as their conversation shows them, those they sent first, then those they were sent: each in its line as the core words it (`Exchange.line`), in the tone of its way, sent or received, its text under it with the operator's comment on deciding it after it.

    One repeating the conversation's own words, a turn's last words lup made a
    note of, is left out: the agent's words show it already.
    """

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
            at=each.at,
        )

    return [
        *(shown(each, sent=True) for each in exchanged.sent if not each.echoes),
        *(shown(each, sent=False) for each in exchanged.received),
    ]


def merged(entries: list[Entry], items: list[Inboxed]) -> list[Turn]:
    """Return the steps and the items in order: an item the conversation sent just after the call that made it, where the record holds it; any other by when it was told, or made, after the last step at or before then.

    A step its record gives no time takes the time of the last before it, and
    one before any time counts as before every item, so in a record with no
    times the items are all at its end. Items between the same two steps go in
    the order they came, then by number.
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

    def before(item: Inboxed) -> int:
        """Return the step `item` goes just after by when it was: the last at or before then, or with no time yet; -1 for before every step."""
        return max(
            (
                step
                for step, time in enumerate(times)
                if time is None or time <= item.at
            ),
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
    """Say a call in its line: its tool, and what it did where its record says (`Called.gist`)."""
    return call.tool if call.gist is None else f"{call.tool}: {call.gist}"


def turned(turns: list[Turn], of: OfAgent, view: Method, run: int = 3) -> list[Block]:
    """Lay `turns` out in blocks, in order: the operator's words, the agent's, each call a line saying what it did, each run of `run` calls or more folded under one line saying how many of which, and each item a line with its text folded under it; what each run, call and item folds set off by a bar (`Fold.barred`).

    A call whose record gives it an id folds its input and output under its
    line, read from `view`, one call read whole, as it opens.
    """

    def call(calling: Calling) -> Block:
        summary = [Span(text=f"· {called(calling.called)}", tone=CALL_TONE.name)]
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

    def item(inboxed: Inboxed) -> Block:
        summary = inboxed.line
        number = inboxed.number
        if not inboxed.text:
            return Line(id=f"item {number} line", spans=summary)
        return Fold(
            id=f"item {number}",
            kind=ITEMS_KIND.name,
            summary=summary,
            barred=True,
            content=[Markdown(id=f"text {number}", text=inboxed.text)],
        )

    def one(turn: Turn) -> list[Block]:
        match turn:
            case Spoken(said=Said(by="operator")):
                return list(words(turn))
            case Spoken():
                return [
                    Markdown(
                        id=f"step {turn.step}", text="\n".join(kept(turn.said.text))
                    )
                ]
            case Calling():
                return [call(turn)]
            case Inboxed():
                return [item(turn)]

    def laid(group: list[Turn]) -> list[Block]:
        calls = [each for each in group if isinstance(each, Calling)]
        if len(calls) < run:
            return [block for each in group for block in one(each)]
        tools = folded([each.called.tool for each in calls])
        return [
            Fold(
                id=f"calls {calls[0].step}",
                kind=CALLS_KIND.name,
                summary=[Span(text=tools, tone=RUN_TONE.name)],
                barred=True,
                content=[call(each) for each in calls],
            )
        ]

    runs = groupby(turns, key=lambda each: isinstance(each, Calling))
    return [block for _, group in runs for block in laid(list(group))]


def agent_s(turn: Turn) -> bool:
    """Say whether `turn` is the agent's words, which the cap on what's open counts: never their calls, which fold anyway, nor an item."""
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
    """Lay out an agent's conversation as its drawer shows it: its summary line counting its steps and those new to the operator, each exchange before their last words folded under the first line of their words, what they've read since folded under one line, and everything after it open, but for at most the agent's last words `earlier` keeps open (`capped`).

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

    opened = [] if latest.opening is None else words(latest.opening)
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
            *opened,
            *shown,
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


def call_blocks(of: OfCall, call: Call | None, *, inline: int = 100) -> Blocks:
    """Lay out one call read whole as its fold in the drawer shows it opened: what it was given after `input:`, each argument after its name, and what it returned after `output:`, or `failed:` where the runtime says it failed, `none yet` while it runs.

    A call its record doesn't hold, `call` none, says it wasn't read. A value
    longer than `inline` as JSON is laid out under its argument's name.
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

    def numbered(part: str, lines: list[str]) -> list[Block]:
        return [
            Line.of(f"{part} {ran}.{at}", line)
            for at, line in enumerate(lines, start=1)
        ]

    if call.output is None:
        returned = [Line.of(f"output {ran}", "output: none yet")]
    else:
        said = "failed:" if call.failed else "output:"
        returned = [
            Line.of(f"output {ran}", said),
            *numbered("output", lined(call.output, "  ")),
        ]
    return Blocks(
        blocks=[
            Line.of(f"input {ran}", "input:"),
            *numbered("input", given(call.input, "  ", inline)),
            *returned,
        ]
    )
