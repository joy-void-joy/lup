"""The operator's requests to lup's inbox, on the host service's control socket, and their handlers.

`docs/inbox.md`, *The operator's face*. `lup-dev inbox` and its commands
send these, each a typed request on the control socket, starting the service
where none runs, as a launch does: what waits for the operator (`ListInbox`), one
item whole (`ShowItem`), a question's answer (`AnswerItem`), a message read
(`FinishItem`), and a message to the session a launch runs (`SendItem`). They're
the inbox's own kinds, registered with the service by `cli.py`. A room reaches
those that only read on its launch's request socket, each answered with what's of
its repository alone (`Reading`): an item of another's is refused, and a list
leaves it out. The rest a room never reaches, and the store isn't mounted.

Trust on launch sends the approval's (`docs/trust.md`): the
launch asks it (`AskApproval`, joining the one waiting about the same zone) and
waits on its answer (`AwaitApproval`, whose reply comes once it's answered); the
launching terminal, or `lup-dev inbox answer` at any other, answers it
(`AnswerApproval`), whichever comes first; `lup-dev inbox show --diff` reads its
whole diff (`ShowDiff`), and the dashboard each file it changes, whole
(`ShowFiles`), as of a held change (`AskHold`) and of a write that landed
flagged (`AskFlag`, joining the item `ShowGathering` finds gathering the
conversation's flagged writes to the file).

The dashboard reads a conversation whole: its steps, as its runtime records
them (`ShowConversation`), and the items it sent and was sent, in every state
(`ListItems`), which its page places among them.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal, override

from lup.types import Model
from lup_dev.git import Git
from lup_dev.host.protocol import LaunchId, Reply, Request
from lup_dev.host.records import Entry, Recorded, within
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.inbox import context
from lup_dev.inbox.delivery import Delivery, body
from lup_dev.inbox.store import (
    Approval,
    ChangedFile,
    Conversation,
    Draft,
    Flagged,
    HeldChange,
    InboxError,
    Item,
    Operator,
    Passage,
    Ruling,
    Talk,
    Waiting,
    cited,
)
from lup_dev.listing import Span


class ListInbox(Request, Span, reads=True):
    """List what waits in the operator's inbox, oldest first, made within `since` and `until`: a duration counted back by the service's clock, and every item waiting, where neither is given."""

    kind: Literal["inbox-list"] = "inbox-list"


class ShowItem(Request, reads=True):
    """Show one item whole."""

    kind: Literal["inbox-show"] = "inbox-show"
    number: int


class AnswerItem(Request, reads=False):
    """Answer a question: a verdict on each of its decisions, and a comment on the whole, or a plain question's answer in words."""

    kind: Literal["inbox-answer"] = "inbox-answer"
    number: int
    rulings: list[Ruling] = []
    comment: str = ""


class FinishItem(Request, reads=False):
    """Take a message the operator has read off their list."""

    kind: Literal["inbox-done"] = "inbox-done"
    number: int


class SendItem(Request, reads=False):
    """Send the operator's message to a conversation of the session a launch runs: its main one, or one of its subagents."""

    kind: Literal["inbox-send"] = "inbox-send"
    launch: LaunchId
    text: str
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""
    passages: list[Passage] = []
    """The passages of the conversation's words the operator replied to, where
    they send it from reading the conversation."""


class ShowDraft(Request, reads=True):
    """Show the operator's draft reply: what they've written on the items they're reading."""

    kind: Literal["inbox-draft"] = "inbox-draft"


class KeepDraft(Request, reads=False):
    """Keep the operator's draft reply as it stands, in place of the last."""

    kind: Literal["inbox-keep-draft"] = "inbox-keep-draft"
    draft: Draft


class ShowTalk(Request, reads=True):
    """Show what the operator writes on one conversation they read, and the messages they sent it from there."""

    kind: Literal["inbox-talk"] = "inbox-talk"
    conversation: Conversation


