"""The operator's requests to lup's inbox, on the host service's control socket, and their handlers.

`docs/host-tools.md`, *The operator's face*. `lup-dev inbox` and its commands
send these, each a typed request on the control socket, starting the service
where none runs, as a launch does: what waits for the operator (`ListInbox`), one
item whole (`ShowItem`), a question's answer (`AnswerItem`), a message read
(`FinishItem`), and a message to the session a launch runs (`SendItem`). They're
the inbox's own kinds, registered with the service by `cli.py`; a room can't
send them, since it can't reach the control socket, and the store isn't
mounted.

Trust on launch sends the approval's (`docs/launch.md`, *Trust on launch*): the
launch asks it (`AskApproval`, joining the one waiting about the same zone) and
waits on its answer (`AwaitApproval`, whose reply comes once it's answered); the
launching terminal, or `lup-dev inbox answer` at any other, answers it
(`AnswerApproval`), whichever comes first; `lup-dev inbox show --diff` reads its
whole diff (`ShowDiff`).
"""

import asyncio
from pathlib import Path
from typing import Literal, override

from lup.types import Model
from lup_dev.host.protocol import LaunchId, Reply, Request
from lup_dev.host.records import Entry, Recorded
from lup_dev.host.service import Handler, Route
from lup_dev.inbox import context
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.store import (
    Approval,
    Conversation,
    Draft,
    HeldChange,
    Item,
    Operator,
    Ruling,
    Waiting,
)


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
    """Send the operator's message to a conversation of the session a launch runs: its main one, or one of its subagents."""

    kind: Literal["inbox-send"] = "inbox-send"
    launch: LaunchId
    text: str
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""


class ShowDraft(Request):
    """Show the operator's draft reply: what they've written on the items they're reading."""

    kind: Literal["inbox-draft"] = "inbox-draft"


class KeepDraft(Request):
    """Keep the operator's draft reply as it stands, in place of the last."""

    kind: Literal["inbox-keep-draft"] = "inbox-keep-draft"
    draft: Draft


class SendDraft(Request):
    """Send the operator's draft reply: a review to each conversation whose items it covers."""

    kind: Literal["inbox-send-draft"] = "inbox-send-draft"


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
    """Answer an approval or a held change, yes or no, with what the operator adds."""

    kind: Literal["inbox-answer-approval"] = "inbox-answer-approval"
    number: int
    approved: bool
    comment: str = ""


class AskHold(Request):
    """Put a held change in the operator's inbox: what's held and why, its diff, and the session that made it."""

    kind: Literal["inbox-ask-hold"] = "inbox-ask-hold"
    change: HeldChange
    sender: Conversation
    diff: str


class ShowDiff(Request):
    """Read an approval's whole diff."""

    kind: Literal["inbox-show-diff"] = "inbox-show-diff"
    number: int


class ShowContext(Request):
    """Read an item's moment in the conversation that sent it: what led to the call that made it, and what came after."""

    kind: Literal["inbox-show-context"] = "inbox-show-context"
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


class Drafted(Reply):
    """The operator's draft reply, as it stands."""

    kind: Literal["inbox-drafted"] = "inbox-drafted"
    draft: Draft


class Reviewed(Reply):
    """The reviews a draft was sent as, one to each conversation it covers."""

    kind: Literal["inbox-reviewed"] = "inbox-reviewed"
    items: list[Item]


class Whole(Reply):
    """An approval's whole diff, coloured."""

    kind: Literal["inbox-diff"] = "inbox-diff"
    text: str


class Context(Reply):
    """An item's moment in the conversation that sent it, read from its runtime's record: from the operator's last words before the call that made it, through the call, to their next words or the record's end."""

    kind: Literal["inbox-context"] = "inbox-context"
    number: int
    entries: list[Entry]
    anchor: int
    """Which of `entries` is the call that made the item."""


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
        sent = await self.delivery.sent(request.launch, request.text, request.agent)
        return Shown(item=sent)


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
        after = self.delivery.decided(
            request.number, approved=request.approved, comment=request.comment
        )
        return Settled(item=after, here=isinstance(before.state, Waiting))


class HoldAsking(Model, Handler[AskHold], arbitrary_types_allowed=True):
    """Answers `AskHold`: the held change in the operator's inbox."""

    delivery: Delivery

    @override
    def request(self) -> type[AskHold]:
        return AskHold

    @override
    async def answer(self, request: AskHold) -> Reply:
        item = await self.delivery.held_change(
            request.change, request.sender, request.diff
        )
        return Shown(item=item)


class ContextShowing(Model, Handler[ShowContext], arbitrary_types_allowed=True):
    """Answers `ShowContext`: an item's moment, read from its sender's record as it stands (`inbox/context.py`)."""

    delivery: Delivery
    recorded: dict[str, Recorded]
    """Each runtime's records on this machine, and how they're read, by its name."""

    @override
    def request(self) -> type[ShowContext]:
        return ShowContext

    @override
    async def answer(self, request: ShowContext) -> Reply:
        item = self.delivery.inbox.item(request.number)
        found = await asyncio.to_thread(context.read, item, self.recorded)
        return Context(number=item.number, entries=found.entries, anchor=found.anchor)


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


class DraftShowing(Model, Handler[ShowDraft], arbitrary_types_allowed=True):
    """Answers `ShowDraft`: the draft as it stands."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowDraft]:
        return ShowDraft

    @override
    async def answer(self, request: ShowDraft) -> Reply:
        return Drafted(draft=self.delivery.inbox.draft())


class DraftKeeping(Model, Handler[KeepDraft], arbitrary_types_allowed=True):
    """Answers `KeepDraft`: the draft kept."""

    delivery: Delivery

    @override
    def request(self) -> type[KeepDraft]:
        return KeepDraft

    @override
    async def answer(self, request: KeepDraft) -> Reply:
        return Drafted(draft=self.delivery.inbox.drafted(request.draft))


class DraftSending(Model, Handler[SendDraft], arbitrary_types_allowed=True):
    """Answers `SendDraft`: the reviews it was sent as."""

    delivery: Delivery

    @override
    def request(self) -> type[SendDraft]:
        return SendDraft

    @override
    async def answer(self, request: SendDraft) -> Reply:
        return Reviewed(items=await self.delivery.reviewed())


def routes(delivery: Delivery, recorded: dict[str, Recorded]) -> list[Route]:
    """Route each of the inbox's kinds to its handler, over one delivery; an item's moment read from the records `recorded`."""
    return [
        Route.to(Listing(delivery=delivery)),
        Route.to(Showing(delivery=delivery)),
        Route.to(Answering(delivery=delivery)),
        Route.to(Finishing(delivery=delivery)),
        Route.to(Sending(delivery=delivery)),
        Route.to(ApprovalAsking(delivery=delivery)),
        Route.to(ApprovalAwaiting(delivery=delivery)),
        Route.to(ApprovalAnswering(delivery=delivery)),
        Route.to(HoldAsking(delivery=delivery)),
        Route.to(DiffShowing(delivery=delivery)),
        Route.to(ContextShowing(delivery=delivery, recorded=recorded)),
        Route.to(DraftShowing(delivery=delivery)),
        Route.to(DraftKeeping(delivery=delivery)),
        Route.to(DraftSending(delivery=delivery)),
    ]
