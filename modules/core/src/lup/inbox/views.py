"""What the inbox shows the operator, as the shell's blocks: the list of parties, a party's buffer, a concern, and what waits on them.

Each view is a method of `Inboxes`, which holds the store; what it lays out is
made here, from one repository's inbox, the views it opens next handed in as
`Shows`. A block keeps an id that stays put as the inbox changes (`party-3`,
`concern-12`, `item-40`), and a comment on it reaches the party it's about:
whoever wrote an item, whoever holds a concern, the party a buffer is
(`README.md` here, *What the operator sees*).
"""

from lup.doors.door import Method
from lup.inbox.records import AgentRecord, Concern, Item, PartyRecord, PileRecord
from lup.inbox.said import (
    Clearing,
    ConcernOf,
    Declining,
    OnItem,
    PartyOf,
    Pile,
    Showing,
)
from lup.shell.blocks import Block, Blocks, Fold, Line, Markdown, Offer, Span, Viewing
from lup.types import Model
lazy from lup.doors.parties import Party
lazy from lup.inbox.inbox import Inbox


class Shows(Model, arbitrary_types_allowed=True):
    """The inbox's views a block opens, and the actions its blocks offer: commenting on an item, clearing, declining, and saying what's been seen."""

    party: Method
    concern: Method
    comment: Method
    clear: Method
    decline: Method
    seen: Method


def reached(inbox: Inbox, party: PartyRecord) -> Party | None:
    """Return the party a comment on `party`'s blocks reaches: the agent, or the pile, which keeps it; none for the operator, whose own they are."""
    match party:
        case AgentRecord():
            return party.caller()
        case PileRecord():
            return Pile(repository=inbox.repository, path=party.name or "")
        case _:
            return None


def party_fold(inbox: Inbox, party: PartyRecord, shows: Shows) -> Fold:
    """Return `party` as a fold of a list: its name, what it holds, and what of it is new or waits; its buffer read as it opens."""
    held = inbox.holding(party)
    new = len(inbox.new_involving(party))
    done = sum(1 for each in held if inbox.standing(each).waits())
    counts = [
        f"{len(held)} held" if held else "",
        f"{new} new" if new else "",
        f"{done} done, to clear" if done else "",
    ]
    said = ", ".join(each for each in counts if each)
    return Fold(
        id=f"party-{party.key}",
        kind="party",
        summary=[
            Span(text=inbox.called(party), tone="strong"),
            Span(text=f"  {said}" if said else "", tone="muted"),
        ],
        content=Viewing.of(
            shows.party,
            PartyOf(repository=inbox.repository, name=inbox.called(party)),
        ),
        reaches=reached(inbox, party),
    )


def concern_fold(inbox: Inbox, concern: Concern, shows: Shows) -> Fold:
    """Return `concern` as a fold: its title, its kind where it's a friction, and its marks; what's in it read as it opens."""
    standing = inbox.standing(concern)
    marks = [
        "friction" if concern.kind == "inbox:friction" else "",
        f"left by {inbox.called(standing.left_by)}" if standing.left_by else "",
        "declined" if standing.declined is not None else "",
    ]
    said = ", ".join(each for each in marks if each)
    stands = (
        "done"
        if standing.cleared or standing.declined is not None
        else "waiting"
        if standing.done is not None
        else "new"
        if inbox.fresh(concern)
        else None
    )
    return Fold(
        id=f"concern-{concern.number}",
        kind="concern",
        standing=stands,
        summary=[
            Span(text=f"{inbox.called(concern)} ", tone="muted"),
            Span(text=concern.title, tone="strong"),
            Span(text=f"  {said}" if said else "", tone="muted"),
        ],
        content=Viewing.of(shows.concern, ConcernOf(number=concern.number or 0)),
        reaches=reached(inbox, standing.holder),
        offers=[
            Offer.of(
                shows.clear,
                Clearing(repository=inbox.repository, what=str(concern.number)),
            ),
            Offer.of(shows.decline, Declining(concern=concern.number or 0)),
        ],
    )


