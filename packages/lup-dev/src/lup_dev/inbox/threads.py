"""The operator's words as parts, each with an id: the parts of their items an agent cites, where a quoted passage lies in an item.

`docs/inbox.md`, *Parts and ids*. The operator's words reach an agent in items
with parts of their own: what they said on its items (`anchors`), a review's
comments, in its order; the comment a reply to a note carries; each passage's
reply in a message sent from reading a conversation; an answer's rulings, then
its comment; and, after those, the rest of their words (`spoken`), a review's
messages and remarks, a message's words on the whole. Each has an id, `546.2`,
which the tags carry (`<reply id="546.2">`) and an agent's citation names
(`inbox/citations.py`).

A passage the operator quoted is found in the item it's of by the part it
starts in (`located`): by its offsets where the item's text is what the
dashboard showed, else by its first line where that's in one part alone. The
tag then carries the part's id and the quote's first line, since the agent has
its own words and the id finds the rest; a passage of a changed file's lines,
which no part holds, is quoted whole, as before.
"""

import textwrap

from lup.types import Model
from lup_dev.inbox.parts import Part, PartId, blocks
from lup_dev.inbox.store import (
    Answer,
    Conversation,
    Item,
    Message,
    Operator,
    Quote,
    Review,
    Verdict,
)


class Anchor(Model):
    """One part of an item of the operator's, which an agent cites by its id: their words at one place, and what the place is."""

    id: PartId
    text: str
    """The operator's words there: a comment, a message, a ruling's comment."""
    item: int | None = None
    """The agent's item it's on; none where it's on a passage of the agent's
    conversation, which the operator read there, or on nothing."""
    quote: Quote | None = None
    """The passage it's on: of the item's text, or of the reply `on`; none for
    a comment on the item whole, or a ruling."""
    on: PartId | None = None
    """The agent's reply it answers, where it's a comment copies before kept
    on a reply (`Comment.on`)."""
    to: Conversation | None = None
    """Whom a review's message or remark was written to; none for any other
    part."""
    decision: int | None = None
    """The decision it rules on, from 1, for an answer's ruling."""
    verdict: Verdict | None = None
    """Its verdict, for a ruling with one."""


def anchors(item: Item) -> list[Anchor]:
    """Return the parts of `item` that are the operator's words on what an agent said, in the item's order, numbered from 1: none for an item that isn't the operator's words on an agent's.

    A review's are its comments, in its order, those on other agents' items
    counted so the numbers hold for every agent it reaches; a reply's its one
    comment; a message's from reading a conversation each passage's reply,
    its words on the whole left for `spoken`; an answer's each ruling, then
    its comment.
    """

    def numbered(at: int) -> PartId:
        return PartId(item=item.number, part=at)

    match item.reason:
        case Review(comments=comments):
            return [
                Anchor(
                    id=numbered(at),
                    text=each.text,
                    item=each.item,
                    quote=each.quote,
                    on=each.on,
                )
                for at, each in enumerate(comments, start=1)
            ]
        case Message(of=int() as of, text=text):
            return [Anchor(id=numbered(1), text=text, item=of)]
        case Message(passages=passages):
            return [
                Anchor(
                    id=numbered(at),
                    text=each.text,
                    quote=Quote(text=each.quote, start=0, end=len(each.quote)),
                )
                for at, each in enumerate(passages, start=1)
            ]
        case Answer(question=question, rulings=rulings, comment=comment):
            ruled = [
                Anchor(
                    id=numbered(at),
                    text=each.comment,
                    item=question,
                    decision=each.decision,
                    verdict=each.verdict,
                )
                for at, each in enumerate(rulings, start=1)
            ]
            whole = (
                [Anchor(id=numbered(len(rulings) + 1), text=comment, item=question)]
                if comment
                else []
            )
            return [*ruled, *whole]
        case _:
            return []


def spoken(item: Item) -> list[Anchor]:
    """Return every part of `item` that's the operator's own words, each with its id, in the item's order: those on what an agent said (`anchors`), then the rest, numbered after them and after any replies copies before kept on the item (`Item.replies`), so every id they gave keeps its meaning.

    The rest is a review's messages, then its remarks, each saying whom it's
    to, those to other agents counted as its comments are; and a message's
    words on the whole, but one replying to an item, whose words are its one
    anchor. None for an item that isn't the operator's.
    """
    if item.sender != Operator():
        return []
    on = anchors(item)
    after = len(on) + len(item.replies)

    def numbered(at: int) -> PartId:
        return PartId(item=item.number, part=after + at)

    match item.reason:
        case Review(letters=letters, remarks=remarks):
            said = [*letters, *remarks]
            return on + [
                Anchor(id=numbered(at), text=each.text, to=each.to)
                for at, each in enumerate(said, start=1)
            ]
        case Message(of=None, text=text) if text.strip():
            return [*on, Anchor(id=numbered(1), text=text)]
        case _:
            return on


def cue(text: str, longest: int = 80) -> str:
    r"""Return the cue a quote is cut to where a part's id finds the rest: its first line, shortened to `longest` characters at a word's end, `…` saying where it was cut.

    A passage the operator quotes is usually a whole paragraph, one line of
    the source however long, so the first line alone saved little: the agent
    has its own words in its context, and the id names the part.

    >>> cue("Twenty kinds of line.\nFour carry what was said.")
    'Twenty kinds of line.'
    >>> cue("Twenty kinds of line, and only four of them carry what was said.", longest=30)
    'Twenty kinds of line, and…'
    """
    line = next(iter(text.splitlines()), "")
    return textwrap.shorten(line, width=longest, placeholder="…")


def located(parts: list[Part], text: str, quote: Quote) -> Part | None:
    r"""Return the part of `text`, split into `parts`, that `quote` starts in: by its offsets where they read `quote.text` there, as the dashboard showed the text; else by its first line, where one part alone holds it; none where neither finds it.

    >>> parts = blocks("One.\n\nTwo.\n", 4)
    >>> located(parts, "One.\n\nTwo.\n", Quote(text="Two.", start=6, end=10)).id
    PartId(item=4, part=2)
    >>> located(parts, "One.\n\nTwo.\n", Quote(text="a.py:7\n+L7", start=6, end=10))
    """
    if text.startswith(quote.text, quote.start) and quote.end == quote.start + len(
        quote.text
    ):
        return next((each for each in parts if each.end > quote.start), None)
    line = next(iter(quote.text.splitlines()), "")
    holding = [each for each in parts if line and line in each.text]
    match holding:
        case [found]:
            return found
        case _:
            return None


def parts_of(item: Item, text: str) -> list[Part]:
    """Return the parts of `item`'s `text`, its Markdown blocks numbered within the item (`blocks`)."""
    return blocks(text, item.number)


def addressed_to(item: Item, party: Conversation) -> bool:
    """Say whether `item` is the operator's, addressed to `party`: for it, or passed on to it from its subagent that had ended."""
    return item.sender == Operator() and party in (item.recipient, item.addressed)
