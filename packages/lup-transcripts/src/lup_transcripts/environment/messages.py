"""An agent's conversation as its words alone, laid out in lup's building blocks: the `messages` drawer under their banner, and what came earlier in it.

`docs/dashboard.md`, *The drawers*, its **Messages** entry. The trace
(`environment/conversation.py`) holds everything an agent did; this is what's
read to follow what they said and were told, without their calls, each saying
who's talking to whom. Pure, as the trace is, and from the same steps and items
(`merged`), in the order they came:
- what a subagent's parent told them as they spawned them, where their record
  holds it (`Transcript.brief`), first;
- the operator's words typed to them, under a heading the core words
  (`Exchanged.typed`);
- their turns' ends: the words an item repeats, under that item's heading, their
  last words before the operator typed again, and a subagent's last words, which
  their runtime hands their parent and no item holds (`Exchanged.last_words`);
- each item they sent or were sent that's words (`Exchange.words`): what the
  operator said through lup as they'd read it back, messages between this agent
  and others, and what this agent told the operator, whose answer would otherwise
  have nothing above it; a subagent's end in their parent's drawer with those
  last words under it, read from their record as it's shown (`report`). A write
  lup flagged or held, and lup's word on citations, are the trace's alone.

Each message is a fold of the trace's own `items` kind (`m`), open, under its
heading, its text Markdown a comment is anchored to. A comment on what another
agent wrote goes to them (`Markdown.by`), so it reaches whoever wrote it whichever
of the two drawers it's written in; each is anchored to the drawer it's written
in, as every comment is to its block, so the same words read in the other drawer
don't carry it.

What came after the operator last read it stays open and new, read by its words
being on screen (`Sight`), with the last few they read before it (`seen`), but for at most the last `FoldKind.keeps_open`
messages, what came before folded under one line (`▸ 412 earlier messages, 30
new`) read as it opens (`laid`). How far they've read is the drawer's own review
mark, or their own last words to the agent, typed or through lup, since they speak
having read what came before (`Read`), and their words themselves are never new. Space `d` on the drawer's line moves
it, and leaves the trace's as it is, each drawer being its own scope.

Each block's id names what it shows, so it stays as the conversation grows: `said
6` and `step 6` a step's fold and words, `item 51` and `text 51` an item's, `item
51 line` an item with no text; `messages through item 51` what the operator had
read up to that message, `messages until last 20` what came before the last 20.
"""

from collections.abc import Callable
from itertools import pairwise
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
from lup_dev.host.records import Said
from lup_transcripts.environment.conversation import (
    EARLIER_KIND,
    ITEMS_KIND,
    RECEIVED_TONE,
    SENT_TONE,
    Calling,
    Capped,
    Inboxed,
    Position,
    Read,
    Spoken,
    counted,
    inboxed,
    kept,
    key,
    merged,
    positions,
    sight_of,
    sighted,
)

if TYPE_CHECKING:
    from lup.doors import Method
    from lup_dev.host.records import Entry
    from lup_dev.inbox.marks import ReviewMark
    from lup_dev.inbox.protocol import Exchanged

type Report = Callable[[OfAgent], str]
"""Read one conversation's last words from their record, which is all that holds
them where their runtime handed them to their parent; nothing where it can't."""

HEARD_TONE = Tone(name="heard", colour="purple")
"""What another agent said to this one, in a colour of its own: the operator's words
are in the blue of theirs, and this agent's own in the orange of what they sent."""
NEW_TONE = Tone(name="new", like="strong")
"""A message new to the operator saying so on its heading."""

TONES = [HEARD_TONE, NEW_TONE]
"""The tones the messages declare beside the trace's."""


class OfMessages(OfAgent):
    """What came earlier among an agent's messages, as its fold in the drawer reads it: what the operator had read, up to one message; or what came before the last that many, which show open after it."""

    through: str | None = Field(
        default=None,
        description="Only what came up to this message, which you had read, by its block: `step 6` for the agent's or your words at step 6, `item 51` for an item. Left out, as far as it goes.",
    )
    until_last: int | None = Field(
        default=None,
        description="Only what came before the last `until_last` messages, which show open after it. Left out, all of it.",
    )


type Word = Spoken | Inboxed
"""One message: something said at a step, or an item of lup's inbox."""