class KeepTalk(Request, reads=False):
    """Keep what the operator writes on one conversation as it stands, in place of the last."""

    kind: Literal["inbox-keep-talk"] = "inbox-keep-talk"
    conversation: Conversation
    talk: Talk


class SendDraft(Request, reads=False):
    """Send the operator's draft reply: a review to each conversation whose items it covers or it writes to."""

    kind: Literal["inbox-send-draft"] = "inbox-send-draft"


class AskApproval(Request, reads=False):
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


class AwaitApproval(Request, reads=True):
    """Wait for an approval's answer: the reply comes once it's answered, wherever it is."""

    kind: Literal["inbox-await-approval"] = "inbox-await-approval"
    number: int


class AnswerApproval(Request, reads=False):
    """Answer an approval or a held change, yes or no, with what the operator adds."""

    kind: Literal["inbox-answer-approval"] = "inbox-answer-approval"
    number: int
    approved: bool
    comment: str = ""


class AskHold(Request, reads=False):
    """Put a held change in the operator's inbox: what's held and why, its diff and each file held, and the session that made it."""

    kind: Literal["inbox-ask-hold"] = "inbox-ask-hold"
    change: HeldChange
    sender: Conversation
    diff: str
    files: list[ChangedFile]
    """Each file held, whole: what it holds, and what the change makes it."""
    call: str | None = None
    """The runtime's id for the call that made the change, which the item keeps."""


class ShowGathering(Request, reads=True):
    """Find the item a write that landed flagged would join: the one gathering the same conversation's flagged writes to the same file, while the operator hasn't read it (`Inbox.gathering`)."""

    kind: Literal["inbox-show-gathering"] = "inbox-show-gathering"
    sender: Conversation
    worktree: Path
    path: Path
    """The file, from the worktree's root."""


class AskFlag(Request, reads=False):
    """Put a write that landed flagged in the operator's inbox: what its file's whole change flags, that change's diff and its file whole, and the conversation that made it."""

    kind: Literal["inbox-ask-flag"] = "inbox-ask-flag"
    flagged: Flagged
    sender: Conversation
    diff: str
    file: ChangedFile
    """The file whole since the item it joins was made: what it held before that
    item's first write, and what this write makes it, judged as one change."""
    call: str | None = None
    """The runtime's id for the call that made the write, which an item of its
    own keeps."""
    joining: int | None = None
    """The item it joins, as `ShowGathering` found it; none for one of its own."""
    refreshing: bool = False
    """Whether the write flags nothing of its own, and only brings the item it
    joins to its file as it stands: where that item gathers no more, it makes
    none."""


class ShowDiff(Request, reads=True):
    """Read the whole diff of an approval, a held change or a flagged write."""

    kind: Literal["inbox-show-diff"] = "inbox-show-diff"
    number: int


class ShowFiles(Request, reads=True):
    """Read each file an approval, a held change or a flagged write touches, whole before and after."""

    kind: Literal["inbox-show-files"] = "inbox-show-files"
    number: int


class ShowConversation(Request, reads=True):
    """Read one conversation as its runtime records it, from its step `since` on: the operator's words, the agent's, and the tools it called."""

    kind: Literal["inbox-show-conversation"] = "inbox-show-conversation"
    runtime: str
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's own conversation."""
    since: int = 0
    """How many of its steps the asker has already: only those after are sent."""


class ShowContext(Request, reads=True):
    """Read an item's moment in the conversation that sent it: what led to the call that made it, and what came after."""

    kind: Literal["inbox-show-context"] = "inbox-show-context"
    number: int


class ListItems(Request, reads=True):
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


class Gathering(Reply):
    """The item a flagged write would join, and its file whole as it's kept; none where it would make one of its own."""

    kind: Literal["inbox-gathering"] = "inbox-gathering"
    number: int | None = None
    file: ChangedFile | None = None


class Whole(Reply):
    """An approval's whole diff, coloured; a held change's or a flagged write's."""

    kind: Literal["inbox-diff"] = "inbox-diff"
    text: str


