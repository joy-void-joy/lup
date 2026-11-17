"""The dashboard's socket: what the page sends the server, and what it's told.

The page says the token it was handed first (`Hello`); the server then tells it
the document's root view and the project's kinds (`Opened`) and the draft as it
stands (`Drafted`), and answers each view the page watches (`Watch`) with its
blocks, or why it can't (`Answered`, `Unanswered`), and again once what it shows
changes. The page writes each comment and mark into the draft as it changes
(`Write`, `Mark`, `Erase`), and sends it (`Send`), told what went and what
stayed (`Delivered`), every page told the draft as it changes. The page's types are generated
from these, so the two can't disagree (`README.md` here, *The server*).
"""

from typing import Annotated, Literal

from pydantic import Field

from lup.shell.blocks import Blocks, Viewing
from lup.shell.draft import Comment, Draft, Marked
from lup.shell.looks import Looks
from lup.types import Model


class Hello(Model):
    """The page's first frame: the token it was handed."""

    kind: Literal["hello"] = "hello"
    token: str


class Watch(Model):
    """Read a view, and again each time what it shows changes, under a number the page picks."""

    kind: Literal["watch"] = "watch"
    watch: int
    viewing: Viewing


class Unwatch(Model):
    """Stop reading the view watched under a number."""

    kind: Literal["unwatch"] = "unwatch"
    watch: int


class Write(Model):
    """Put a comment in the draft, in place of the one of its id where there's one: each edit of it, as it's made."""

    kind: Literal["write"] = "write"
    comment: Comment


class Mark(Model):
    """Put a verb marked on a block in the draft, in place of the mark of its id where there's one."""

    kind: Literal["mark"] = "mark"
    marked: Marked


class Erase(Model):
    """Take the comment or mark of an id out of the draft."""

    kind: Literal["erase"] = "erase"
    id: str


class Send(Model):
    """Send the draft: each comment and mark on its own."""

    kind: Literal["send"] = "send"


type Sent = Annotated[
    Hello | Watch | Unwatch | Write | Mark | Erase | Send, Field(discriminator="kind")
]
"""What the page sends the server."""


class Opened(Model):
    """What the page is told once its token is read: the document's root view, and the kinds a project's modules declare."""

    kind: Literal["opened"] = "opened"
    root: Viewing | None
    looks: Looks


class Answered(Model):
    """What a view watched answers."""

    kind: Literal["answered"] = "answered"
    watch: int
    blocks: Blocks


class Unanswered(Model):
    """Why a frame the page sent isn't answered: a view it can't read, or a frame the server can't."""

    kind: Literal["unanswered"] = "unanswered"
    watch: int | None
    """The watch it's about, where it's about one."""
    reason: str


class Drafted(Model):
    """The draft as it stands, told every page at its opening and whenever it changes, so each shows the same."""

    kind: Literal["drafted"] = "drafted"
    draft: Draft


class Delivered(Model):
    """What came of a send: the parts that went, which leave the draft, and those that stayed in it, each saying why in the draft."""

    kind: Literal["delivered"] = "delivered"
    went: list[str]
    """The ids of the comments and marks that went."""
    stayed: list[str]
    """The ids of those that stayed in the draft."""


type Told = Annotated[
    Opened | Answered | Unanswered | Drafted | Delivered, Field(discriminator="kind")
]
"""What the server tells the page."""


class Read(Model):
    """What the page reads from the core and sends it: a view's answer, the kinds a project's modules declare, and every frame the socket carries, the page's types generated from its description (`described`)."""

    blocks: Blocks
    looks: Looks
    sent: Sent
    told: Told