def messages(
    entries: list[Entry],
    exchanged: Exchanged,
    of: OfAgent,
    brief: str | None = None,
) -> list[Word]:
    """Return the words of the conversation of `entries` in the order they came: what spawned them, where their record holds it apart from their steps (`brief`), named as a step before the first; the operator's typed, their turns' ends, and each item that's words.

    A turn's end is the agent's words an item repeats; their last words before the
    operator types again, or, for a subagent, whose last words are no item, at the
    record's end, with no call after them. Their words while a turn goes on are the
    trace's.
    """
    briefed = (
        [] if brief is None else [Spoken(step=-1, said=Said(by="operator", text=brief))]
    )
    turns = merged(entries, inboxed(exchanged))
    steps = [each for each in turns if not isinstance(each, Inboxed)]

    def ends_it(turn: Spoken | Calling, after: Spoken | Calling | None) -> bool:
        match turn, after:
            case Spoken(said=said), None:
                return said.by == "agent" and of.agent is not None
            case Spoken(said=said), Spoken(said=next_said):
                return said.by == "agent" and next_said.by == "operator"
            case _:
                return False

    last = [
        each.step
        for each, after in pairwise([*steps, None])
        if isinstance(each, Spoken) and ends_it(each, after)
    ]

    def words(turn: Word) -> bool:
        match turn:
            case Inboxed():
                return turn.heading is not None
            case Spoken():
                return (
                    turn.said.by == "operator"
                    or turn.repeated is not None
                    or turn.step in last
                )

    return [
        *briefed,
        *(each for each in turns if not isinstance(each, Calling) and words(each)),
    ]


def their_own(turn: Word) -> bool:
    """Say whether `turn` is the operator's own words through lup, which are never new to them."""
    return isinstance(turn, Inboxed) and turn.spoken is not None


def message(turn: Word, exchanged: Exchanged, report: Report, *, new: bool) -> Block:
    """Lay out one message: its text under its heading saying who's talking to whom, in the tone of who's talking, open, saying `new` where it came after what the operator read; a subagent's end with their last words first, read by `report`, which a comment on goes to them."""

    def heading(line: list[Span], tone: Tone) -> list[Span]:
        toned = [span.model_copy(update={"tone": tone.name}) for span in line]
        return [
            *toned,
            *([Span(text=" · "), Span(text="new", tone=NEW_TONE.name)] if new else []),
        ]

    def under(fold: str, line: list[Span], tone: Tone, body: Markdown) -> Block:
        return Fold(
            id=fold,
            kind=ITEMS_KIND.name,
            summary=heading(line, tone),
            open=True,
            barred=True,
            content=[body],
        )

    match turn:
        case Inboxed(heading=line, reading=reading, number=number):
            tone = (
                SENT_TONE
                if turn.sent
                else HEARD_TONE
                if turn.by is not None
                else RECEIVED_TONE
            )
            last = "" if not turn.reported or turn.by is None else report(turn.by)
            text = "\n".join(kept(f"{last}\n\n{reading}"))
            if not text:
                return Line(id=f"item {number} line", spans=heading(line or [], tone))
            body = Markdown(id=f"text {number}", text=text, by=turn.by)
            return under(f"item {number}", line or [], tone, body)
        case Spoken(step=step, said=said, repeated=repeated):
            text = "\n".join(kept(said.text))
            if said.by == "operator":
                body = Markdown(id=f"step {step}", text=text, by=exchanged.parent)
                tone = RECEIVED_TONE if exchanged.parent is None else HEARD_TONE
                return under(f"said {step}", exchanged.typed, tone, body)
            body = Markdown(id=f"step {step}", text=text)
            line = (
                exchanged.last_words
                if repeated is None or repeated.heading is None
                else repeated.heading
            )
            return under(f"said {step}", line, SENT_TONE, body)


def body_of(block: Block) -> str:
    """Return the id of what a message's `block` says: its words under its heading, which a fold closed over them keeps off screen; the line itself, for one with no words."""
    match block:
        case Fold(content=[first, *_]):
            return first.id
        case _:
            return block.id


