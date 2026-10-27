"""A conversation laid out in lup's building blocks: the drawer under its agent's banner, one earlier exchange, and one call read whole.

`docs/dashboard.md`, *The drawers*, its **Conversation** entry. Each is a pure
layout answering `Blocks`, the layout of one of `Transcripts`' views:
- `conversation_blocks`, the drawer: its summary line counting the steps, each
  exchange before the operator's last words folded under the first line of
  their words that opened it, what came before their first words under a line
  of its own, and everything since their last words open;
- `exchange_blocks`, one earlier exchange's steps, which its fold reads as it
  opens (`OfExchange`), so the drawer's answer stays small however long the
  conversation grows;
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
`exchange 5` (or `exchange before`), `calls 2`, `call <the call's id>` or
`item 51`; a line is `step 6` (`step 6.1` on, for the operator's further
lines), `item 64 line` for an item with no text, `text 51` for an item's text,
and `input <id>`, `output <id>` (`.1` on) or `unread <id>` in a call's view.
"""

import json
from collections.abc import Callable
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
    Span,
    Tone,
)
from lup.types import Model
from lup_dev.host.records import Called, Entry, Said
from lup_dev.inbox.protocol import Exchanged
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Conversation,
    Decided,
    Done,
    Flagged,
    HeldChange,
    Item,
    Message,
    Operator,
    Review,
    Stop,
    Superseded,
    Told,
    Unresolved,
    Waiting,
    Withdrawn,
    cited,
)
from lup_transcripts.environment.views import folded
from lup_transcripts.errors import LupTranscriptsError

