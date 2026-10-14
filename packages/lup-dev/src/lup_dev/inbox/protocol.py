"""The operator's requests to lup's inbox, on the host service's control socket, and their handlers.

`docs/host-tools.md`, *The operator's face*. `lup-dev inbox` and its commands
send these, each a typed request on the control socket, starting the service
where none runs, as a launch does: what waits for the operator (`ListInbox`), one
item whole (`ShowItem`), a question's answer (`AnswerItem`), a message read
(`FinishItem`), and a message to the session a launch runs (`SendItem`). They're
the inbox's own kinds, registered with the service by `cli.py`; a room can't
send them, since it can't reach the control socket, and the store isn't
mounted.
"""

from typing import Literal, override

from lup.types import Model
from lup_dev.host.protocol import LaunchId, Reply, Request
from lup_dev.host.service import Handler, Route
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import Item, Operator, Ruling


class ListInbox(Request):
    """List what waits in the operator's inbox, oldest first."""

    kind: Literal["inbox-list"] = "inbox-list"


class ShowItem(Request):
    """Show one item whole."""

    kind: Literal["inbox-show"] = "inbox-show"
    number: int


class AnswerItem(Request):
    """Answer a question: a verdict on each of its decisions, and a comment on the whole, or a plain question's answer in words."""

    kind: Literal["inbox-answer"] = "inbox-answer"
    number: int
    rulings: list[Ruling] = []
    comment: str = ""


class FinishItem(Request):
    """Take a message the operator has read off their list."""

    kind: Literal["inbox-done"] = "inbox-done"
    number: int


class SendItem(Request):
    """Send the operator's message to the main conversation of the session a launch runs."""

    kind: Literal["inbox-send"] = "inbox-send"
    launch: LaunchId
    text: str


class Items(Reply):
    """Items, oldest first."""

    kind: Literal["inbox-items"] = "inbox-items"
    items: list[Item]


class Shown(Reply):
    """One item, whole."""

    kind: Literal["inbox-item"] = "inbox-item"
    item: Item


class Listing(Model, Handler[ListInbox], arbitrary_types_allowed=True):
    """Answers `ListInbox`: the items waiting for the operator."""

    delivery: Delivery

    @override
    def request(self) -> type[ListInbox]:
        return ListInbox

    @override
    async def answer(self, request: ListInbox) -> Reply:
        return Items(items=self.delivery.inbox.waiting(Operator()))


class Showing(Model, Handler[ShowItem], arbitrary_types_allowed=True):
    """Answers `ShowItem`: the item, whole."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowItem]:
        return ShowItem

    @override
    async def answer(self, request: ShowItem) -> Reply:
        return Shown(item=self.delivery.inbox.item(request.number))


class Answering(Model, Handler[AnswerItem], arbitrary_types_allowed=True):
    """Answers `AnswerItem`: the question answered, its answer told to the conversation that asked."""

    delivery: Delivery

    @override
    def request(self) -> type[AnswerItem]:
        return AnswerItem

    @override
    async def answer(self, request: AnswerItem) -> Reply:
        answer = await self.delivery.answer(
            request.number, request.rulings, request.comment
        )
        return Shown(item=answer)


class Finishing(Model, Handler[FinishItem], arbitrary_types_allowed=True):
    """Answers `FinishItem`: the message off the operator's list."""

    delivery: Delivery

    @override
    def request(self) -> type[FinishItem]:
        return FinishItem

    @override
    async def answer(self, request: FinishItem) -> Reply:
        return Shown(item=self.delivery.done(request.number))


class Sending(Model, Handler[SendItem], arbitrary_types_allowed=True):
    """Answers `SendItem`: the message in the inbox of the session the launch runs."""

    delivery: Delivery

    @override
    def request(self) -> type[SendItem]:
        return SendItem

    @override
    async def answer(self, request: SendItem) -> Reply:
        return Shown(item=await self.delivery.sent(request.launch, request.text))


def routes(delivery: Delivery) -> list[Route]:
    """Route each of the inbox's kinds to its handler, over one delivery."""
    return [
        Route.to(Listing(delivery=delivery)),
        Route.to(Showing(delivery=delivery)),
        Route.to(Answering(delivery=delivery)),
        Route.to(Finishing(delivery=delivery)),
        Route.to(Sending(delivery=delivery)),
    ]
