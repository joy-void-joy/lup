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

The dashboard reads a conversation's steps as their runtime records them
(`ShowConversation`), for their task list and their context; the conversation
it shows is `Transcripts`' view of it. A conversation's items, those they sent
and were sent in every state, each with its line (`ListItems`,
`inbox/lines.py`), are what a module's view of the conversation weaves in, read
through the core.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, override

from lup import blocks
from lup.types import Model
from lup_dev.git import Git
from lup_dev.host.protocol import LaunchId, Reply, Request
from lup_dev.host.records import (
    Entry,
    Recorded,
    Task,
    Transcript,
    Usage,
    within,
)
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.inbox import context, lines, marks
from lup_dev.inbox.delivery import Delivery, written
from lup_dev.inbox.marks import CORE, MarkStore
from lup_dev.inbox.reading import Narrowing, Reader, Spelling
from lup_dev.inbox.roster import Roster, ids
from lup_dev.inbox.store import (
    Answer,
    Approval,
    ChangedFile,
    Draft,
    Flagged,
    HeldChange,
    InboxError,
    Item,
    Message,
    Order,
    Passage,
    Review,
    Ruling,
    Talk,
    Waiting,
    cited,
)
from lup_dev.layout import Layout
from lup_dev.listing import Span
from lup_ledger.parties import Conversation, Operator

if TYPE_CHECKING:
    from collections.abc import Callable


class ListInbox(Request, Span, reads=True):
    """List what waits in the operator's inbox, oldest first, made within `since` and `until`: a duration counted back by the service's clock, and every item waiting, where neither is given."""

    kind: Literal["inbox-list"] = "inbox-list"


class ReadInbox(Request, Narrowing, reads=True):
    """Read the operator's own exchange, the items they sent or were sent, as the agents' `inbox` tool reads the repository's: a line an item or each whole, narrowed to their exchange with one conversation, to kinds, to a time, and to what waits for them unless `every` is asked (`inbox/reading.py`)."""

    kind: Literal["inbox-read"] = "inbox-read"


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
    """Send the operator's message to a conversation of the session a launch runs: their main one, or one of their subagents."""

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


class ShowOrder(Request, reads=True):
    """Show where the dashboard's review lays out its groups, as the operator has seen them: kept for every page they open, across reloads."""

    kind: Literal["inbox-order"] = "inbox-order"


class KeepOrder(Request, reads=False):
    """Keep where the dashboard's review lays out its groups once a page laid them out: each kept where it was, any other after them, and those gone from the page dropped (`Order.laid`)."""

    kind: Literal["inbox-keep-order"] = "inbox-keep-order"
    places: list[str]
    """Each group the page laid out, by what names its place (`Group.place`,
    `page/src/review.ts`), in the order it laid them out."""
    gone: list[str] = []
    """The places of the groups gone from the page: each its last layout laid
    out and this one doesn't, and, as it first lays the review out, each kept
    it doesn't lay out."""