if TYPE_CHECKING:
    from pydantic import JsonValue

    from lup.doors import Method
    from lup_dev.host.records import Call


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
    called="earlier exchanges",
    one="the earlier exchange",
    level=1,
    opens="back",
    colour="ok",
)
"""Each exchange before the operator's last words, under the first line of their
words that opened it: `zr` opens the latest still folded, each one a step
further back."""
CALLS_KIND = FoldKind(
    name="calls",
    letter="k",
    called="runs of calls",
    one="the run of calls",
    level=2,
    colour="purple",
)
"""A run of calls, under one line saying how many of which."""
ITEMS_KIND = FoldKind(
    name="items",
    letter="m",
    called="items' text",
    one="the item's text",
    level=3,
    colour="cyan",
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
    """One exchange of an agent's conversation, as its fold in the drawer reads it: by the operator's words that open it."""

    step: int | None = Field(
        default=None,
        description="The step of your words that open it; left out, what came before your first words.",
    )


class OfCall(OfAgent):
    """One call of an agent's conversation, read whole as its fold in the drawer opens."""

    id: str = Field(description="The runtime's id for the call.")


class Beside(Model):
    """What a conversation shows beside its steps: the items of lup's inbox it exchanged, and how a conversation among their parties is called."""

    exchanged: Exchanged = Exchanged(sent=[], received=[])
    named: Callable[[Conversation], str]
    """A conversation's name as the operator reads it: its path, as `lup-impl/a04`,
    else its runtime's ids."""


class Spoken(Model):
    """Something said at one step: the operator's words, or the agent's."""

    step: int
    said: Said


class Calling(Model):
    """A tool called at one step."""

    step: int
    called: Called


type Piece = str | Conversation
"""A run of an item's line: its own text, or a conversation it names, said as
the conversation is called and referring to it."""


class Inboxed(Model):
    """An item of lup's inbox as the conversation shows it: its line, its text folded under it, and where it goes among the steps."""

    number: int
    sent: bool
    """Whether the conversation sent it, rather than was sent it."""
    line: list[Span]
    """Its line, in the tone of what it is, each conversation it names a span
    of its own referring to it (`Span.conversation`)."""
    text: str
    """Its text as it's folded under its line, with the operator's comment on
    their decision after it; empty where there's none."""
    call: str | None = None
    """The call that made it, for one the conversation sent where the record
    keeps the call's id: it goes just after it."""
    at: datetime
    """When it was told the conversation, or made: where it goes among the steps
    when no call places it."""


type Turn = Spoken | Calling | Inboxed
"""One step of the conversation, or an item of lup's inbox between its steps."""


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


def what(item: Item) -> str:
    """Say what an item is, in a word or two: a message's kind, a question, an answer, a review, a held change, an approval, a friction, how it went, a stop, a flagged write."""
    match item.reason:
        case Message(kind=kind):
            return kind
        case HeldChange():
            return "held change"
        case Stop():
            return "stopped"
        case Flagged():
            return "flagged write"
        case reason:
            return reason.reason


def inboxed(beside: Beside, agent: str | None) -> list[Inboxed]:
    """Return the items the conversation exchanged as it shows them, those it sent first, then those it was sent; `agent` is its subagent's id, none for its session's own.

    One it sent says `→`, what it is, whom to, and where it stands: answered and
    by what, read, waiting on the operator, unread, withdrawn, decided. One it
    was sent says `←`, what it is, for whom where it was passed on, and whether
    it's told yet. A turn's last words, which lup made a note, are left out:
    they're the agent's words, already shown. Each conversation a line names
    is said as `beside` calls it, in a span referring to it by its runtime's
    ids.
    """
    sent, received = beside.exchanged.sent, beside.exchanged.received
    named = beside.named

    def answering(item: Item) -> list[int]:
        def answers(each: Item) -> bool:
            match each.reason:
                case Answer(question=question):
                    return question == item.number
                case Message(of=of):
                    return of == item.number
                case Review(covers=covers):
                    return item.number in covers
                case _:
                    return False

        found = [each.item.number for each in received if answers(each.item)]
        match item.state:
            case Answered(answer=answer):
                answered = [answer]
            case _:
                answered = []
        return sorted(dict.fromkeys([*answered, *found]))

    def standing(item: Item) -> str | None:
        match item.state:
            case Withdrawn(why=why):
                return f"withdrawn: {why}"
            case Decided(approved=approved):
                return "approved" if approved else "declined"
            case Superseded(by=by):
                return f"superseded by {cited(by)}"
            case _:
                pass
        answers = answering(item)
        if answers:
            return f"answered by {', '.join(cited(each) for each in answers)}"
        match item.state:
            case Waiting() if not isinstance(item.recipient, Operator):
                return "not told yet"
            case Waiting():
                return (
                    "waiting on you" if item.rank.name == "waiting on you" else "unread"
                )
            case Done():
                return "read"
            case _:
                return None

    def came(item: Item) -> list[Piece]:
        match item.reason, item.sender:
            case Unresolved(of=of, citations=[_]), _:
                return [
                    f"from lup: a citation of your words in {cited(of)} named no one passage"
                ]
            case Unresolved(of=of, citations=citations), _:
                return [
                    (
                        f"from lup: {len(citations)} citations of your words in "
                        f"{cited(of)} named no one passage"
                    )
                ]
            case _, Conversation() as sender:
                return [f"{what(item)} from ", sender]
            case Answer(question=question), _:
                return [f"your answer to {cited(question)}"]
            case Review(covers=[]), _:
                return ["your message, from the review"]
            case Review(covers=covers), _:
                return [f"your review of {', '.join(cited(each) for each in covers)}"]
            case Message(of=None), _:
                return ["your message"]
            case Message(of=int() as of), _:
                return [f"your reply to {cited(of)}"]
            case _:
                return [f"your {what(item)}"]

    def dotted(first: list[Piece], *parts: str | list[Piece] | None) -> list[Piece]:
        kept = [
            first,
            *(
                [each] if isinstance(each, str) else each
                for each in parts
                if each is not None
            ),
        ]
        return [
            piece
            for at, part in enumerate(kept)
            for piece in [*([" · "] if at else []), *part]
        ]

    def spanned(pieces: list[Piece], tone: Tone) -> list[Span]:
        def referring(party: Conversation) -> Span:
            of = OfAgent(
                runtime=party.runtime, session=party.session, agent=party.agent
            )
            return Span(text=named(party), tone=tone.name, conversation=of)

        runs = groupby(pieces, key=lambda each: isinstance(each, str))
        return [
            span
            for plain, run in runs
            for span in (
                [
                    Span(
                        text="".join(each for each in run if isinstance(each, str)),
                        tone=tone.name,
                    )
                ]
                if plain
                else [referring(each) for each in run if isinstance(each, Conversation)]
            )
        ]

    def text(said: str, comment: str) -> str:
        parts = [said, *([f"your comment: {comment}"] if comment else [])]
        return "\n".join(kept("\n\n".join(parts)))

    def ending(item: Item) -> bool:
        match item.reason:
            case Message(ending=True):
                return True
            case _:
                return False

    def its(item: Item, said: str) -> Inboxed:
        match item.recipient:
            case Conversation() as recipient:
                to: Piece = recipient
            case Operator():
                to = "you"
        match item.state:
            case Decided(comment=comment):
                pass
            case _:
                comment = ""
        head: list[Piece] = [f"→ {cited(item.number)} {what(item)} to ", to]
        return Inboxed(
            number=item.number,
            sent=True,
            line=spanned(dotted(head, standing(item)), SENT_TONE),
            text=text(said, comment),
            call=item.call,
            at=item.made,
        )

    def theirs(item: Item, said: str) -> Inboxed:
        passed = item.addressed
        ours = passed is not None and passed.agent == agent
        head: list[Piece] = [f"← {cited(item.number)} ", *came(item)]
        if passed is not None and not ours:
            head = [*head, ", for ", passed, ", which had ended"]
        match item.recipient:
            case Conversation() as recipient if ours:
                onward: list[Piece] | None = [
                    "passed on to ",
                    recipient,
                    ", this one having ended",
                ]
            case _:
                onward = None
        match item.state:
            case Waiting():
                told, at = "not told yet", item.made
            case Told(at=at):
                told = None
            case _:
                told, at = None, item.made
        return Inboxed(
            number=item.number,
            sent=False,
            line=spanned(dotted(head, told, onward), RECEIVED_TONE),
            text=text(said, ""),
            at=at,
        )

    return [
        *(its(each.item, each.text) for each in sent if not ending(each.item)),
        *(theirs(each.item, each.text) for each in received),
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
    """Lay `turns` out in blocks, in order: the operator's words, the agent's, each call a line saying what it did, each run of `run` calls or more folded under one line saying how many of which, and each item a line with its text folded under it.

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
                content=[call(each) for each in calls],
            )
        ]

    runs = groupby(turns, key=lambda each: isinstance(each, Calling))
    return [block for _, group in runs for block in laid(list(group))]


def conversation_blocks(
    of: OfAgent,
    entries: list[Entry],
    beside: Beside,
    *,
    exchange: Method,
    call: Method,
    run: int = 3,
) -> Blocks:
    """Lay out an agent's conversation as its drawer shows it: its summary line counting its steps, each exchange before the operator's last words folded under the first line of their words, and everything since those words open.

    What came before their first words folds under a line of its own, saying
    how many steps and items and how long before their words. Each earlier
    exchange is read from `exchange`, one exchange's view, as it opens, and
    each call's input and output from `call`, one call's view (`turned`). A
    conversation with no steps is none: an empty answer, with no summary line.
    """
    if not entries:
        return Blocks()
    *earlier, latest = parts(merged(entries, inboxed(beside, of.agent)))

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
            kind=EARLIER_KIND.name,
            summary=summary(part, until),
            content=Load.of(exchange, read),
        )

    opened = [] if latest.opening is None else words(latest.opening)
    return Blocks(
        summary=[Span(text=f"conversation · {counted(len(entries), 'step')}")],
        blocks=[
            *(folded_part(part, until) for part, until in pairwise([*earlier, latest])),
            *opened,
            *turned(latest.turns, of, call, run),
        ],
    )


def exchange_blocks(
    of: OfExchange,
    entries: list[Entry],
    beside: Beside,
    *,
    call: Method,
    run: int = 3,
) -> Blocks:
    """Lay out one exchange of an agent's conversation as its fold in the drawer shows it opened: the operator's further lines of the words that open it, then each step and item up to their next words.

    The first line of their words is the fold's summary, so it isn't laid out
    again. For what came before their first words, every step and item there;
    none where nothing came before them. Each call's input and output is read
    from `call`, one call's view, as it opens.

    Raise `ConversationError` where `of.step` isn't a step of the operator's
    words.
    """
    found = [
        part
        for part in parts(merged(entries, inboxed(beside, of.agent)))
        if part.step() == of.step
    ]
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
    further = [] if part.opening is None else words(part.opening)[1:]
    return Blocks(blocks=[*further, *turned(part.turns, of, call, run)])


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
