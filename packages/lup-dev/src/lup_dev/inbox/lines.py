"""Each item one conversation exchanged, with its line as a view of the conversation shows it: the core words it, so no module names the inbox's kinds.

`docs/inbox.md`, *A conversation's items in its view*. A view of a conversation
(`Transcripts`' drawer) weaves in each item of lup's inbox they sent or were sent,
a line where it happened (`→ @51 question to you · answered by @53`). The
line is made here, for the conversation it's in (`lined`): what the item's
kind says of it (`said`), then what the core says around it: whom it went to,
or whom it came from and for whom, and where it stands. A module weaving the
items in reads each one's line, when it reached the conversation, whether it
repeats the conversation's own words or the input of the call that made it, and
the operator's comment on deciding it, as the core hands them with the items
(`Exchanged`), and never matches an item's reason or state.

A view of the conversation's words alone (`Transcripts`' `messages`) reads each
one's heading instead (`Lined.heading`): who says it to whom, what it is, and
where it stands (`@53 you → lup-impl/parser · answer to @51`). An item that's no
words of theirs has none (`worded`). The operator's copy of a message between
conversations is neither sent nor received: the message itself is (`copy`).

`said` is each kind's own words, as the kind's summary view will say them once
each kind is its module's (#113, step 4): the one place here naming the kinds.

What lup told the conversation in no item, its lines left for them (`Left`), is
worded here too (`relayed`): lup's own line as lup's (`lup → lup-impl/parser`),
and someone's words a line carried whole as theirs reaching the conversation,
saying how (`@812.1 you → lup-impl/parser · moved by lup-impl into @lag`).
"""

from datetime import datetime
from itertools import groupby
from typing import TYPE_CHECKING

from lup.blocks import OfAgent, Span
from lup.types import Model
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Approval,
    Decided,
    Done,
    Ended,
    Flagged,
    Friction,
    HeldChange,
    Item,
    Left,
    Message,
    Review,
    Stop,
    Superseded,
    Told,
    Unresolved,
    Waiting,
    Withdrawn,
    cited,
)
from lup_ledger.parties import Conversation, Operator

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

type Piece = str | Conversation
"""A run of an item's line: its own words, or a conversation it names, said as
the conversation is called and referring to them."""


class Lined(Model):
    """One item a conversation exchanged, as a view of that conversation shows it."""

    item: Item
    sent: bool
    """Whether the conversation sent it, rather than was sent it."""
    line: list[Span]
    """Its line, each conversation it names a span of their own referring to
    them by their runtime's ids, said by their path (`Span.conversation`)."""
    at: datetime
    """When it reached the conversation: when it was told it, else made."""
    comment: str = ""
    """The operator's comment on deciding it, where they decided it with one."""
    echoes: bool = False
    """Whether it repeats the conversation's own words, which a view of it shows
    already: a turn's last words, which lup made a note of."""
    call_sends_it: bool = False
    """Whether sending it is all the call that made it did, that call's input
    being its text: one of lup's tools, as `note` or `ask`, rather than a write
    lup flagged or held."""
    by: OfAgent | None = None
    """Who wrote it, where it's another conversation than this one: whom a
    comment on its text goes to, whichever drawer it's written in."""
    heading: list[Span] | None = None
    """Its line among the conversation's words alone: who says it to whom, what
    it is, and where it stands (`@53 you → lup-impl/parser · answer to @51`),
    each conversation a span of their own as in `line`; none where it's no words
    of theirs (`worded`)."""
    reported: bool = False
    """Whether what its sender said with it is their last words, which their
    runtime hands their parent and only their record holds: a subagent's end."""


def said(item: Item) -> list[Piece]:
    """Say what `item` is, in its kind's own words: a turn's last words as their kind is named (`turn's end`, `inbox/texts.py`), a message by its kind, the operator's own as their message or their reply; their answer and review by what they answer; lup's word on citations by how many in which item; a held change, a stop, a flagged write; a concern's words as a concern, as `kind` names them; any other kind by its name.

    >>> from datetime import UTC
    >>> said(Item(number=54, reason=Message(kind="note", text="Good.", of=52),
    ...     sender=Operator(), recipient=Operator(), made=datetime(2026, 10, 18, tzinfo=UTC)))
    ['reply to @52']
    """
    match item.reason, item.sender:
        case Message(ending=True), _:
            return ["turn's end"]
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
        case Friction(), _:
            return ["concern"]
        case reason, _:
            return [reason.reason]


