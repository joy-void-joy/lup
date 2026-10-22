"""Replying by id: the parts of the operator's items an agent answers, where a quoted passage lies in an item, and what a reply may answer.

`docs/inbox.md`, *Replying by id*. The operator's words reach an agent in
items with parts of their own (`anchors`): a review's comments, in its order;
the comment a reply to a note carries; each passage's reply in a message sent
from reading a conversation; an answer's rulings, then its comment. Each has
an id, `546.2`, which the tags carry (`<reply id="546.2">`) and the agent's
`reply` names; the agent's replies are kept on the item after them, numbered
on (`Reply.number`), so the operator's next comment can be on one.

A passage the operator quoted is found in the item it's of by the part it
starts in (`located`): by its offsets where the item's text is what the
dashboard showed, else by its first line where that's in one part alone. The
tag then carries the part's id and the quote's first line, since the agent has
its own words and the id finds the rest; a passage of a changed file's lines,
which no part holds, is quoted whole, as before.

An agent may answer a part of an item addressed to it that's the operator's
words on one of its own items, or on a passage of its conversation (`answerable`);
one on another agent's item, or one of its own replies, is refused naming what
it may answer.
"""

import textwrap

from lup.types import Model
from lup_dev.inbox.parts import Part, PartId, blocks
from lup_dev.inbox.store import (
    Answer,
    Conversation,
    InboxError,
    Item,
    Message,
    Operator,
    Quote,
    Review,
    Verdict,
    cited,
)


class Anchor(Model):
    """One part of an item of the operator's, which an agent may answer by its id: their words at one place, and what the place is."""

    id: PartId
    text: str
    """The operator's words there: a comment, a reply, a ruling's comment."""
    item: int | None = None
    """The agent's item it's on; none where it's on a passage of the agent's
    conversation, which the operator read there."""
    quote: Quote | None = None
    """The passage it's on: of the item's text, or of the reply `on`; none for
    a comment on the item whole, or a ruling."""
    on: PartId | None = None
    """The agent's reply it answers, where it continues a thread."""
    decision: int | None = None
    """The decision it rules on, from 1, for an answer's ruling."""
    verdict: Verdict | None = None
    """Its verdict, for a ruling with one."""


class Replying(Model):
    """One reply an agent makes with `reply`: the part it answers, and its words."""

    to: PartId
    text: str


def anchors(item: Item) -> list[Anchor]:
    """Return the parts of `item` an agent may answer, in the item's order, numbered from 1: none for an item that isn't the operator's words on the agent's.

    A review's are its comments, in its order, those on other agents' items
    counted so the numbers hold for every agent it reaches; a reply's its one
    comment; a message's from reading a conversation each passage's reply,
    its words on the whole, which no tag names, left out; an answer's each
    ruling, then its comment.
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


def answerable(item: Item, to: PartId, sent: list[int]) -> Anchor:
    """Return the part `to` of `item` that the agent may answer with `reply`: the operator's words on one of its own items, `sent`, or on a passage of its conversation.

    Raise `InboxError` naming what it may answer where `to` names a part on
    another agent's item, one of the agent's own replies, or no part.
    """
    found = anchors(item)
    offered = [each for each in found if each.item is None or each.item in sent]
    listed = ", ".join(each.id.said() for each in offered) or "none"
    anchor = next((each for each in found if each.id == to), None)
    if anchor is not None and anchor in offered:
        return anchor
    if anchor is not None and isinstance(anchor.item, int):
        message = (
            f"{to.cited()} is the operator's comment on {cited(anchor.item)}, another "
            f"agent's item, not yours to answer; {cited(item.number)}'s parts you "
            f"may answer: {listed}"
        )
        raise InboxError(message)
    own = next((each for each in item.replies if each.number == to.part), None)
    if own is not None:
        message = (
            f"{to.cited()} is your own reply to {own.to.cited()}; "
            f"{cited(item.number)}'s parts you may answer: {listed}"
        )
        raise InboxError(message)
    message = (
        f"{to.cited()} names no part of {cited(item.number)}; its parts you may "
        f"answer: {listed}"
    )
    raise InboxError(message)
