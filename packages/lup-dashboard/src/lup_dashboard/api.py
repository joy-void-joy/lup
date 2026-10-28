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
    Holding,
    Listed,
    ListLaunches,
    Refused,
    Rename,
    Renamed,
    SetHolding,
)
from lup_dev.host.workers import Viewed, Viewing
from lup_dev.inbox.protocol import (
    AnswerApproval,
    AnswerItem,
    Context,
    Conversed,
    Drafted,
    Files,
    FinishItem,
    Items,
    KeepDraft,
    KeepOrder,
    KeepTalk,
    ListInbox,
    Ordered,
    Reviewed,
    SendDraft,
    SendItem,
    Settled,
    ShowContext,
    ShowConversation,
    ShowDraft,
    ShowFiles,
    ShowItem,
    Shown,
    ShowOrder,
    ShowTalk,
    Talked,
)
from lup_dev.policy.since import ReviewSince, ShowSince, Since, SinceReviewed

type Asked = Annotated[
    ListLaunches
    | Rename
    | SetHolding
    | ListInbox
    | ShowItem
    | AnswerItem
    | FinishItem
    | SendItem
    | AnswerApproval
    | ShowFiles
    | ShowContext
    | ShowConversation
    | ShowDraft
    | KeepDraft
    | SendDraft
    | ShowOrder
    | KeepOrder
    | ShowTalk
    | KeepTalk
    | ShowSince
    | ReviewSince
    | Viewing,
    Field(discriminator="kind"),
]
"""A request the page may send: the launches served and their conversations,
a launch renamed, the operator's switch for a conversation turned, "hold each
flagged write", and the operator's inbox, its items read, answered, finished
and sent, an approval or a held change answered and the files it changes read,
an item's moment in its sender's conversation read, a conversation's record read
from where the page left it for its task list and its context, the operator's
draft reply shown, kept and sent, where their review lays out
its groups shown and kept, what they write on a conversation shown and kept, what an agent's branch changed since they
last saw it read and its files marked reviewed, and a module's view, which the
page draws from its blocks (`docs/host.md`, *The views the dashboard shows*)."""

type Replied = Annotated[
    Listed
    | Renamed
    | Holding
    | Items
    | Shown
    | Settled
    | Files
    | Context
    | Conversed
    | Drafted
    | Ordered
    | Talked
    | Reviewed
    | Since
    | SinceReviewed
    | Viewed
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