def lups(item: Item) -> bool:
    """Say whether `item` is lup's word to the conversation that sent the item it's about, told to them though it's their own: on their citations that named no passage."""
    return isinstance(item.reason, Unresolved)


def told(party: Conversation, item: Item) -> bool:
    """Say whether `party` was sent `item`, rather than sent it: one from another party, or lup's word to them."""
    return item.sender != party or lups(item)


def copy(item: Item) -> bool:
    """Say whether `item` is the operator's copy of a message one conversation sent another, which keeps it in a thread (`Concerns.landed`): the message itself is what they exchanged, and a view of them shows that."""
    match item.reason:
        case Message(to=Conversation()):
            return True
        case _:
            return False


def reported(item: Item) -> bool:
    """Say whether `item` is a subagent's plain end of their turn whose last words their runtime hands their parent, so no item holds them."""
    match item.reason:
        case Ended(handed=True, stopped=False, failed=None):
            return True
        case _:
            return False


def worded(item: Item, party: Conversation) -> bool:
    """Say whether `item` is words `party`'s conversation shows as said, rather than something done: not a write lup flagged or held, an approval, or lup's word on citations; and not the news of a subagent's their parent is told (`Item.quiet`) in the subagent's own view, the words being theirs already, to the operator or among their steps."""
    match item.reason:
        case Flagged() | HeldChange() | Approval() | Unresolved():
            return False
        case _:
            return not (item.quiet and item.sender == party)


def of_agent(conversation: Conversation) -> OfAgent:
    """Refer to `conversation` by their runtime's ids, which never change as they're renamed."""
    return OfAgent(
        runtime=conversation.runtime,
        session=conversation.session,
        agent=conversation.agent,
    )


def spans(pieces: list[Piece], named: Callable[[Conversation], str]) -> list[Span]:
    """Return `pieces` as a line's spans: each run of words one span, each conversation a span of their own, said as `named` calls them, referring to them by their runtime's ids (`Span.conversation`)."""
    runs = groupby(pieces, key=lambda each: isinstance(each, str))
    return [
        span
        for plain, run in runs
        for span in (
            [Span(text="".join(each for each in run if isinstance(each, str)))]
            if plain
            else [
                Span(text=named(each), conversation=of_agent(each))
                for each in run
                if isinstance(each, Conversation)
            ]
        )
    ]


def dotted(*parts: list[Piece] | str | None) -> list[Piece]:
    """Return `parts` one after the other, a ` · ` between each, those that are none or empty left out.

    >>> dotted(["@5 note"], None, "read")
    ['@5 note', ' · ', 'read']
    """
    kept = [[each] if isinstance(each, str) else each for each in parts if each]
    return [
        piece
        for at, part in enumerate(kept)
        for piece in [*([" · "] if at else []), *part]
    ]


class Relay(Model):
    """One of lup's lines left for a conversation (`Left`), as a view of that conversation shows it: lup's own line, or someone's words it carried them whole."""

    left: Left
    line: list[Span]
    """Its line among the conversation's steps: `← from lup`, or what it carries
    and how it came (`← @7 note from lup-impl/parser, landed in @lag`)."""
    heading: list[Span]
    """Its heading among the conversation's words alone, who says it to whom:
    `lup → lup-impl/fixer`, or `@812.1 you → lup-impl/fixer · moved by lup-impl
    into @lag`."""
    at: datetime
    """When it reached the conversation: when it was told them, else left."""
    carried: Item | None = None
    """The item it carries, whole or a part of it, where it carries one the
    inbox holds; none for lup's own line."""
    part: int | None = None
    """The part of the operator's words in `carried` it carries, where it carries
    one part."""
    by: OfAgent | None = None
    """Who wrote what it carries, where that's another conversation: whom a
    comment on its text goes to."""


