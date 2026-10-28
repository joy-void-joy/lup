"""Each item one conversation exchanged, with its line as a view of the conversation shows it: the core words it, so no module names the inbox's kinds.

`docs/inbox.md`, *A conversation's items in its view*. A view of a conversation
(`Transcripts`' drawer) weaves in each item of lup's inbox it sent or was sent,
a line where it happened (`→ @51 question to you · answered by @53`). The
line is made here, for the conversation it's in (`lined`): what the item's
kind says of it (`said`), then what the core says around it: whom it went to,
or whom it came from and for whom, and where it stands. A module weaving the
items in reads each one's line, when it reached the conversation, whether it
repeats the conversation's own words, and the operator's comment on deciding
it, as the core hands them with the items (`Exchanged`), and never matches an
item's reason or state.

`said` is each kind's own words, as the kind's summary view will say them once
each kind is its module's (#113, step 4): the one place here naming the kinds.
"""

from datetime import datetime
from itertools import groupby
from typing import TYPE_CHECKING

from lup.blocks import OfAgent, Span
from lup.types import Model
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

if TYPE_CHECKING:
    from collections.abc import Callable

type Piece = str | Conversation
"""A run of an item's line: its own words, or a conversation it names, said as
the conversation is called and referring to it."""


class Lined(Model):
    """One item a conversation exchanged, as a view of that conversation shows it."""

    item: Item
    sent: bool
    """Whether the conversation sent it, rather than was sent it."""
    line: list[Span]
    """Its line, each conversation it names a span of its own referring to it
    by its runtime's ids, said by its path (`Span.conversation`)."""
    at: datetime
    """When it reached the conversation: when it was told it, else made."""
    comment: str = ""
    """The operator's comment on deciding it, where they decided it with one."""
    echoes: bool = False
    """Whether it repeats the conversation's own words, which a view of it shows
    already: a turn's last words, which lup made a note of."""


def said(item: Item) -> list[Piece]:
    """Say what `item` is, in its kind's own words: a message by its kind, the operator's own as their message or their reply; their answer and review by what they answer; lup's word on citations by how many in which item; a held change, a stop, a flagged write; any other kind by its name.

    >>> from datetime import UTC
    >>> said(Item(number=54, reason=Message(kind="note", text="Good.", of=52),
    ...     sender=Operator(), recipient=Operator(), made=datetime(2026, 10, 18, tzinfo=UTC)))
    ['reply to @52']
    """
    match item.reason, item.sender:
        case Message(of=None), Operator():
            return ["message"]
        case Message(of=int() as of), Operator():
            return [f"reply to {cited(of)}"]
        case Message(kind=kind), _:
            return [kind]
        case Answer(question=question), _:
            return [f"answer to {cited(question)}"]
        case Review(covers=[]), _:
            return ["message, from the review"]
        case Review(covers=covers), _:
            return [f"review of {', '.join(cited(each) for each in covers)}"]
        case Unresolved(of=of, citations=[_]), _:
            return [f"a citation of your words in {cited(of)} named no one passage"]
        case Unresolved(of=of, citations=citations), _:
            return [
                (
                    f"{len(citations)} citations of your words in {cited(of)} "
                    "named no one passage"
                )
            ]
        case HeldChange(), _:
            return ["held change"]
        case Stop(), _:
            return ["stopped"]
        case Flagged(), _:
            return ["flagged write"]
        case reason, _:
            return [reason.reason]


def lups(item: Item) -> bool:
    """Say whether `item` is lup's word to the conversation that sent the item it's about, told to it though it's its own: on its citations that named no passage."""
    return isinstance(item.reason, Unresolved)


def told(party: Conversation, item: Item) -> bool:
    """Say whether `party` was sent `item`, rather than sent it: one from another party, or lup's word to it."""
    return item.sender != party or lups(item)


def lined(
    party: Conversation, items: list[Item], named: Callable[[Conversation], str]
) -> list[Lined]:
    """Return each of `items`, those `party` sent, then those it was sent, with its line as a view of `party` shows it.

    One it sent says `→`, what it is (`said`), whom to, and where it stands:
    withdrawn, decided, superseded, answered and by what, not told yet, waiting
    on the operator, unread, or read. One it was sent says `←`, what it is,
    from whom, for whom where it was passed on from a subagent that had ended,
    or, in that subagent's own view, where it went on to, and whether it's told
    yet. Each conversation a line names is a span of its own, said as `named`
    calls it, referring to it by its runtime's ids (`Span.conversation`), which
    never change as it's renamed.
    """
    received = [each for each in items if told(party, each)]

    def spanned(pieces: list[Piece]) -> list[Span]:
        def referring(conversation: Conversation) -> Span:
            of = OfAgent(
                runtime=conversation.runtime,
                session=conversation.session,
                agent=conversation.agent,
            )
            return Span(text=named(conversation), conversation=of)

        runs = groupby(pieces, key=lambda each: isinstance(each, str))
        return [
            span
            for plain, run in runs
            for span in (
                [Span(text="".join(each for each in run if isinstance(each, str)))]
                if plain
                else [referring(each) for each in run if isinstance(each, Conversation)]
            )
        ]

    def dotted(*parts: list[Piece] | str | None) -> list[Piece]:
        kept = [[each] if isinstance(each, str) else each for each in parts if each]
        return [
            piece
            for at, part in enumerate(kept)
            for piece in [*([" · "] if at else []), *part]
        ]

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

        found = [each.number for each in received if answers(each)]
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

    def echoes(item: Item) -> bool:
        match item.reason:
            case Message(ending=True):
                return True
            case _:
                return False

    def its(item: Item) -> Lined:
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
        head = [f"→ {cited(item.number)} ", *said(item), " to ", to]
        return Lined(
            item=item,
            sent=True,
            line=spanned(dotted(head, standing(item))),
            at=item.made,
            comment=comment,
            echoes=echoes(item),
        )

    def came(item: Item) -> list[Piece]:
        if lups(item):
            return ["from lup: ", *said(item)]
        match item.sender:
            case Conversation() as sender:
                return [*said(item), " from ", sender]
            case Operator():
                return ["your ", *said(item)]

    def theirs(item: Item) -> Lined:
        passed = item.addressed
        ours = passed is not None and passed.agent == party.agent
        head = [f"← {cited(item.number)} ", *came(item)]
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
                waiting, at = "not told yet", item.made
            case Told(at=at):
                waiting = None
            case _:
                waiting, at = None, item.made
        return Lined(
            item=item,
            sent=False,
            line=spanned(dotted(head, waiting, onward)),
            at=at,
        )

    return [
        *(its(each) for each in items if not told(party, each)),
        *(theirs(each) for each in received),
    ]