class Files(Reply):
    """Each file an approval, a held change or a flagged write touches, whole before and after, in the order it was asked with."""

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


def owned(item: Item, repository: Path) -> Item:
    """Return `item` where it's of `repository` alone (`Item.of`); refuse it otherwise, saying nothing of it, as to a room of `repository`."""
    if not item.of(repository):
        message = f"{cited(item.number)} isn't this repository's"
        raise InboxError(message)
    return item


class Listing(Model, Reading[ListInbox], arbitrary_types_allowed=True):
    """Answers `ListInbox`: the items waiting for the operator."""

    delivery: Delivery

    @override
    def request(self) -> type[ListInbox]:
        return ListInbox

    @override
    async def answer(self, request: ListInbox) -> Reply:
        inbox = self.delivery.inbox
        return Items(items=self.waiting(request), reviewed=inbox.reviewed())

    @override
    async def scoped(self, request: ListInbox, repository: Path) -> Reply:
        waiting = [each for each in self.waiting(request) if each.of(repository)]
        return Items(items=waiting, reviewed=self.delivery.inbox.reviewed(repository))

    def waiting(self, request: ListInbox) -> list[Item]:
        """Return the items waiting for the operator, made within `request`'s window."""
        window = request.window(self.delivery.clock.now())
        waiting = self.delivery.inbox.waiting(Operator())
        return [each for each in waiting if window.covers(each.made)]


class Showing(Model, Reading[ShowItem], arbitrary_types_allowed=True):
    """Answers `ShowItem`: the item, whole."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowItem]:
        return ShowItem

    @override
    async def answer(self, request: ShowItem) -> Reply:
        return Shown(item=self.delivery.inbox.item(request.number))

    @override
    async def scoped(self, request: ShowItem, repository: Path) -> Reply:
        return Shown(item=owned(self.delivery.inbox.item(request.number), repository))


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
        sent = await self.delivery.sent(
            request.launch, request.text, request.agent, request.passages
        )
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


class ApprovalAwaiting(Model, Reading[AwaitApproval], arbitrary_types_allowed=True):
    """Answers `AwaitApproval` once the approval is answered, with the approval as it stands."""

    delivery: Delivery

    @override
    def request(self) -> type[AwaitApproval]:
        return AwaitApproval

    @override
    async def answer(self, request: AwaitApproval) -> Reply:
        return Shown(item=await self.delivery.settled(request.number))

    @override
    async def scoped(self, request: AwaitApproval, repository: Path) -> Reply:
        owned(self.delivery.inbox.item(request.number), repository)
        return await self.answer(request)


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


class GatheringShowing(Model, Reading[ShowGathering], arbitrary_types_allowed=True):
    """Answers `ShowGathering`: the item gathering the conversation's flagged writes to the file, with its file as it's kept."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowGathering]:
        return ShowGathering

    @override
    async def answer(self, request: ShowGathering) -> Reply:
        inbox = self.delivery.inbox
        found = inbox.gathering(request.sender, request.worktree, request.path)
        if found is None:
            return Gathering()
        files = await asyncio.to_thread(inbox.files, found.number)
        file = next((each for each in files if each.path == request.path), None)
        return Gathering(number=found.number, file=file)

    @override
    async def scoped(self, request: ShowGathering, repository: Path) -> Reply:
        if request.sender.repository != repository:
            message = "the conversation isn't one of this repository's"
            raise InboxError(message)
        return await self.answer(request)


class FlagAsking(Model, Handler[AskFlag], arbitrary_types_allowed=True):
    """Answers `AskFlag`: the flagged write in the operator's inbox, joining the item it names where that one still gathers."""

    delivery: Delivery

    @override
    def request(self) -> type[AskFlag]:
        return AskFlag

    @override
    async def answer(self, request: AskFlag) -> Reply:
        item = await self.delivery.flagged(
            request.flagged,
            request.sender,
            request.diff,
            request.file,
            call=request.call,
            joining=request.joining,
            refreshing=request.refreshing,
        )
        return Shown(item=item)