def relayed(
    party: Conversation,
    lines: list[Left],
    items: Mapping[int, Item],
    threads: Callable[[int], str | None],
    named: Callable[[Conversation], str],
) -> list[Relay]:
    """Return each of lup's `lines` left for `party`, oldest first, as a view of `party` shows it, saying `not told yet` where they aren't.

    One carrying someone's words whole, an item of `items` landing in a
    thread or moved there, or a part of the operator's words moved there,
    shows as those words reaching `party`, its writer's and of its kind, saying
    in which thread, by its name as `threads` says it, and how it came there:
    `landed`, or moved by whom. Any other, or one whose item or thread is gone,
    is lup's own line to them, `lup → lup-impl/fixer`, never the operator's,
    though it says what the operator did.
    """

    def one(left: Left) -> Relay:
        waiting = "not told yet" if left.told is None else None
        at = left.at if left.told is None else left.told
        carries = left.carries
        item = None if carries is None else items.get(carries.item)
        name = None if carries is None else threads(carries.thread)
        if carries is None or item is None or name is None:
            return Relay(
                left=left,
                line=spans(dotted(["← from lup"], waiting), named),
                heading=spans(dotted(["lup → ", party], waiting), named),
                at=at,
            )
        match carries.moved:
            case None:
                came: list[Piece] = [f"landed in @{name}"]
            case Operator():
                came = [f"moved by you into @{name}"]
            case Conversation() as mover:
                came = ["moved by ", mover, f" into @{name}"]
        writer: Piece = item.sender if isinstance(item.sender, Conversation) else "you"
        if carries.part is not None:
            said_as = f"{cited(item.number)}.{carries.part}"
            return Relay(
                left=left,
                line=spans(
                    dotted([f"← {said_as} your words, ", *came], waiting), named
                ),
                heading=spans(
                    dotted([f"{said_as} ", writer, " → ", party], came, waiting), named
                ),
                at=at,
                carried=item,
                part=carries.part,
            )
        whose: list[Piece] = (
            [*said(item), " from ", item.sender]
            if isinstance(item.sender, Conversation)
            else ["your ", *said(item)]
        )
        return Relay(
            left=left,
            line=spans(
                dotted(
                    [f"← {cited(item.number)} ", *whose, ", ", *came],
                    waiting,
                ),
                named,
            ),
            heading=spans(
                dotted(
                    [f"{cited(item.number)} ", writer, " → ", party],
                    list(said(item)),
                    came,
                    waiting,
                ),
                named,
            ),
            at=at,
            carried=item,
            by=of_agent(item.sender)
            if isinstance(item.sender, Conversation) and item.sender != party
            else None,
        )

    return [one(each) for each in lines]


def lined(
    party: Conversation, items: list[Item], named: Callable[[Conversation], str]
) -> list[Lined]:
    """Return each of `items`, those `party` sent, then those they were sent, with its line as a view of `party` shows it.

    One they sent says `→`, what it is (`said`), whom to, and where it stands:
    withdrawn, decided, superseded, answered and by what, not told yet, waiting
    on the operator, unread, or read. One they were sent says `←`, what it is,
    from whom, for whom where it was passed on from a subagent that had ended,
    or, in that subagent's own view, where it went on to, and whether it's told
    yet. Each conversation a line names is a span of its own, said as `named`
    calls them, referring to them by their runtime's ids (`Span.conversation`),
    which never change as they're renamed.
    """
    items = [each for each in items if not copy(each)]
    received = [each for each in items if told(party, each)]

    def spanned(pieces: list[Piece]) -> list[Span]:
        return spans(pieces, named)

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

    def sends(item: Item) -> bool:
        match item.reason:
            case Flagged() | HeldChange():
                return False
            case _:
                return item.call is not None

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
        match to:
            case Conversation():
                whom: Piece = to
            case _:
                whom = "you"
        return Lined(
            item=item,
            sent=True,
            line=spanned(dotted(head, standing(item))),
            at=item.made,
            comment=comment,
            echoes=echoes(item),
            call_sends_it=sends(item),
            heading=spanned(
                dotted(
                    [f"{cited(item.number)} ", party, " → ", whom],
                    list(said(item)),
                    standing(item),
                )
            )
            if worded(item, party)
            else None,
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
        match item.sender:
            case Conversation() as sender:
                writer: Piece = sender
                by = OfAgent(
                    runtime=sender.runtime, session=sender.session, agent=sender.agent
                )
            case _:
                writer, by = "you", None
        whom = passed if passed is not None else party
        passing = (
            None
            if passed is None
            else ["passed on to ", item.recipient]
            if isinstance(item.recipient, Conversation)
            else None
        )
        return Lined(
            item=item,
            sent=False,
            line=spanned(dotted(head, waiting, onward)),
            at=at,
            by=by,
            reported=reported(item),
            heading=spanned(
                dotted(
                    [f"{cited(item.number)} ", writer, " → ", whom],
                    list(said(item)),
                    waiting,
                    passing,
                )
            )
            if worded(item, party)
            else None,
        )

    return [
        *(its(each) for each in items if not told(party, each)),
        *(theirs(each) for each in received),
    ]
