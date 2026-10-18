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
whole diff (`ShowDiff`), and the dashboard each file it changes, whole
(`ShowFiles`), as of a held change (`AskHold`).

The dashboard reads a conversation whole: its steps, as its runtime records
them (`ShowConversation`), and the items it sent and was sent, in every state
(`ListItems`), which its page places among them.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal, override

from lup.types import Model
from lup_dev.host.protocol import LaunchId, Reply, Request
from lup_dev.host.records import Entry, Recorded
from lup_dev.host.service import Handler, Route
from lup_dev.inbox import context
from lup_dev.inbox.delivery import Delivery, body
from lup_dev.inbox.store import (
    Approval,
    ChangedFile,
    Conversation,
    Draft,
    HeldChange,
    Item,
    Operator,
    Ruling,
    Talk,
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


class ShowTalk(Request):
    """Show what the operator writes on one conversation they read, and the messages they sent it from there."""

    kind: Literal["inbox-talk"] = "inbox-talk"
    conversation: Conversation


class KeepTalk(Request):
    """Keep what the operator writes on one conversation as it stands, in place of the last."""

    kind: Literal["inbox-keep-talk"] = "inbox-keep-talk"
    conversation: Conversation
    talk: Talk


class SendDraft(Request):
    """Send the operator's draft reply: a review to each conversation whose items it covers or it writes to."""

    kind: Literal["inbox-send-draft"] = "inbox-send-draft"


class AskApproval(Request):
    """Ask the operator's approval, its whole diff and each file it changes kept beside it; or join the approval waiting about the same zone."""

    kind: Literal["inbox-ask-approval"] = "inbox-ask-approval"
    question: str
    """Answered yes or no."""
    summary: str
    """What the operator reads first, coloured as git prints it."""
    diff: str
    """The whole diff, coloured, shown on request."""
    files: list[ChangedFile]
    """Each file of the zone changed, whole before and after, shown on request."""
    typing: bool = False
    """Whether the files carry the reading of their parse alone, for the service
    to read their types in the background (`Approval.typing`)."""
    repository: Path
    """The git directory of the repository whose host zone it is."""
    fingerprint: str
    """The zone's fingerprint, which a launch asking about the same zone joins by."""
    worktree: Path
    """The worktree the launch asking it runs in."""
    pushed_by: Conversation | None = None
    """The main conversation of the session whose push asked it; none for a
    launch's."""

    def approval(self) -> Approval:
        """Return the approval as the inbox keeps it, its diff and files beside it."""
        return Approval(
            text=self.question,
            summary=self.summary,
            repository=self.repository,
            fingerprint=self.fingerprint,
            pushed_by=self.pushed_by,
            typing=self.typing,
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
    """Put a held change in the operator's inbox: what's held and why, its diff and each file held, and the session that made it."""

    kind: Literal["inbox-ask-hold"] = "inbox-ask-hold"
    change: HeldChange
    sender: Conversation
    diff: str
    files: list[ChangedFile]
    """Each file held, whole: what it holds, and what the change makes it."""
    call: str | None = None
    """The runtime's id for the call that made the change, which the item keeps."""


class ShowDiff(Request):
    """Read an approval's whole diff."""

    kind: Literal["inbox-show-diff"] = "inbox-show-diff"
    number: int


class ShowFiles(Request):
    """Read each file an approval or a held change touches, whole before and after."""

    kind: Literal["inbox-show-files"] = "inbox-show-files"
    number: int


class ShowConversation(Request):
    """Read one conversation as its runtime records it, from its step `since` on: the operator's words, the agent's, and the tools it called."""

    kind: Literal["inbox-show-conversation"] = "inbox-show-conversation"
    runtime: str
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""
    since: int = 0
    """How many of its steps the asker has already: only those after are sent."""


class ShowContext(Request):
    """Read an item's moment in the conversation that sent it: what led to the call that made it, and what came after."""

    kind: Literal["inbox-show-context"] = "inbox-show-context"
    number: int


class ListItems(Request):
    """List the items one conversation sent and was sent, in every state, oldest first, each with its text whole."""

    kind: Literal["inbox-list-items"] = "inbox-list-items"
    conversation: Conversation


class Items(Reply):
    """Items, oldest first, and when the operator last sent a reply."""

    kind: Literal["inbox-items"] = "inbox-items"
    items: list[Item]
    reviewed: datetime | None = None
    """When the operator's last reply was sent, from the review; none before
    their first: what came after it is new to them."""


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


class Talked(Reply):
    """What the operator writes on one conversation, as it stands."""

    kind: Literal["inbox-talked"] = "inbox-talked"
    talk: Talk


class Reviewed(Reply):
    """What sending a draft did: the reviews it was sent as, one to each conversation it covers, and what it did with the approvals and held changes it covers (`Delivery.reviewed`)."""

    kind: Literal["inbox-reviewed"] = "inbox-reviewed"
    items: list[Item]
    approved: list[Item] = []
    """The approvals and held changes it approved: an approval of a host zone
    among them is acted on as the operator's terminal acts on it."""
    noted: list[Item] = []
    """The notes it left with each session whose push asked an approval the
    operator commented on, which stays unanswered."""
    kept: list[int] = []
    """The approvals commented on that no known session's push asked: their
    comments stay drafted."""


class Whole(Reply):
    """An approval's whole diff, coloured."""

    kind: Literal["inbox-diff"] = "inbox-diff"
    text: str


class Files(Reply):
    """Each file an approval or a held change touches, whole before and after, in the order it was asked with."""

    kind: Literal["inbox-files"] = "inbox-files"
    number: int
    files: list[ChangedFile]


class Conversed(Reply):
    """A conversation's steps, from step `since` on, and how many it has in all."""

    kind: Literal["inbox-conversation"] = "inbox-conversation"
    entries: list[Entry]
    since: int
    total: int


class Context(Reply):
    """An item's moment in the conversation that sent it, read from its runtime's record: from the operator's last words before the call that made it, through the call, to their next words or the record's end."""

    kind: Literal["inbox-context"] = "inbox-context"
    number: int
    entries: list[Entry]
    anchor: int
    """Which of `entries` is the call that made the item."""


class Exchange(Model):
    """One item a conversation sent or was sent, with its text whole: as the conversation wrote it, or as it's told it."""

    item: Item
    text: str


class Exchanged(Reply):
    """The items one conversation sent, and those it was sent, each oldest first, in every state, with its text whole."""

    kind: Literal["inbox-exchanged"] = "inbox-exchanged"
    sent: list[Exchange]
    received: list[Exchange]
    """Those for it, those passed on to it from a subagent of its session that
    had ended, and, for a subagent, those for it passed on to its session's main
    conversation once it had."""


class Listing(Model, Handler[ListInbox], arbitrary_types_allowed=True):
    """Answers `ListInbox`: the items waiting for the operator."""

    delivery: Delivery

    @override
    def request(self) -> type[ListInbox]:
        return ListInbox

    @override
    async def answer(self, request: ListInbox) -> Reply:
        inbox = self.delivery.inbox
        return Items(items=inbox.waiting(Operator()), reviewed=inbox.reviewed())


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
            request.approval(), request.diff, request.files, request.worktree
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
    """Answers `AnswerApproval`: the approval answered, where nothing answered it first, the operator's comment told to the session whose push asked it."""

    delivery: Delivery

    @override
    def request(self) -> type[AnswerApproval]:
        return AnswerApproval

    @override
    async def answer(self, request: AnswerApproval) -> Reply:
        before = self.delivery.approval(request.number)
        after = await self.delivery.decided(
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
            request.change,
            request.sender,
            request.diff,
            request.files,
            call=request.call,
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


def written(item: Item) -> str:
    """Return the text of an item a conversation sent, whole: as it wrote it, a question with its decisions and leans; a change held from it, with what's held and why."""
    match item.reason:
        case HeldChange(text=text, summary=summary):
            return f"{text}\n{summary}"
        case _:
            return body(item)


class ItemsListing(Model, Handler[ListItems], arbitrary_types_allowed=True):
    """Answers `ListItems`: the items the conversation sent, as it wrote them, and those it was sent, as it's told them."""

    delivery: Delivery

    @override
    def request(self) -> type[ListItems]:
        return ListItems

    @override
    async def answer(self, request: ListItems) -> Reply:
        party = request.conversation
        items = self.delivery.inbox.exchanged(party)
        return Exchanged(
            sent=[
                Exchange(item=each, text=written(each))
                for each in items
                if each.sender == party
            ],
            received=[
                Exchange(item=each, text=self.delivery.words(each))
                for each in items
                if each.sender != party
            ],
        )


class ConversationShowing(
    Model, Handler[ShowConversation], arbitrary_types_allowed=True
):
    """Answers `ShowConversation`: the steps of one conversation's record after those the asker has, each record read again only once it changed."""

    recorded: dict[str, Recorded]
    """Each runtime's records on this machine, and how they're read, by its name."""
    recording: context.Recording = context.Recording()

    @override
    def request(self) -> type[ShowConversation]:
        return ShowConversation

    @override
    async def answer(self, request: ShowConversation) -> Reply:
        read = await asyncio.to_thread(
            self.recording.read,
            self.recorded,
            request.runtime,
            request.session,
            request.agent,
        )
        steps = read.transcript.entries
        return Conversed(
            entries=steps[request.since :], since=request.since, total=len(steps)
        )


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


class FilesShowing(Model, Handler[ShowFiles], arbitrary_types_allowed=True):
    """Answers `ShowFiles`: each file the approval or held change touches, whole, read off the event loop, since they can run to megabytes."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowFiles]:
        return ShowFiles

    @override
    async def answer(self, request: ShowFiles) -> Reply:
        self.delivery.approval(request.number)
        files = await asyncio.to_thread(self.delivery.inbox.files, request.number)
        return Files(number=request.number, files=files)


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
        return Drafted(draft=self.delivery.drafted(request.draft))


class TalkShowing(Model, Handler[ShowTalk], arbitrary_types_allowed=True):
    """Answers `ShowTalk`: what the operator wrote on the conversation, as it stands."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowTalk]:
        return ShowTalk

    @override
    async def answer(self, request: ShowTalk) -> Reply:
        return Talked(talk=self.delivery.inbox.talk(request.conversation))


class TalkKeeping(Model, Handler[KeepTalk], arbitrary_types_allowed=True):
    """Answers `KeepTalk`: what the operator wrote on the conversation, kept."""

    delivery: Delivery

    @override
    def request(self) -> type[KeepTalk]:
        return KeepTalk

    @override
    async def answer(self, request: KeepTalk) -> Reply:
        talk = self.delivery.inbox.talked(request.conversation, request.talk)
        return Talked(talk=talk)


class DraftSending(Model, Handler[SendDraft], arbitrary_types_allowed=True):
    """Answers `SendDraft`: the reviews it was sent as."""

    delivery: Delivery

    @override
    def request(self) -> type[SendDraft]:
        return SendDraft

    @override
    async def answer(self, request: SendDraft) -> Reply:
        dispatched = await self.delivery.reviewed()
        return Reviewed(
            items=dispatched.reviews,
            approved=dispatched.approved,
            noted=dispatched.noted,
            kept=dispatched.kept,
        )


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
        Route.to(FilesShowing(delivery=delivery)),
        Route.to(ContextShowing(delivery=delivery, recorded=recorded)),
        Route.to(ConversationShowing(recorded=recorded)),
        Route.to(ItemsListing(delivery=delivery)),
        Route.to(DraftShowing(delivery=delivery)),
        Route.to(DraftKeeping(delivery=delivery)),
        Route.to(DraftSending(delivery=delivery)),
        Route.to(TalkShowing(delivery=delivery)),
        Route.to(TalkKeeping(delivery=delivery)),
    ]