class ContextShowing(Model, Reading[ShowContext], arbitrary_types_allowed=True):
    """Answers `ShowContext`: an item's moment, read from its sender's record as it stands (`inbox/context.py`)."""

    delivery: Delivery
    recorded: dict[str, Recorded]
    """Each runtime's records on this machine, and how they're read, by its name."""

    @override
    def request(self) -> type[ShowContext]:
        return ShowContext

    @override
    async def answer(self, request: ShowContext) -> Reply:
        return await self.moment(self.delivery.inbox.item(request.number))

    @override
    async def scoped(self, request: ShowContext, repository: Path) -> Reply:
        return await self.moment(
            owned(self.delivery.inbox.item(request.number), repository)
        )

    async def moment(self, item: Item) -> Context:
        """Read `item`'s moment from its sender's record, off the event loop."""
        found = await asyncio.to_thread(context.read, item, self.recorded)
        return Context(number=item.number, entries=found.entries, anchor=found.anchor)


def written(item: Item) -> str:
    """Return the text of an item a conversation sent, whole: as it wrote it, a question with its decisions and leans; a change held from it, with what's held and why, or one that landed flagged, with what's flagged."""
    match item.reason:
        case (
            HeldChange(text=text, summary=summary) | Flagged(text=text, summary=summary)
        ):
            return f"{text}\n{summary}"
        case _:
            return body(item)


class ItemsListing(Model, Reading[ListItems], arbitrary_types_allowed=True):
    """Answers `ListItems`: the items the conversation sent, as it wrote them, and those it was sent, as it's told them."""

    delivery: Delivery

    @override
    def request(self) -> type[ListItems]:
        return ListItems

    @override
    async def answer(self, request: ListItems) -> Reply:
        party = request.conversation
        return self.exchanged(party, self.delivery.inbox.exchanged(party))

    @override
    async def scoped(self, request: ListItems, repository: Path) -> Reply:
        party = request.conversation
        if party.repository != repository:
            message = "the conversation isn't one of this repository's"
            raise InboxError(message)
        items = self.delivery.inbox.exchanged(party)
        return self.exchanged(party, [each for each in items if each.of(repository)])

    def exchanged(self, party: Conversation, items: list[Item]) -> Exchanged:
        """Return `items` as `party` sent them, as it wrote them, and as it was sent them, as it's told them."""
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
    Model, Reading[ShowConversation], arbitrary_types_allowed=True
):
    """Answers `ShowConversation`: the steps of one conversation's record after those the asker has, each record read again only once it changed; for a room, only a record that ran in its repository."""

    recorded: dict[str, Recorded]
    """Each runtime's records on this machine, and how they're read, by its name."""
    recording: context.Recording = context.Recording()

    @override
    def request(self) -> type[ShowConversation]:
        return ShowConversation

    @override
    async def answer(self, request: ShowConversation) -> Reply:
        read = await self.read(request)
        return self.conversed(read.transcript.entries, request.since)

    @override
    async def scoped(self, request: ShowConversation, repository: Path) -> Reply:
        """Answer only where the record says it ran in the repository's git directory or one of its worktrees, as lup keeps a repository's sessions (`lup.transcripts`)."""
        read = await self.read(request)
        under = await asyncio.to_thread(
            lambda: [repository, *Git.pinned(repository).worktrees()]
        )
        ran = read.transcript.directory
        if ran is None or not within(ran, under):
            message = "the conversation isn't one of this repository's"
            raise InboxError(message)
        return self.conversed(read.transcript.entries, request.since)

    async def read(self, request: ShowConversation) -> context.Read:
        """Read the conversation's record as it stands, off the event loop."""
        return await asyncio.to_thread(
            self.recording.read,
            self.recorded,
            request.runtime,
            request.session,
            request.agent,
        )

    def conversed(self, steps: list[Entry], since: int) -> Conversed:
        """Return the conversation's steps after the first `since`."""
        return Conversed(entries=steps[since:], since=since, total=len(steps))


