"""The operator's draft: the comments they've written into the document and the verbs they've marked on its blocks, until they send it.

There's one draft, kept by the dashboard's server rather than by a page, each
comment and mark written to it as it changes, so two open pages share it and a
closed tab loses nothing. Sending it (Ctrl+Enter) sends each part on its own: a
comment to what its block offers for comments, a mark to the action it marks;
each part that goes leaves the draft, and each that can't stays in it with why,
so one never stops the rest (`DESIGN.md`, *The dashboard*: "Sending always
works"; `README.md` here, *The draft*).
"""

from pydantic import BaseModel

from lup.shell.blocks import Offer, Viewing
from lup.types import Model


class Quote(Model):
    """What a part of the draft is on: a block of a view, the block's version as the part was written, and the lines of it quoted, whole, with where the passage starts and ends in them."""

    viewing: Viewing
    """The view whose block it's on, its module named."""
    block: str
    """The block's id."""
    version: str | None = None
    """The block's version as the part was written: a part on a block whose
    version has changed since is on something the operator didn't see."""
    lines: list[str] = []
    """The lines of the block it quotes, whole, as they read when it was written."""
    start: int = 0
    """Where the passage it's on starts in its lines, joined by newlines."""
    end: int | None = None
    """Where the passage ends; none for the lines whole."""


class Comment(Model):
    """A comment the operator wrote into the document, under what it's on."""

    id: str
    """The page's id for it, kept as it's edited."""
    on: Quote
    words: str
    reason: str | None = None
    """Why it stayed in the draft at the last send; none where it hasn't been
    sent, or nothing kept it."""


class Marked(Model):
    """A verb the operator marked on a block, waiting for the send: the action the block offers under that verb, and the block."""

    id: str
    """The page's id for the mark."""
    on: Quote
    offer: Offer
    reason: str | None = None
    """Why it stayed in the draft at the last send; none where it hasn't been
    sent, or nothing kept it."""


class Draft(Model):
    """The operator's draft: every comment and mark not sent yet, in the order they were made."""

    comments: list[Comment] = []
    marks: list[Marked] = []

    def written(self, comment: Comment) -> Draft:
        """Return the draft with `comment` in it, in place of the one of its id, where there's one."""
        if any(each.id == comment.id for each in self.comments):
            comments = [
                comment if each.id == comment.id else each for each in self.comments
            ]
        else:
            comments = [*self.comments, comment]
        return self.model_copy(update={"comments": comments})

    def marked(self, mark: Marked) -> Draft:
        """Return the draft with `mark` in it, in place of the one of its id, where there's one."""
        if any(each.id == mark.id for each in self.marks):
            marks = [mark if each.id == mark.id else each for each in self.marks]
        else:
            marks = [*self.marks, mark]
        return self.model_copy(update={"marks": marks})

    def erased(self, part: str) -> Draft:
        """Return the draft without the comment or mark whose id is `part`."""
        return Draft(
            comments=[each for each in self.comments if each.id != part],
            marks=[each for each in self.marks if each.id != part],
        )


class Commenting(Model):
    """The comment an action offered under the `comment` verb is given, beside what its offer gave (`Commented`)."""

    words: str
    lines: list[str] = []
    """The block's lines the comment quotes, whole, as they read when it was written."""
    start: int = 0
    """Where the passage it's on starts in its lines, joined by newlines."""
    end: int | None = None
    """Where the passage ends; none for the lines whole."""
    version: str | None = None
    """The block's version as the comment was written."""


class Commented[G: BaseModel](Commenting):
    """What an action a block offers under the `comment` verb is given: what the offer gave it, and the comment written on the block.

    A module's comment action takes `Commented[G]`, its block offering it with a
    `G`: `Offer.of(InboxPart.comment, OnItem(item=12))`.
    """

    on: G
    """What the block's offer gave."""
