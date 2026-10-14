"""The operator's requests to lup's inbox, on the host service's control socket, and their handlers.

`docs/host-tools.md`, *The operator's face*. `lup-dev inbox` and its commands
send these, each a typed request on the control socket, starting the service
where none runs, as a launch does: what waits for the operator (`ListInbox`), one
item whole (`ShowItem`), a question's answer (`AnswerItem`), a message read
(`FinishItem`), and a message to the session a launch runs (`SendItem`). They're
the inbox's own kinds, registered with the service by `cli.py`; a room can't
send them, since it can't reach the control socket, and the store isn't
mounted.

Trust on launch sends the approval's (*Trust on launch: the summary first*): the
launch asks it (`AskApproval`, joining the one waiting about the same zone) and
waits on its answer (`AwaitApproval`, whose reply comes once it's answered); the
launching terminal, or `lup-dev inbox answer` at any other, answers it
(`AnswerApproval`), whichever comes first; `lup-dev inbox show --diff` reads its
whole diff (`ShowDiff`).
"""

from pathlib import Path
from typing import Literal, override

from lup.types import Model
from lup_dev.host.protocol import LaunchId, Reply, Request
from lup_dev.host.service import Handler, Route
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import Approval, Item, Operator, Ruling, Waiting


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


class AskApproval(Request):
    """Ask the operator's approval, its whole diff kept beside it; or join the approval waiting about the same zone."""

    kind: Literal["inbox-ask-approval"] = "inbox-ask-approval"
    question: str
    """Answered yes or no."""
    summary: str
    """What the operator reads first, coloured as git prints it."""
    diff: str
    """The whole diff, coloured, shown on request."""
    repository: Path
    """The git directory of the repository whose host zone it is."""
    fingerprint: str
    """The zone's fingerprint, which a launch asking about the same zone joins by."""
    worktree: Path
    """The worktree the launch asking it runs in."""

    def approval(self) -> Approval:
        """Return the approval as the inbox keeps it, its diff beside it."""
        return Approval(
            text=self.question,
            summary=self.summary,
            repository=self.repository,
            fingerprint=self.fingerprint,
        )


class AwaitApproval(Request):
    """Wait for an approval's answer: the reply comes once it's answered, wherever it is."""

    kind: Literal["inbox-await-approval"] = "inbox-await-approval"
    number: int


class AnswerApproval(Request):
    """Answer an approval, yes or no."""

    kind: Literal["inbox-answer-approval"] = "inbox-answer-approval"
    number: int
    approved: bool


class ShowDiff(Request):
    """Read an approval's whole diff."""

    kind: Literal["inbox-show-diff"] = "inbox-show-diff"
    number: int


class Items(Reply):
    """Items, oldest first."""

    kind: Literal["inbox-items"] = "inbox-items"
    items: list[Item]


class Shown(Reply):
    """One item, whole."""

    kind: Literal["inbox-item"] = "inbox-item"
    item: Item


class Settled(Reply):
    """An approval as it stands once answered, and whether this answer was the one that answered it."""

    kind: Literal["inbox-settled"] = "inbox-settled"
    item: Item
    here: bool
    """Whether this answer decided it; else it was answered before, elsewhere,
    and this one changed nothing."""


class Whole(Reply):
    """An approval's whole diff, coloured."""

    kind: Literal["inbox-diff"] = "inbox-diff"
    text: str


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


class ApprovalAsking(Model, Handler[AskApproval], arbitrary_types_allowed=True):
    """Answers `AskApproval`: the approval in the operator's inbox, or the one waiting about the same zone."""

    delivery: Delivery

    @override
    def request(self) -> type[AskApproval]:
        return AskApproval

    @override
    async def answer(self, request: AskApproval) -> Reply:
        item = await self.delivery.asked(
            request.approval(), request.diff, request.worktree
        )
        return Shown(item=item)


class ApprovalAwaiting(Model, Handler[AwaitApproval], arbitrary_types_allowed=True):
    """Answers `AwaitApproval` once the approval is answered, with the approval as it stands."""

    delivery: Delivery

    @override
    def request(self) -> type[AwaitApproval]:
        return AwaitApproval

    @override
    async def answer(self, request: AwaitApproval) -> Reply:
        return Shown(item=await self.delivery.settled(request.number))


class ApprovalAnswering(Model, Handler[AnswerApproval], arbitrary_types_allowed=True):
    """Answers `AnswerApproval`: the approval answered, where nothing answered it first."""

    delivery: Delivery

    @override
    def request(self) -> type[AnswerApproval]:
        return AnswerApproval

    @override
    async def answer(self, request: AnswerApproval) -> Reply:
        before = self.delivery.approval(request.number)
        after = self.delivery.decided(request.number, approved=request.approved)
        return Settled(item=after, here=isinstance(before.state, Waiting))


class DiffShowing(Model, Handler[ShowDiff], arbitrary_types_allowed=True):
    """Answers `ShowDiff`: the approval's whole diff."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowDiff]:
        return ShowDiff

    @override
    async def answer(self, request: ShowDiff) -> Reply:
        self.delivery.approval(request.number)
        return Whole(text=self.delivery.inbox.diff(request.number))


def routes(delivery: Delivery) -> list[Route]:
    """Route each of the inbox's kinds to its handler, over one delivery."""
    return [
        Route.to(Listing(delivery=delivery)),
        Route.to(Showing(delivery=delivery)),
        Route.to(Answering(delivery=delivery)),
        Route.to(Finishing(delivery=delivery)),
        Route.to(Sending(delivery=delivery)),
        Route.to(ApprovalAsking(delivery=delivery)),
        Route.to(ApprovalAwaiting(delivery=delivery)),
        Route.to(ApprovalAnswering(delivery=delivery)),
        Route.to(DiffShowing(delivery=delivery)),
    ]