def laid(
    said: list[Word],
    of: OfAgent,
    exchanged: Exchanged,
    kind: FoldKind,
    *,
    view: Method,
    report: Report,
    read: Read | None,
    places: dict[str, Position],
    through: str | None = None,
    until_last: int | None = None,
    seen: int = 3,
) -> Capped:
    """Lay out `said`, or only those up to the message `through`, or before the last `until_last`: what the operator has read folded, but for the last `seen` of it, so the drawer opens on where the exchange stands rather than on one line saying how much came before; and of the rest at most the last `kind.keeps_open` open, each saying it's new, what came before folded too, under one line saying how many and how many of them are new, read from `view` as it opens (`kept_open`).

    Where only what they'd read folds, the fold reads up to the last message they
    read, its id saying which, which changes only as they mark more read. Where
    some of what's new folds too, it reads what came before the messages shown,
    so each fold opened shows `kind.keeps_open` more, and folds what came before
    them the same way; its id says how many of the last messages it comes before,
    which a new message never changes, so a fold the operator opened stays open.

    Each message new to them is read by being on screen, its words themselves, so
    one closed under its heading isn't; and what's new under the fold holds their
    mark back until it's opened (`Sight`).
    """
    named = [key(each) for each in said]
    within = said if through is None else said[: named.index(through) + 1]
    turns = (
        within if until_last is None else kept_open(within, always, until_last).folded
    )
    # What they'd read of it is all read: only what came after it splits again.
    read_up_to = 0 if read is None or through is not None else read.reviewed(turns)
    held = kept_open(turns, always, kind.keeps_open, max(read_up_to - seen, 0))

    def is_new(at: int, turn: Word) -> bool:
        return (
            read is not None
            and through is None
            and at + len(held.folded) >= read_up_to
            and not their_own(turn)
        )

    shown = [
        message(each, exchanged, report, new=is_new(at, each))
        for at, each in enumerate(held.shown)
    ]
    sights = [
        sight_of(each, body_of(block), places)
        for at, (each, block) in enumerate(zip(held.shown, shown, strict=True))
        if is_new(at, each)
    ]
    if not held.folded:
        return Capped(blocks=shown, sights=sights)
    new = sum(1 for each in held.folded[read_up_to:] if not their_own(each))
    said_of = ", ".join(
        [
            counted(len(held.folded), "earlier message"),
            *([f"{new} new"] if new else []),
        ]
    )
    if read is not None and through is None and len(held.folded) == held.reviewed:
        up_to, deeper = key(held.folded[-1]), None
        block = f"messages through {up_to}"
    else:
        up_to, deeper = through, (until_last or 0) + (kind.keeps_open or 0)
        on = "" if through is None else f" through {through}"
        block = f"messages{on} until last {deeper}"
    loaded = OfMessages(
        runtime=of.runtime,
        session=of.session,
        agent=of.agent,
        through=up_to,
        until_last=deeper,
    )
    fold = Fold(
        id=block,
        kind=kind.name,
        summary=[Span(text=said_of, tone="muted")],
        content=Load.of(view, loaded),
    )
    held_back = sight_of(held.folded[-1], block, places).model_copy(
        update={"folded": True}
    )
    return Capped(
        blocks=[fold, *shown], sights=[*([held_back] if new else []), *sights]
    )


def always(turn: Word) -> bool:
    """Count every message among those kept open: each is words to read."""
    del turn
    return True


def nothing_reported(of: OfAgent) -> str:
    """Report no last words of `of`, as where only what the record of `entries` says is shown."""
    del of
    return ""


def messages_blocks(
    of: OfAgent,
    entries: list[Entry],
    exchanged: Exchanged,
    *,
    view: Method,
    report: Report = nothing_reported,
    brief: str | None = None,
    earlier: FoldKind = EARLIER_KIND,
    mark: ReviewMark | None = None,
    reading: Offer | None = None,
) -> Blocks:
    """Lay out an agent's messages as their drawer shows them: its summary line counting them and those new to the operator, what they've read folded under one line, and everything after it open, but for at most the last `earlier` keeps open (`laid`).

    Where any are new, the drawer offers `reading`, marking it read up to its last
    step, Space `d` on its line. A conversation with no words yet is none: an empty
    answer, with no summary line.
    """
    said = messages(entries, exchanged, of, brief)
    if not said:
        return Blocks()
    read = Read.of(mark, entries, exchanged)
    new = sum(1 for each in said[read.reviewed(said) :] if not their_own(each))
    summary = [f"messages · {len(said)}", *([f"{new} new"] if new else [])]
    shown = laid(
        said,
        of,
        exchanged,
        earlier,
        view=view,
        report=report,
        read=read,
        places=positions(merged(entries, inboxed(exchanged))),
    )
    return Blocks(
        summary=[Span(text=" · ".join(summary))],
        offers=[] if reading is None or not new else [reading],
        blocks=shown.blocks,
        sights=sighted(reading, shown.sights),
    )


def earlier_messages_blocks(
    of: OfMessages,
    entries: list[Entry],
    exchanged: Exchanged,
    *,
    view: Method,
    report: Report = nothing_reported,
    brief: str | None = None,
    earlier: FoldKind = EARLIER_KIND,
    mark: ReviewMark | None = None,
    reading: Offer | None = None,
) -> Blocks:
    """Lay out what came earlier among an agent's messages, as its fold in the drawer shows it opened (`OfMessages`): none where nothing did, or the message it's up to is gone, as one the agent's `edit` left saying what no step does."""
    said = messages(entries, exchanged, of, brief)
    if of.through is not None and of.through not in [key(each) for each in said]:
        return Blocks()
    shown = laid(
        said,
        of,
        exchanged,
        earlier,
        view=view,
        report=report,
        read=Read.of(mark, entries, exchanged),
        places=positions(merged(entries, inboxed(exchanged))),
        through=of.through,
        until_last=of.until_last,
    )
    return Blocks(blocks=shown.blocks, sights=sighted(reading, shown.sights))
