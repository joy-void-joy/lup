"""The review: what the next send would do with the draft, as the page's window shows it.

The core decides where each part goes (`Dashboard.taking`); the review shows it
as a checklist, the comments grouped by where each goes, then the marks, what
each does, each part a line ticked where it goes and blank where the operator
keeps it back, saying the words it says, or what it does, and what it's on. The
page opens it in its window at the first Ctrl+Enter and sends what's ticked at
the second; Space d and Space x on a part tick it and untick it, Space t and
Space h either (`README.md` in `lup/shell/`, *The draft*).
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
    """Return the review of `draft` as a checklist, each part going where `going` says: a fold for each place comments go, in the order they were written, then one of the marks; each part a line, ticked where it goes at the next send and blank where the operator keeps it back, which stays in the draft; the summary saying how many go; nothing where the draft holds nothing.

    >>> from lup.shell.blocks import Viewing
    >>> from lup.shell.draft import Comment, Draft, Quote
    >>> quote = Quote(viewing=Viewing(view="pile"), block="1", lines=["note 1"])
    >>> draft = Draft(comments=[Comment(id="c", on=quote, words="looks good"),
    ...     Comment(id="d", on=quote, words="later", held=True)])
    >>> print(reviewed(draft, [Going(part="c", to="to notes"),
    ...     Going(part="d", to="to notes")]).text())
    draft · 1 of 2 to send
    ▾ to notes: 1 of 2
      [x] looks good  on “note 1”
      [ ] later  on “note 1”
    """
    parts = [*draft.comments, *draft.marks]
    if not parts:
        return Blocks()
    where = {each.part: each for each in going}

    def place(comment: Comment) -> str:
        """Say where `comment` goes, as the review's heading says it."""
        found = where.get(comment.id)
        return found.to if found is not None else "to no one"

    def line(part: Comment | Marked) -> Line:
        """Return `part`'s line, ticked where it goes, saying why it can't go where it can't."""
        found = where.get(part.id)
        stays = (
            []
            if part.held or found is None or found.stays is None
            else [Span(text=f"  ◂ {found.stays}", tone="muted")]
        )
        box = (
            Span(text="[ ] ", tone="muted")
            if part.held
            else Span(text="[x] ", tone="strong")
        )
        spans = said(part) if isinstance(part, Comment) else done(part)
        return Line(id=part.id, spans=[box, *spans, *stays])

    def fold(key: str, said: str, placed: list[Comment] | list[Marked]) -> Fold:
        """Return the fold of id `key` holding `placed`'s lines, said in its summary as `said` and how many of them go."""
        goes = sum(not each.held for each in placed)
        count = f"{goes}" if goes == len(placed) else f"{goes} of {len(placed)}"
        return Fold(
            id=key,
            kind="sent-to",
            summary=[Span(text=f"{said}: {count}", tone="strong")],
            content=[line(each) for each in placed],
        )

    places: list[Block] = [
        fold(f"to {to}", to, [each for each in draft.comments if place(each) == to])
        for to in dict.fromkeys(place(each) for each in draft.comments)
    ]
    marked: list[Block] = [fold("marked", "marked", draft.marks)] if draft.marks else []
    goes = sum(not each.held for each in parts)
    count = f"{goes}" if goes == len(parts) else f"{goes} of {len(parts)}"
    return Blocks(
        blocks=[*places, *marked],
        summary=[Span(text=f"draft · {count} to send", tone="strong")],
    )
