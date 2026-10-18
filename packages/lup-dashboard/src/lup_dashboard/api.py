"""The dashboard's API: the host service's own control requests, relayed, and their replies.

`docs/dashboard.md`, *The API*. The page asks the host service through the
dashboard exactly what the operator's commands ask it: each request here is one
of the host's control requests, sent on as it is, its reply returned as it is,
a refusal among them. A watched request is answered again each time its reply
changes (`lup_dev/host/watch.py`).
"""

from typing import Annotated

from pydantic import Field

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
    FinishItem,
    Items,
    ListInbox,
    SendItem,
    Settled,
    ShowDiff,
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
    | ShowDiff,
    Field(discriminator="kind"),
]
"""A request the page may send: the launches served and their conversations,
a launch renamed, and the operator's inbox, its items read, answered, finished
and sent, an approval answered and its diff read."""

type Replied = Annotated[
    Listed | Renamed | Items | Shown | Settled | Whole | Refused,
    Field(discriminator="kind"),
]
"""The host's reply to one: what each request returns, or why it was refused."""
