"""What an item is, and what it says: its kind in a few words and as a tag names it, its first line, and its text whole.

Read wherever lup says an item: the tags a conversation is told (`inbox/delivery.py`),
the inbox read a line an item (`inbox/reading.py`), the threads an item lands in
(`inbox/concerns.py`).
"""

from typing import Literal

from lup_dev.inbox.citations import plainly
from lup_dev.inbox.store import (
    Answer,
    Approval,
    Ended,
    Flagged,
    Friction,
    HeldChange,
    HowItFelt,
    Item,
    Message,
    Question,
    Review,
    Stop,
    Unresolved,
)


def what(item: Item) -> str:
    """Say what an item is, in a few words."""
    match item.reason:
        case Message(ending=True):
            return "the end of a turn"
        case Message(kind="question"):
            return "a question, as a message"
        case Message(kind=kind):
            return f"a {kind}"
        case Friction():
            return "a friction"
        case HowItFelt():
            return "how it felt"
        case Stop():
            return "a stop by choice"
        case Ended(stopped=True):
            return "a subagent stopped"
        case Ended():
            return "the end of a subagent's turn"
        case Unresolved():
            return "lup's word on citations that didn't resolve"
        case Question():
            return "a question"
        case Answer():
            return "an answer"
        case Approval():
            return "an approval"
        case HeldChange():
            return "a held change"
        case Flagged():
            return "a flagged write"
        case Review():
            return "a review"


def opening(item: Item) -> str:
    """Return an item's first line: its text's, a message with no words of its own its first reply's, an answer's comment's, or a review's first message's or comment's."""
    match item.reason:
        case Message(text="", passages=[first, *_]):
            said = first.text
        case (
            Message(text=text)
            | Friction(text=text)
            | HowItFelt(text=text)
            | Stop(text=text)
            | Ended(text=text)
            | Question(text=text)
            | Approval(text=text)
            | HeldChange(text=text)
            | Flagged(text=text)
        ):
            said = text
        case Unresolved(of=of, citations=citations):
            said = plainly(citations, of)
        case Answer(comment=comment):
            said = comment
        case Review(letters=letters, comments=comments):
            said = next((each.text for each in [*letters, *comments]), "")
    return next(iter(said.splitlines()), "")


def body(item: Item) -> str:
    """Return an item's text whole, as its sender wrote it: a question's with each decision numbered, its lean on the line under it, as the dashboard lays it out (`page/src/review.ts`), so a passage quoted there is found here by its offsets (`located`); a review's messages, then its comments."""
    match item.reason:
        case Question(text=text, decisions=decisions):
            numbered = [
                f"{at}. {each.text}\n   lean: {each.lean}"
                for at, each in enumerate(decisions, start=1)
            ]
            return "\n".join([text, *numbered])
        case (
            Message(text=text)
            | Friction(text=text)
            | HowItFelt(text=text)
            | Stop(text=text)
            | Ended(text=text)
            | Approval(text=text)
            | HeldChange(text=text)
            | Flagged(text=text)
        ):
            return text
        case Unresolved(of=of, citations=citations):
            return plainly(citations, of)
        case Answer(comment=comment):
            return comment
        case Review(letters=letters, comments=comments):
            return "\n".join(each.text for each in [*letters, *comments])


def written(item: Item) -> str:
    """Return the text of an item a conversation sent, whole: as they wrote it, a question with its decisions and leans; a change held from them, with what's held and why, or one that landed flagged, with what's flagged."""
    match item.reason:
        case (
            HeldChange(text=text, summary=summary) | Flagged(text=text, summary=summary)
        ):
            return f"{text}\n{summary}"
        case _:
            return body(item)


type ItemKind = Literal[
    "turn's end",
    "note",
    "problem",
    "disagreement",
    "question as a message",
    "friction",
    "how it felt",
    "stop",
    "ended",
    "unresolved",
    "question",
    "answer",
    "approval",
    "held change",
    "flagged write",
    "review",
]
"""An item's kind as a tag's `kind` names it (`kind`), and as `inbox` narrows
to: a message by its own kind, a turn's last words told apart from a note,
else what the item is."""


def kind(item: Item) -> ItemKind:
    """Name an item's kind as a tag's `kind` says it: a message's own kind, else what the item is.

    >>> from datetime import UTC, datetime
    >>> from lup_ledger.parties import Operator
    >>> item = Item(number=7, reason=Message(kind="problem", text="It hangs."),
    ...     sender=Operator(), recipient=Operator(), made=datetime(2026, 1, 1, tzinfo=UTC))
    >>> kind(item)
    'problem'
    """
    match item.reason:
        case Message(ending=True):
            return "turn's end"
        case Message(kind="question"):
            return "question as a message"
        case Message(kind=said):
            return said
        case Friction():
            return "friction"
        case HowItFelt():
            return "how it felt"
        case Stop():
            return "stop"
        case Ended():
            return "ended"
        case Unresolved():
            return "unresolved"
        case Question():
            return "question"
        case Answer():
            return "answer"
        case Approval():
            return "approval"
        case HeldChange():
            return "held change"
        case Flagged():
            return "flagged write"
        case Review():
            return "review"