class ShowTalk(Request, reads=True):
    """Show what the operator writes on one conversation they read, and the messages they sent the conversation from there."""

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
    first: bool = False
    """Whether it's the zone's first approval (`Approval.first`)."""

    def approval(self) -> Approval:
        """Return the approval as the inbox keeps it, its diff and files beside it."""
        return Approval(
            text=self.question,
            summary=self.summary,
            repository=self.repository,
            fingerprint=self.fingerprint,
            pushed_by=self.pushed_by,
            typing=self.typing,
            first=self.first,
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
    """Read one conversation as its runtime records it, from its step `since` on: the operator's words, the agent's, and the tools they called."""

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


class Seen(Model):
    """How far the operator has seen an agent's group, as the core's review mark on it says (`lup_dev.inbox.marks`): its items up to `item` aren't new to them."""

    conversation: Conversation
    item: int
    """The last item of the group they'd seen as they marked it."""
    at: datetime
    """When they marked it, as their reply was sent."""


class Items(Reply):
    """Items, oldest first, and how far the operator has seen each group they're in."""

    kind: Literal["inbox-items"] = "inbox-items"
    items: list[Item]
    seen: list[Seen] = []
    """How far the operator has seen the group of each conversation among the
    items' senders, where they've marked it seen: an item after it is new to
    them, unless they commented on it in a reply sent (`answers`)."""
    answers: list[Item] = []
    """The operator's own items about those listed: those a turn's end listed
    answers or cites, which the page lays out above it, and a review, a reply
    or an answer to one listed, with the replies copies before kept on them
    (`Item.replies`), which it lays out under it (`docs/dashboard.md`, *The
    review*)."""
    commented: list[Item] = []
    """The conversations' items the operator's in `answers` are on, as they
    stand: whose each is, so the page shows an agent the operator's words on their
    own items alone, and what each says as it stands, a comment on a passage an
    edit changed marked outdated."""
    paths: list[Pathed] = []
    """Each conversation the items name, with its path, where lup knows it
    (`pathed`): how the dashboard and `lup-dev inbox` name an agent that isn't
    running, or isn't their launch's latest session, whom no launch shown there
    names."""
    landings: dict[int, str] = {}
    """By each flagged write listed that a landing waits on, what that landing
    lands where (`Delivery.landing`): what `lup-dev inbox` says on the flags'
    line."""


class Readout(Reply):
    """What a reading of the inbox says, and how many items it found before its limit: none where it found no conversation of the name it was given."""

    kind: Literal["inbox-readout"] = "inbox-readout"
    text: str
    found: int = 0


class Shown(Reply):
    """One item, whole, and each conversation it names by their path."""

    kind: Literal["inbox-item"] = "inbox-item"
    item: Item
    paths: list[Pathed] = []
    """Each conversation the item names, with their path, where lup knows it
    (`pathed`): how `lup-dev inbox` names them."""


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


class Ordered(Reply):
    """Where the dashboard's review lays out its groups, as kept."""

    kind: Literal["inbox-ordered"] = "inbox-ordered"
    order: Order


class Talked(Reply):
    """What the operator writes on one conversation, as it stands."""

    kind: Literal["inbox-talked"] = "inbox-talked"
    talk: Talk


class Reviewed(Reply):
    """What sending a draft did: the reviews it was sent as, one to each conversation it covers, and what it did with the approvals and held changes it covers (`Delivery.reviewed`)."""

    kind: Literal["inbox-reviewed"] = "inbox-reviewed"
    items: list[Item]
    read: list[int] = []
    """The messages it took off the list marked read with nothing to add, by
    number, which tells their senders nothing."""
    approved: list[Item] = []
    """The approvals and held changes it approved: an approval of a host zone
    among them is acted on as the operator's terminal acts on it."""
    declined: list[Item] = []
    """The approvals and held changes it declined."""
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
    """A conversation's steps, from step `since` on, and how many it has in all; what its context holds and its task list, as its record stands."""

    kind: Literal["inbox-conversation"] = "inbox-conversation"
    entries: list[Entry]
    since: int
    total: int
    usage: Usage | None = None
    """What its context held at its last reply; none where its record says
    nothing of it."""
    tasks: list[Task] = []
    """Its task list as it stands; empty where it keeps none."""


class Context(Reply):
    """An item's moment in the conversation that sent it, read from the runtime's record: from the operator's last words before the call that made it, through the call, to their next words or the record's end."""

    kind: Literal["inbox-context"] = "inbox-context"
    number: int
    entries: list[Entry]
    anchor: int
    """Which of `entries` is the call that made the item."""


class Exchange(Model):
    """One item a conversation sent or was sent, with its text whole, as the conversation wrote it or as they're told it, and its line as a view of the conversation shows it, which the core words (`inbox/lines.py`)."""

    item: Item
    text: str
    line: list[blocks.Span]
    """Its line: `→ @51 question to you · answered by @53`, what its kind says
    of it, then whom it went to or came from, and where it stands; each
    conversation it names a span of their own, said by their path, referring to
    them by their runtime's ids (`Span.conversation`)."""
    at: datetime
    """When it reached the conversation: when it was told it, else made."""
    comment: str = ""
    """The operator's comment on deciding it, where they decided it with one."""
    echoes: bool = False
    """Whether it repeats the conversation's own words, which a view of it shows
    already: a turn's last words, which lup made a note of."""


class Pathed(Model):
    """A conversation, and their path as lup's commands call it: their session's name, then each subagent's down to them (`lup-impl/parser`), an unnamed one by their runtime's id; and whether another conversation shares it."""

    conversation: Conversation
    path: str
    alike: bool = False
    """Whether another conversation of their repository the inbox knows has the
    same path, so they're named with their runtime's ids beside it
    (`inbox/roster.py`)."""

    def said(self) -> str:
        """Say the conversation as lup names them: their path, their runtime's ids in brackets after it where another shares it."""
        return f"{self.path} ({ids(self.conversation)})" if self.alike else self.path


def pathed(roster: Roster, items: list[Item]) -> list[Pathed]:
    """Return each conversation `items` name with their path, once, where lup knows it (`Roster`): each an item is from, for, was addressed to or sent to (`Message.to`), and each a review writes to."""
    named = dict.fromkeys(
        each
        for item in items
        for each in [
            item.sender,
            item.recipient,
            item.addressed,
            *(
                [item.reason.to]
                if isinstance(item.reason, Message) and item.reason.to is not None
                else []
            ),
            *(
                [
                    *(letter.to for letter in item.reason.letters),
                    *(remark.to for remark in item.reason.remarks),
                ]
                if isinstance(item.reason, Review)
                else []
            ),
        ]
        if isinstance(each, Conversation)
    )
    return [
        Pathed(conversation=each, path=path, alike=bool(roster.alike(each)))
        for each in named
        if (path := roster.path(each)) is not None
    ]


def called(conversation: Conversation, paths: list[Pathed]) -> str:
    """Say `conversation` as lup names them, by their path among `paths` (`Pathed.said`), else by their runtime's ids."""
    found = next((each for each in paths if each.conversation == conversation), None)
    return ids(conversation) if found is None else found.said()


class Exchanged(Reply):
    """The items one conversation sent, and those they were sent, each oldest first, in every state, with its text whole, and each conversation among the items' parties by their path."""

    kind: Literal["inbox-exchanged"] = "inbox-exchanged"
    sent: list[Exchange]
    received: list[Exchange]
    """Those for them, those passed on to them from a subagent of their session
    that had ended, and, for a subagent, those for them passed on to their
    session's main conversation once they had."""
    paths: list[Pathed] = []
    """Each conversation the items are from, for or were addressed to, with
    their path, where lup knows their session's name: a view says a
    conversation by it, and refers to them by their runtime's ids, which never
    change as they're renamed."""

    def path(self, conversation: Conversation) -> str | None:
        """Return `conversation`'s path, as the exchange gives it; none where lup knows none."""
        return next(
            (each.path for each in self.paths if each.conversation == conversation),
            None,
        )


def exchanged(
    party: Conversation,
    items: list[Item],
    *,
    written: Callable[[Item], str],
    told: Callable[[Item], str],
    paths: list[Pathed],
) -> Exchanged:
    """Return `items`, those `party` sent, with the text as they wrote it (`written`), and those they were sent, as they're told them (`told`), lup's word on their citations among those, though it's their own item; each with its line as a view of `party` shows it (`lines.lined`), each conversation it names called by their path among `paths`, else by their runtime's ids."""

    def named(conversation: Conversation) -> str:
        return called(conversation, paths)

    def exchange(each: lines.Lined) -> Exchange:
        item = each.item
        return Exchange(
            item=item,
            text=written(item) if each.sent else told(item),
            line=each.line,
            at=each.at,
            comment=each.comment,
            echoes=each.echoes,
        )

    lined = lines.lined(party, items, named)
    return Exchanged(
        sent=[exchange(each) for each in lined if each.sent],
        received=[exchange(each) for each in lined if not each.sent],
        paths=paths,
    )


def shown(delivery: Delivery, item: Item) -> Shown:
    """Return `item` whole, with each conversation it names by their path (`pathed`)."""
    return Shown(item=item, paths=pathed(delivery.roster(), [item]))


def owned(item: Item, repository: Path) -> Item:
    """Return `item` where it's of `repository` alone (`Item.of`); refuse it otherwise, saying nothing of it, as to a room of `repository`."""
    if not item.of(repository):
        message = f"{cited(item.number)} isn't this repository's"
        raise InboxError(message)
    return item


async def ran_in(transcript: Transcript, repository: Path) -> None:
    """Refuse a record, as to a room of `repository`, unless it says it ran in the repository's git directory or one of its worktrees, as lup keeps a repository's sessions (`lup_transcripts`), saying nothing of it.

    A room's hook names whatever session it likes, so its conversation, and
    every item it makes, can be one a host session or another project's room
    ran: the record found under that session's id is read only where it ran
    in the asker's repository.
    """
    under = await asyncio.to_thread(
        lambda: [repository, *Git.pinned(repository).worktrees()]
    )
    ran = transcript.directory
    if ran is None or not within(ran, under):
        message = "the conversation isn't one of this repository's"
        raise InboxError(message)


class Listing(Model, Reading[ListInbox], arbitrary_types_allowed=True):
    """Answers `ListInbox`: the items waiting for the operator, and how far they've seen each group they're in."""

    delivery: Delivery
    layout: Layout
    """lup's state on the host, where each repository's review marks are kept."""

    @override
    def request(self) -> type[ListInbox]:
        return ListInbox

    @override
    async def answer(self, request: ListInbox) -> Reply:
        return self.listed(self.waiting(request))

    @override
    async def scoped(self, request: ListInbox, repository: Path) -> Reply:
        return self.listed(
            [each for each in self.waiting(request) if each.of(repository)]
        )

    def listed(self, waiting: list[Item]) -> Items:
        """Return the items `waiting`, how far the operator has seen each group, the operator's own items about them and the items those are on, and each conversation among them all by their path."""
        answers = self.answering(waiting)
        commented = self.commented(answers)
        return Items(
            items=waiting,
            seen=self.seen(waiting),
            answers=answers,
            commented=commented,
            paths=pathed(self.delivery.roster(), [*waiting, *answers, *commented]),
            landings={
                each.number: named
                for each in waiting
                if (named := self.delivery.landing(each.number)) is not None
            },
        )

    def seen(self, items: list[Item]) -> list[Seen]:
        """Return how far the operator has seen the group of each conversation among `items`' senders, by the core's review mark on it, each repository's marks read once; none for one never marked."""
        senders = list(
            dict.fromkeys(
                each.sender for each in items if isinstance(each.sender, Conversation)
            )
        )
        kept = {
            repository: MarkStore(layout=self.layout.marks(repository)).kept(CORE)
            for repository in dict.fromkeys(each.repository for each in senders)
        }

        def of(conversation: Conversation) -> Seen | None:
            mark = kept[conversation.repository].of(marks.seen(conversation))
            if mark is None or mark.up_to is None:
                return None
            return Seen(conversation=conversation, item=int(mark.up_to), at=mark.at)

        return [found for each in senders if (found := of(each)) is not None]

    def waiting(self, request: ListInbox) -> list[Item]:
        """Return the items waiting for the operator, made within `request`'s window."""
        window = request.window(self.delivery.clock.now())
        waiting = self.delivery.inbox.waiting(Operator())
        return [each for each in waiting if window.covers(each.made)]

    def commented(self, answers: list[Item]) -> list[Item]:
        """Return the items the operator's `answers` are on, oldest first, as they stand: each a review's comments are on, the question an answer answers, the message a reply is to."""
        found = self.delivery.inbox.items

        def on(answer: Item) -> list[int]:
            match answer.reason:
                case Review(comments=comments):
                    return [each.item for each in comments]
                case Answer(question=question):
                    return [question]
                case Message(of=int() as of):
                    return [of]
                case _:
                    return []

        numbers = [number for answer in answers for number in on(answer)]
        return [
            found[number]
            for number in sorted(dict.fromkeys(numbers))
            if number in found
        ]

    def answering(self, items: list[Item]) -> list[Item]:
        """Return the operator's items that any of `items` answers or that answer it, oldest first: those a turn's end follows (`Message.answers`) or cites (`Item.citations`), shown above it; and, each the one sent to the item's sender, a review covering it with a comment on it, a reply to it, or an answer to it, whose comments and the replies copies before kept on them are shown under it.

        A review goes to each conversation it reaches as an item of its own,
        each carrying every comment, so only the copy sent to the item's
        sender answers it: what's under the item is read once.
        """
        found = self.delivery.inbox.items

        def answers(answer: Item, item: Item) -> bool:
            if item.sender not in (answer.recipient, answer.addressed):
                return False
            match answer.reason:
                case Review(comments=comments):
                    return any(each.item == item.number for each in comments)
                case Message(of=int() as of):
                    return of == item.number
                case Answer(question=question):
                    return question == item.number
                case _:
                    return False

        def followed(item: Item) -> list[int]:
            after = item.reason.answers if isinstance(item.reason, Message) else []
            named = [
                each.found.part.item
                for each in item.citations
                if each.found is not None
            ]
            return [*after, *named]

        before = [number for item in items for number in followed(item)]
        return [
            found[number]
            for number in sorted(found)
            if found[number].sender == Operator()
            and (
                number in before or any(answers(found[number], item) for item in items)
            )
        ]


class InboxReading(Model, Reading[ReadInbox], arbitrary_types_allowed=True):
    """Answers `ReadInbox`: the operator's own exchange read as the `inbox` tool reads the repository's, what waits for them unless `every` is asked; every repository's on the host, a room's own for a room; each option named as `lup-dev inbox` names it."""

    delivery: Delivery

    @override
    def request(self) -> type[ReadInbox]:
        return ReadInbox

    @override
    async def answer(self, request: ReadInbox) -> Reply:
        inbox = self.delivery.inbox
        items = [inbox.items[number] for number in sorted(inbox.items)]
        return self.readout(request, items, "")

    @override
    async def scoped(self, request: ReadInbox, repository: Path) -> Reply:
        items = self.delivery.inbox.about(repository)
        return self.readout(request, items, " about this repository")

    def readout(self, request: ReadInbox, items: list[Item], where: str) -> Readout:
        """Read `items` as `request` narrows them, for the operator; `where` says what they are where none is listed."""
        reader = Reader(
            delivery=self.delivery,
            reader=Operator(),
            where=where,
            mine=True,
            spelling=Spelling.command(),
        )
        read = reader.read(items, request)
        return Readout(text=read.text, found=read.found)


class Showing(Model, Reading[ShowItem], arbitrary_types_allowed=True):
    """Answers `ShowItem`: the item, whole."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowItem]:
        return ShowItem

    @override
    async def answer(self, request: ShowItem) -> Reply:
        return shown(self.delivery, self.delivery.inbox.item(request.number))

    @override
    async def scoped(self, request: ShowItem, repository: Path) -> Reply:
        item = owned(self.delivery.inbox.item(request.number), repository)
        return shown(self.delivery, item)


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
        return shown(self.delivery, answer)


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
        return shown(self.delivery, sent)


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
        """Answer only where the item is the repository's, and its sender's record says it ran in the repository (`ran_in`): checked before the call is looked for, so a refusal says nothing of the record."""
        item = owned(self.delivery.inbox.item(request.number), repository)
        read = await asyncio.to_thread(context.sent, item, self.recorded)
        await ran_in(read.transcript, repository)
        return self.anchored(item, read)

    async def moment(self, item: Item) -> Context:
        """Read `item`'s moment from its sender's record, off the event loop."""
        read = await asyncio.to_thread(context.sent, item, self.recorded)
        return self.anchored(item, read)

    def anchored(self, item: Item, read: context.Read) -> Context:
        """Return `item`'s moment in its sender's record `read`."""
        found = context.anchored(item, read)
        return Context(number=item.number, entries=found.entries, anchor=found.anchor)


class ItemsListing(Model, Reading[ListItems], arbitrary_types_allowed=True):
    """Answers `ListItems`: the items the conversation sent, as they wrote them, and those they were sent, as they're told them."""

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
        """Return `items` as `party` sent them, as they wrote them, and as they were sent them, as they're told them, each with its line (`exchanged`); and each conversation among the items' parties by their path, as lup names them (`pathed`)."""
        paths = pathed(self.delivery.roster(), items)
        return exchanged(
            party, items, written=written, told=self.delivery.words, paths=paths
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
        return self.conversed(read.transcript, request.since)

    @override
    async def scoped(self, request: ShowConversation, repository: Path) -> Reply:
        """Answer only where the record says it ran in the repository's git directory or one of its worktrees (`ran_in`)."""
        read = await self.read(request)
        await ran_in(read.transcript, repository)
        return self.conversed(read.transcript, request.since)

    async def read(self, request: ShowConversation) -> context.Read:
        """Read the conversation's record as it stands, off the event loop."""
        return await asyncio.to_thread(
            self.recording.read,
            self.recorded,
            request.runtime,
            request.session,
            request.agent,
        )

    def conversed(self, transcript: Transcript, since: int) -> Conversed:
        """Return the conversation's steps after the first `since`, with what its context holds and its task list."""
        steps = transcript.entries
        return Conversed(
            entries=steps[since:],
            since=since,
            total=len(steps),
            usage=transcript.usage,
            tasks=transcript.tasks,
        )


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


class OrderShowing(Model, Reading[ShowOrder], arbitrary_types_allowed=True):
    """Answers `ShowOrder`: where the review lays out its groups; never to a room, since it names the operator's conversations across every repository."""

    delivery: Delivery

    @override
    def request(self) -> type[ShowOrder]:
        return ShowOrder

    @override
    async def answer(self, request: ShowOrder) -> Reply:
        return Ordered(order=self.delivery.inbox.order())

    @override
    async def scoped(self, request: ShowOrder, repository: Path) -> Reply:
        message = "the operator's review is theirs, across every repository"
        raise InboxError(message)


class OrderKeeping(Model, Handler[KeepOrder], arbitrary_types_allowed=True):
    """Answers `KeepOrder`: where the review lays out its groups, kept."""

    delivery: Delivery

    @override
    def request(self) -> type[KeepOrder]:
        return KeepOrder

    @override
    async def answer(self, request: KeepOrder) -> Reply:
        order = self.delivery.inbox.ordered(request.places, request.gone)
        return Ordered(order=order)


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
            read=dispatched.read,
            approved=dispatched.approved,
            declined=dispatched.declined,
            noted=dispatched.noted,
            kept=dispatched.kept,
        )


def routes(
    delivery: Delivery, recorded: dict[str, Recorded], layout: Layout
) -> list[Route]:
    """Route each of the inbox's kinds to its handler, over one delivery; an item's moment, a conversation and its calls read from the records `recorded`, a conversation's record read again only once it changed; how far the operator has seen each group, from the review marks kept in lup's state at `layout`."""
    recording = context.Recording()
    return [
        Route.reading(Listing(delivery=delivery, layout=layout)),
        Route.reading(InboxReading(delivery=delivery)),
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
        Route.reading(ConversationShowing(recorded=recorded, recording=recording)),
        Route.reading(ItemsListing(delivery=delivery)),
        Route.reading(DraftShowing(delivery=delivery)),
        Route.to(DraftKeeping(delivery=delivery)),
        Route.to(DraftSending(delivery=delivery)),
        Route.reading(OrderShowing(delivery=delivery)),
        Route.to(OrderKeeping(delivery=delivery)),
        Route.reading(TalkShowing(delivery=delivery)),
        Route.to(TalkKeeping(delivery=delivery)),
    ]
