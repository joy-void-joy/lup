"""The dashboard's socket: what the page sends the server, and what it's told.

The page says the token it was handed first (`Hello`); the server then tells it
the document's root view and the project's kinds (`Opened`), and answers each
view the page watches (`Watch`) with its blocks, or why it can't (`Answered`,
`Unanswered`), and again once what it shows changes. The page's types are generated
from these, so the two can't disagree (`README.md` here, *The server*).
"""

from typing import Annotated, Literal

from pydantic import Field

from lup.shell.blocks import Blocks, Viewing
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


type Sent = Annotated[Hello | Watch | Unwatch, Field(discriminator="kind")]
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


type Told = Annotated[Opened | Answered | Unanswered, Field(discriminator="kind")]
"""What the server tells the page."""


class Read(Model):
    """What the page reads from the core and sends it: a view's answer, the kinds a project's modules declare, and every frame the socket carries, the page's types generated from its description (`described`)."""

    blocks: Blocks
    looks: Looks
    sent: Sent
    told: Told
