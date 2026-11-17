"""The review: what the next send would do with the draft, laid out as a fold at the top of the dashboard's document.

The core decides where each part goes (`Dashboard.taking`); the review shows it,
grouped by where each goes, then what's held back, each part a line under the
words it says and what it's on. The page opens it at the first Ctrl+Enter and
sends at the second; Space x and Space d on a part hold it back and let it go
(`README.md` in `lup/shell/`, *The draft*).
"""

from typing import TYPE_CHECKING

from lup.shell.blocks import Block, Blocks, Fold, Line, Span
from lup.types import Model

if TYPE_CHECKING:
    from lup.shell.draft import Comment, Draft


class Going(Model):
    """Where one part of the draft goes at the next send, as the review says it: whom, or why it can't go."""

    part: str
    """The part's id."""
    to: str
    """Whom it reaches, as the review's heading says it: `to port-plan`."""
    stays: str | None = None
    """Why it can't go as it stands; none where it can."""


def said(comment: Comment) -> list[Span]:
    """Return a comment as one line of the review: its first line, and the first line of what it's on."""
    words = next((line for line in comment.words.splitlines() if line.strip()), "")
    on = next((line for line in comment.on.lines if line.strip()), "")
    where = (
        f"  on “{on}”"
        if on
        else "  on the block whole"
        if not comment.on.lines
        else "  on a blank line"
    )
    return [Span(text=words, tone="strong"), Span(text=where, tone="muted")]


def reviewed(draft: Draft, going: list[Going]) -> Fold | None:
    """Return the review of `draft`, each part going where `going` says: a fold for each place parts go, in the order they were written, and one of those held back; none where the draft holds nothing.

    >>> from lup.shell.blocks import Viewing
    >>> from lup.shell.draft import Comment, Draft, Quote
    >>> quote = Quote(viewing=Viewing(view="pile"), block="1", lines=["note 1"])
    >>> draft = Draft(comments=[Comment(id="c", on=quote, words="looks good")])
    >>> review = reviewed(draft, [Going(part="c", to="to notes")])
    >>> print(Blocks.of(review).text())
    ▾ draft · 1 to send  [Ctrl+Enter sends, Space x holds one back]
      ▾ to notes: 1
        looks good  on “note 1”
    """
    if not draft.comments:
        return None
    where = {each.part: each for each in going}

    def place(comment: Comment) -> str:
        """Say where `comment` goes, as the review's heading says it."""
        found = where.get(comment.id)
        return found.to if found is not None else "to no one"

    def line(comment: Comment) -> Line:
        """Return `comment`'s line, saying why it can't go where it can't."""
        found = where.get(comment.id)
        stays = (
            []
            if found is None or found.stays is None
            else [Span(text=f"  ◂ {found.stays}", tone="muted")]
        )
        return Line(id=comment.id, spans=[*said(comment), *stays])

    sending = [each for each in draft.comments if not each.held]
    held: list[Block] = [line(each) for each in draft.comments if each.held]
    content: list[Block] = [
        Fold(
            id=f"to {to}",
            kind="sent-to",
            summary=[
                Span(
                    text=f"{to}: {sum(place(each) == to for each in sending)}",
                    tone="strong",
                )
            ],
            content=list[Block](line(each) for each in sending if place(each) == to),
        )
        for to in dict.fromkeys(place(each) for each in sending)
    ]
    if held:
        content.append(
            Fold(
                id="held",
                kind="sent-to",
                summary=[Span(text=f"held back: {len(held)}", tone="muted")],
                content=held,
            )
        )
    return Fold(
        id="draft",
        kind="draft",
        summary=[
            Span(text=f"draft · {len(sending)} to send", tone="strong"),
            Span(text="  [Ctrl+Enter sends, Space x holds one back]", tone="muted"),
        ],
        content=content,
    )


def wrapped(blocks: Blocks, review: Fold | None) -> Blocks:
    """Return the document's root answer with the review at its top, where there's one."""
    if review is None:
        return blocks
    return blocks.model_copy(update={"blocks": [review, *blocks.blocks]})
