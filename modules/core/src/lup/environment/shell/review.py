"""The review: what the next send would do with the draft, as the page's window shows it.

The core decides where each part goes (`Dashboard.taking`); the review shows it,
the comments grouped by where each goes, then the marks, what each does, then
what's held back, each part a line saying the words it says, or what it does,
and what it's on. The page opens it in its window at the first Ctrl+Enter and
sends at the second; Space x and Space d on a part keep it back and let it go
(`README.md` in `lup/shell/`, *The draft*).
"""

from typing import TYPE_CHECKING

from lup.shell.blocks import Block, Blocks, Fold, Line, Span
from lup.shell.draft import Comment
from lup.types import Model

if TYPE_CHECKING:
    from lup.shell.draft import Draft, Marked


class Going(Model):
    """Where one part of the draft goes at the next send, as the review says it: whom, or why it can't go."""

    part: str
    """The part's id."""
    to: str
    """Whom it reaches, as the review's heading says it: `to port-plan`; for a
    mark, what it does: `clear it`."""
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


def done(mark: Marked) -> list[Span]:
    """Return a mark as one line of the review: what it does, and the first line of what it's on."""
    on = next((line for line in mark.on.lines if line.strip()), "")
    where = f"  on “{on}”" if on else "  on a block"
    return [Span(text=mark.offer.says, tone="strong"), Span(text=where, tone="muted")]


def reviewed(draft: Draft, going: list[Going]) -> Blocks:
    """Return the review of `draft`, each part going where `going` says: a fold for each place comments go, in the order they were written, then one of the marks, then one of the parts held back, said in its summary as how many go; nothing where the draft holds nothing.

    >>> from lup.shell.blocks import Viewing
    >>> from lup.shell.draft import Comment, Draft, Quote
    >>> quote = Quote(viewing=Viewing(view="pile"), block="1", lines=["note 1"])
    >>> draft = Draft(comments=[Comment(id="c", on=quote, words="looks good")])
    >>> print(reviewed(draft, [Going(part="c", to="to notes")]).text())
    draft · 1 to send
    ▾ to notes: 1
      looks good  on “note 1”
    """
    if not draft.comments and not draft.marks:
        return Blocks()
    where = {each.part: each for each in going}

    def place(comment: Comment) -> str:
        """Say where `comment` goes, as the review's heading says it."""
        found = where.get(comment.id)
        return found.to if found is not None else "to no one"

    def line(part: Comment | Marked) -> Line:
        """Return `part`'s line, saying why it can't go where it can't."""
        found = where.get(part.id)
        stays = (
            []
            if found is None or found.stays is None
            else [Span(text=f"  ◂ {found.stays}", tone="muted")]
        )
        spans = said(part) if isinstance(part, Comment) else done(part)
        return Line(id=part.id, spans=[*spans, *stays])

    sending = [each for each in draft.comments if not each.held]
    marking = [each for each in draft.marks if not each.held]
    held: list[Block] = [
        line(each).model_copy(update={"standing": "held"})
        for each in [*draft.comments, *draft.marks]
        if each.held
    ]
    places: list[Block] = [
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
    marked: list[Block] = (
        [
            Fold(
                id="marked",
                kind="sent-to",
                summary=[Span(text=f"marked: {len(marking)}", tone="strong")],
                content=[line(each) for each in marking],
            )
        ]
        if marking
        else []
    )
    kept: list[Block] = (
        [
            Fold(
                id="held",
                kind="sent-to",
                summary=[Span(text=f"held back: {len(held)}", tone="muted")],
                content=held,
            )
        ]
        if held
        else []
    )
    return Blocks(
        blocks=[*places, *marked, *kept],
        summary=[
            Span(text=f"draft · {len(sending) + len(marking)} to send", tone="strong")
        ],
    )
