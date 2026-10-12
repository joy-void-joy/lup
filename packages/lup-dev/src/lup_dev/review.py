"""What reviews share: the operator's answers, and the seam to wherever reviews wait.

A change the operator reviews is parked where they read it: in the bridge, the
first lup's dashboard (`lup_dev.legacy_dashboard`); once it exists, lup's own.
Whatever parks it answers to `Queue`, so what submits a review never knows where
it waits (`docs/review-flow.md`, *Modules and public API*). What the operator
writes back comes in the models here, which the installer's review reads too.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator

from lup.types import Model
from lup_dev.errors import LupDevError


class ReviewError(LupDevError):
    """A review can't be parked, read or settled where reviews are parked."""


class LineComment(Model):
    """One comment the operator anchored to lines of a file a review showed."""

    path: Path
    """The file's path in the checkout."""
    first: int
    last: int
    side: Literal["before", "after"]
    """Which text the lines number: `before`, the file before the change; `after`,
    the file as the change leaves it."""
    note: str

    def text(self, since: str | None) -> str:
        """Say where the comment points, then what it says, naming the commit before."""
        lines = (
            str(self.first) if self.first == self.last else f"{self.first}-{self.last}"
        )
        side = f"before, at {since}" if self.side == "before" and since else self.side
        body = "\n    ".join(self.note.splitlines())
        return f"{self.path}:{lines} ({side}): {body}"


class Remark(Model):
    """What the operator wrote on a review without deciding it."""

    note: str = ""
    comments: list[LineComment] = []

    def said(self, since: str | None) -> list[str]:
        """Return the note and the line comments as the terminal prints them."""
        note = (
            [
                "Your note:",
                *(f"    {line}" if line else "" for line in self.note.splitlines()),
            ]
            if self.note
            else []
        )
        comments = (
            [
                "Your line comments:",
                *(f"  {comment.text(since)}" for comment in self.comments),
            ]
            if self.comments
            else []
        )
        return [*note, *comments]


class Answer(Remark):
    """The operator's decision on a review, with what they wrote on it."""

    approved: bool


class ReviewedFile(Model):
    """One file of a review: both its sides, and what the agent and the judge say of it.

    A file the judge asks about lists why; one nothing asks about is there because
    the agent asked for the operator's view anyway; one already landed is shown as
    context, with nothing to apply.
    """

    path: Path
    """Its path in the worktree."""
    before: str | None
    """Its text before the change; none where the change creates it."""
    after: str | None
    """Its text after the change; none where the change deletes it."""
    context: str
    """What changes in it and why, in the agent's words."""
    asks: list[str] = []
    """Why the judge asks the operator about it, one reason each."""
    landed: bool = False
    """Whether it's landed already, so the review shows it only as context."""

    @model_validator(mode="after")
    def shown(self) -> Self:
        """Refuse a file with no text on either side, or a landed one that asks."""
        if self.before is None and self.after is None:
            message = f"{self.path} has no text on either side of the change"
            raise ValueError(message)
        if self.landed and self.asks:
            message = f"{self.path} is landed already, so nothing can ask about it"
            raise ValueError(message)
        return self

    def kind(self) -> Literal["created", "overwritten", "deleted"]:
        """Say whether the change creates the file, overwrites it or deletes it.

        >>> ReviewedFile(path=Path("a.py"), before=None, after="", context="").kind()
        'created'
        """
        if self.before is None:
            return "created"
        if self.after is None:
            return "deleted"
        return "overwritten"


class ReviewRequest(Model):
    """A change put before the operator as one review, wherever it's parked."""

    number: int
    """The review's number in its worktree, by which the queue knows it."""
    requester: str
    """Who asks: the session that submitted it, named as asking and on its replies."""
    agent: str = ""
    """The subagent that submitted it, blank for the session's own conversation."""
    heading: str
    """What the review is about, in the agent's words; it heads the review."""
    files: list[ReviewedFile]


class Waiting(Model):
    """The review waits for the operator's answer."""


class Answered(Model):
    """The operator answered the review."""

    answer: Answer


class Gone(Model):
    """The review left the queue unanswered, and no answer will come to it."""

    why: str
    """Why it left, as the place it was parked says."""


class Look(Model):
    """A parked review as it stands, read without changing anything."""

    state: Waiting | Answered | Gone
    remarks: list[Remark] = []
    """What the operator sent on it without deciding, oldest first."""


# lup: ignore("interface-shape", why="the review flow's seam (docs/review-flow.md, Modules and public API): the six things any place reviews wait must do, which one implementation answers whole")
class Queue(ABC):
    """Where reviews are parked for the operator, and what the asking side does to them.

    A review is named by its number in its worktree, whatever the place it's parked
    calls it there. Telling the operator is the queue's: once when a review is
    first parked, and once when an agent first freezes on it.
    """

    @abstractmethod
    def park(self, review: ReviewRequest) -> None:
        """Put `review` before the operator, telling them once."""

    @abstractmethod
    def look(self, number: int) -> Look:
        """Return how review `number` stands, with what the operator sent on it."""

    @abstractmethod
    def spend(self, number: int) -> None:
        """Record review `number`'s approval as carried out, and let the review go."""

    @abstractmethod
    def withdraw(self, number: int, why: str) -> None:
        """Take review `number` out of the queue, saying `why`: nothing releases it."""

    @abstractmethod
    def reply(self, number: int, text: str) -> None:
        """Say `text` in review `number`'s thread, as whoever asked; it settles nothing."""

    @abstractmethod
    def frozen(self, number: int) -> None:
        """Mark review `number` as one an agent is frozen on, telling the operator once."""
