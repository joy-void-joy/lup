"""The operator's draft: the comments they've written into the document and the verbs they've marked on its blocks, until they send it.

There's one draft, kept by the dashboard's server rather than by a page, each
comment and mark written to it as it changes, so two open pages share it and a
closed tab loses nothing. Sending it (Ctrl+Enter) sends each part on its own: a
comment to what its block offers for comments, a mark to the action it marks;
each part that goes leaves the draft, and each that can't stays in it with why,
so one never stops the rest (`DESIGN.md`, *The dashboard*: "Sending always
works"; `README.md` here, *The draft*).
"""

lazy from collections.abc import Iterator, Mapping

from pydantic import BaseModel, JsonValue

from lup.shell.blocks import Offer, Viewing
from lup.types import Model


class Within(Model):
    """A fold the view of a quoted block was read under: the view whose block the fold is, and the fold's id."""

    viewing: Viewing
    block: str


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
    """The lines of the block it quotes, whole, as they read when it was
    written; none for the block whole."""
    line: int = 0
    """Where the lines it quotes start among the block's own, from 0, so the
    page puts it back under the right one of two lines that read the same."""
    start: int = 0
    """Where the passage it's on starts in its lines, joined by newlines."""
    end: int | None = None
    """Where the passage ends; none for the lines whole."""
    within: list[Within] = []
    """The folds the view of the block it's on was read under, innermost
    first, as the page laid them out: where the block and those holding it in
    its view name no party, the first of these that does, or that a block
    holding it does, is whom a comment on it reaches."""


class Comment(Model):
    """A comment the operator wrote into the document, under what it's on."""

    id: str
    """The page's id for it, kept as it's edited."""
    on: Quote
    words: str
    to: dict[str, JsonValue] | None = None
    """Whom it reaches, as the operator chose (Space s), as the block naming
    that party says it (`Shown.reaches`): kept as it came, since the page sends
    it back, and any module may declare a party; none for whom what it's on
    reaches."""
    reason: str | None = None
    """Why it stayed in the draft at the last send; none where it hasn't been
    sent, or nothing kept it."""
    warned: bool = False
    """Whether a send kept it back once for being on lines that changed since
    it was written: the next send sends it as it is. Writing it again starts
    over."""
    held: bool = False
    """Whether the operator holds it back from sends (Space x): it stays in the
    draft, as it is, until they let it go (Space d)."""


class Outcome(Model):
    """What came of sending one part of the draft: why it stayed, where it did, and whether it stayed for being outdated, which the next send overrides."""

    reason: str | None = None
    """Why it stayed in the draft; none where it went."""
    outdated: bool = False
    """Whether it stayed for being on something that changed since it was
    written."""


class Marked(Model):
    """A verb the operator marked on a block, waiting for the send: the action the block offers under that verb, and the block."""

    id: str
    """The page's id for the mark."""
    on: Quote
    offer: Offer
    reason: str | None = None
    """Why it stayed in the draft at the last send; none where it hasn't been
    sent, or nothing kept it."""
    held: bool = False
    """Whether the operator holds it back from sends (Space x): it stays in the
    draft, as it is, until they let it go (Space d)."""


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

    def settled(self, sent: Draft, outcomes: Mapping[str, Outcome]) -> Draft:
        """Return this draft once `sent` was sent, each part's outcome by its id: one that went taken out, one that stayed given why, a comment kept back for being outdated marked warned, where it's as it was sent; a part written again or erased while it was sent left as it is."""

        def kept[P: (Comment, Marked)](parts: list[P], was: list[P]) -> Iterator[P]:
            """Yield the parts of `parts`, those of `was` settled."""
            for each in parts:
                before = next((part for part in was if part.id == each.id), None)
                if before is None or before != each or each.id not in outcomes:
                    yield each
                    continue
                outcome = outcomes[each.id]
                if outcome.reason is not None:
                    warned = {"warned": True} if outcome.outdated else {}
                    yield each.model_copy(update={"reason": outcome.reason, **warned})

        return Draft(
            comments=list(kept(self.comments, sent.comments)),
            marks=list(kept(self.marks, sent.marks)),
        )

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
