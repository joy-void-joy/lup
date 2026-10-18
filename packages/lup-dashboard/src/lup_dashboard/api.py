"""The dashboard's API: the host service's own control requests, relayed, and their replies.

`docs/dashboard.md`, *The API*. The page asks the host service through the
dashboard exactly what the operator's commands ask it: each request here is one
of the host's control requests, sent on as it is, its reply returned as it is,
a refusal among them. A watched request is answered again each time its reply
changes (`lup_dev/host/watch.py`): the page's watches are carried on one socket,
each numbered by the page (`Watch`, `Unwatch`; `Watched`, `Ended`).
"""

from typing import Annotated, Literal

from pydantic import Field

from lup.types import Model
from lup_dev.host.protocol import (
    Listed,
    ListLaunches,
    Refused,
    Rename,
    Renamed,
)
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AnswerItem,
    Context,
    Conversed,
    Drafted,
    FinishItem,
    Items,
    KeepDraft,
    ListInbox,
    Reviewed,
    SendDraft,
    SendItem,
    Settled,
    ShowContext,
    ShowConversation,
    ShowDiff,
    ShowDraft,
    ShowItem,
    Shown,
    Whole,
)

type Asked = Annotated[
    ListLaunches
    | Rename
    | ListInbox
    | ShowItem
    | AnswerItem
    | FinishItem
    | SendItem
    | AnswerApproval
    | ShowDiff
    | ShowContext
    | ShowConversation
    | ShowDraft
    | KeepDraft
    | SendDraft,
    Field(discriminator="kind"),
]
"""A request the page may send: the launches served and their conversations,
a launch renamed, and the operator's inbox, its items read, answered, finished
and sent, an approval answered and its diff read, an item's moment in its
sender's conversation read, a whole conversation read from where the page left
it, and the operator's draft reply shown, kept and sent."""

type Replied = Annotated[
    Listed
    | Renamed
    | Items
    | Shown
    | Settled
    | Whole
    | Context
    | Conversed
    | Drafted
    | Reviewed
    | Refused,
    Field(discriminator="kind"),
]
"""The host's reply to one: what each request returns, or why it was refused."""


class Watch(Model):
    """The page's frame on its socket starting a watch: the number it gives it, and the request watched."""

    kind: Literal["watch"] = "watch"
    number: int
    request: Asked


class Unwatch(Model):
    """The page's frame on its socket stopping the watch it numbered `number`."""

    kind: Literal["unwatch"] = "unwatch"
    number: int


type Framed = Annotated[Watch | Unwatch, Field(discriminator="kind")]
"""What the page sends on its socket."""


class Watched(Model):
    """The server's frame on the page's socket: a reply to the watch numbered `number`, at once, then each time it changes."""

    kind: Literal["watched"] = "watched"
    number: int
    reply: Replied


class Ended(Model):
    """The server's frame on the page's socket: the watch numbered `number` ended, the host service out of reach or closing it, and why; the page watches it again later."""

    kind: Literal["ended"] = "ended"
    number: int
    why: str