class DiffShowing(Model, Reading[ShowDiff], arbitrary_types_allowed=True):
    """Answers `ShowDiff`: the item's whole diff."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowDiff]:
        return ShowDiff

    @override
    async def answer(self, request: ShowDiff) -> Reply:
        self.delivery.changing(request.number)
        return Whole(text=self.delivery.inbox.diff(request.number))

    @override
    async def scoped(self, request: ShowDiff, repository: Path) -> Reply:
        owned(self.delivery.inbox.item(request.number), repository)
        return await self.answer(request)


class FilesShowing(Model, Reading[ShowFiles], arbitrary_types_allowed=True):
    """Answers `ShowFiles`: each file the approval, held change or flagged write touches, whole, read off the event loop, since they can run to megabytes."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowFiles]:
        return ShowFiles

    @override
    async def answer(self, request: ShowFiles) -> Reply:
        self.delivery.changing(request.number)
        files = await asyncio.to_thread(self.delivery.inbox.files, request.number)
        return Files(number=request.number, files=files)

    @override
    async def scoped(self, request: ShowFiles, repository: Path) -> Reply:
        owned(self.delivery.inbox.item(request.number), repository)
        return await self.answer(request)


class DraftShowing(Model, Reading[ShowDraft], arbitrary_types_allowed=True):
    """Answers `ShowDraft`: the draft as it stands; never to a room, since the operator's unsent reply is theirs, of no repository."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowDraft]:
        return ShowDraft

    @override
    async def answer(self, request: ShowDraft) -> Reply:
        return Drafted(draft=self.delivery.inbox.draft())

    @override
    async def scoped(self, request: ShowDraft, repository: Path) -> Reply:
        message = "the operator's draft reply is theirs until they send it"
        raise InboxError(message)


class DraftKeeping(Model, Handler[KeepDraft], arbitrary_types_allowed=True):
    """Answers `KeepDraft`: the draft kept."""

    delivery: Delivery

    @override
    def request(self) -> type[KeepDraft]:
        return KeepDraft

    @override
    async def answer(self, request: KeepDraft) -> Reply:
        return Drafted(draft=self.delivery.drafted(request.draft))


class TalkShowing(Model, Reading[ShowTalk], arbitrary_types_allowed=True):
    """Answers `ShowTalk`: what the operator wrote on the conversation, as it stands; never to a room, since what they haven't sent is theirs."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowTalk]:
        return ShowTalk

    @override
    async def answer(self, request: ShowTalk) -> Reply:
        return Talked(talk=self.delivery.inbox.talk(request.conversation))

    @override
    async def scoped(self, request: ShowTalk, repository: Path) -> Reply:
        message = (
            "what the operator writes on a conversation is theirs until they send it"
        )
        raise InboxError(message)


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
        Route.reading(Listing(delivery=delivery)),
        Route.reading(Showing(delivery=delivery)),
        Route.to(Answering(delivery=delivery)),
        Route.to(Finishing(delivery=delivery)),
        Route.to(Sending(delivery=delivery)),
        Route.to(ApprovalAsking(delivery=delivery)),
        Route.reading(ApprovalAwaiting(delivery=delivery)),
        Route.to(ApprovalAnswering(delivery=delivery)),
        Route.to(HoldAsking(delivery=delivery)),
        Route.reading(GatheringShowing(delivery=delivery)),
        Route.to(FlagAsking(delivery=delivery)),
        Route.reading(DiffShowing(delivery=delivery)),
        Route.reading(FilesShowing(delivery=delivery)),
        Route.reading(ContextShowing(delivery=delivery, recorded=recorded)),
        Route.reading(ConversationShowing(recorded=recorded)),
        Route.reading(ItemsListing(delivery=delivery)),
        Route.reading(DraftShowing(delivery=delivery)),
        Route.to(DraftKeeping(delivery=delivery)),
        Route.to(DraftSending(delivery=delivery)),
        Route.reading(TalkShowing(delivery=delivery)),
        Route.to(TalkKeeping(delivery=delivery)),
    ]