def item_blocks(inbox: Inbox, item: Item, shows: Shows) -> list[Block]:
    """Return `item` as its heading, who wrote it, of what kind, its number, whether it's new or waits, then its words; then, for a module's own kind of item, the fold its kind lays out, opening on the module's view.

    Each of its blocks offers a comment on it, and what its kind offers beside;
    clearing it where its kind offers nothing under that verb, so Space d on an
    item clears the item, never the concern around it.
    """
    new = inbox.unseen(item)
    waits = item in inbox.waits_on_operator()
    writer = inbox.by(item)
    number = item.number or 0
    laid = item.laid()
    kind = [] if laid is None else laid.offers
    clearing = Offer.of(
        shows.clear, Clearing(repository=inbox.repository, what=str(number))
    )
    offers = [
        Offer.of(shows.comment, OnItem(item=number)),
        *([] if any(each.verb == clearing.verb for each in kind) else [clearing]),
        *kind,
    ]
    folded: list[Block] = (
        []
        if laid is None
        else [
            Fold(
                id=f"item-{item.number}-laid",
                kind=laid.fold,
                summary=[Span(text=laid.summary)],
                content=laid.opens,
                offers=offers,
            )
        ]
    )
    return [
        Line(
            id=f"item-{item.number}",
            spans=[
                Span(text=inbox.writer(item), tone="strong"),
                Span(
                    text=f" · {item.kind.removeprefix('inbox:')} · @{item.number}",
                    tone="muted",
                ),
            ],
            standing="waiting" if waits else "new" if new else None,
            offers=offers,
            sighted=Offer.of(shows.seen, Showing(items=[number])),
        ),
        Markdown(
            id=f"item-{item.number}-text",
            text=item.text,
            tone="operator" if writer.key == inbox.operator().key else "plain",
            offers=offers,
        ),
        *folded,
    ]


def parties(inbox: Inbox, shows: Shows) -> Blocks:
    """Return the list of parties: each at the top, an agent no other spawned or a pile under none, each opening on its buffer."""
    return Blocks.of(*(party_fold(inbox, each, shows) for each in inbox.top()))


def buffer(inbox: Inbox, party: PartyRecord, shows: Shows) -> Blocks:
    """Return `party`'s buffer: the concerns it holds, the parties under it, then what it said or was told outside any concern."""
    return Blocks.of(
        *(concern_fold(inbox, each, shows) for each in inbox.holding(party)),
        *(party_fold(inbox, each, shows) for each in inbox.beneath(party)),
        *(
            block
            for item in inbox.loose(party)
            for block in item_blocks(inbox, item, shows)
        ),
    )


def concern(inbox: Inbox, concern: Concern, shows: Shows) -> Blocks:
    """Return `concern` whole: its body, the concerns under it, then what's been said in it."""
    body = (
        [Markdown(id=f"concern-{concern.number}-body", text=concern.body, tone="muted")]
        if concern.body
        else []
    )
    return Blocks.of(
        *body,
        *(concern_fold(inbox, each, shows) for each in inbox.nested(concern)),
        *(
            block
            for item in inbox.said_in(concern)
            for block in item_blocks(inbox, item, shows)
        ),
    )


def waiting(inbox: Inbox, shows: Shows) -> Blocks:
    """Return what waits on the operator, oldest first: each item they're to answer, then each concern its agent says is done."""
    blocks: list[Block] = [
        block
        for each in inbox.waits_on_operator()
        if isinstance(each, Item)
        for block in item_blocks(inbox, each, shows)
    ]
    concerns = [
        concern_fold(inbox, each, shows)
        for each in inbox.waits_on_operator()
        if isinstance(each, Concern)
    ]
    return Blocks.of(*blocks, *concerns)
