"""Threads as the operator's review reads them: each with where it stands, the section it's in and why, what's new since they read it, and its conversation in order, each reply under what it answers.

`docs/inbox.md`, *Threads in the review*. The page lays the review out as one
buffer of threads (`docs/dashboard.md`, *The review*); the host reads them for
it, every repository's, and the operator settles, declines and reopens them:
- **`inbox-threads`** (`ListThreads`) lists every thread (`ThreadRead`): where
  it stands; its section (`Section`): `waiting on you` where something in it
  asks them, a question, an approval, a held change, a problem, a check, or
  it's done for them to confirm; else `new` where something came that they
  haven't read and that asks nothing; else `every thread`; what in it asks
  them (`Ask`), each in the order it came, and since when it's been in its
  section, which the page orders by and keeps, never sorting again; what's
  new, what's in it for the pile to read, frictions and how it felt, which
  makes no thread new or waiting; how much came before where they read it;
  its review mark; and who answers for it; and where each conversation going
  on works (`Working`), whose "since you approved" the page lays out there.
- **`inbox-thread`** (`ShowThread`) reads one thread's conversation (`ThreadEntry`):
  from where they read it, what came before counted but what asks them and a
  part of theirs nothing answers yet, which never fold away as read, or whole;
  each item, check
  or part of their words moved in, in the order it came, and their own words on
  each, a review's comment, an answer's rulings, a reply, under what it's on;
  an item citing a part of their words moved in under that part, which stands
  open until one does, waiting on whoever answers for the thread and never on
  them (`Standing.unanswered`); an agent's last words under the latest of the
  operator's words in the thread they answer; each part of the operator's
  words with what they said there (`ThreadEntry.said`); with the items, the checks,
  the items of other threads that name it, and who's on it, whose places the
  thread's code is read from.
- **`inbox-settle-thread`**, **`inbox-decline-thread`** and
  **`inbox-reopen-thread`** are the operator's, as Space `d` and Space `x` on
  a thread done, to confirm, are, and `lup-dev inbox settle-thread` and its
  kin in their terminal (`Concerns.settled`, `declined`, `reopened`).
  A reply of theirs on what's in a thread done, to confirm, reopens it
  (`Delivery.reopening`).

Where the operator last read a thread is their review mark on it, the core's,
keyed by the thread's node (`marks.on_node`), up to the last of what's in it
the page showed; or, later, their settling or declining it, never lup's. What came before
either is read; what came after is new, but an item they've answered or marked
read. A thread with no mark is read from its start: what they've answered or
read already is still read.

Every thread is read in one pass over the ledger's records of each kind
(`Ledgered`), and made again only once the ledger, the inbox or a launch
served changed (`ThreadReading`), since the page's watch asks again at each
hook any agent makes.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, override

from pydantic import Field

from lup.types import Model, MutableModel
from lup_dev.host.names import Names
from lup_dev.host.protocol import Reply, Request
from lup_dev.host.service import Handler, Reading, Route
from lup_dev.inbox.concerns import Concerns
from lup_dev.inbox.delivery import Delivery
from lup_dev.inbox.marks import CORE, ReviewMark, on_node
from lup_dev.inbox.protocol import Pathed, named_by
from lup_dev.inbox.store import (
    Friction,
    HowItFelt,
    InboxError,
    Item,
    Message,
    Waiting,
    asks,
    ranked,
)
from lup_dev.inbox.texts import what
from lup_dev.inbox.threads import Anchor, anchors, spoken
from lup_ledger.environment.store import Written
from lup_ledger.parties import Conversation, Operator
from lup_ledger.threads import (
    Answered,
    Check,
    Declined,
    Done,
    In,
    Moved,
    Parked,
    Refers,
    Reopened,
    Settled,
    State,
    Status,
    Thread,
    stood,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

type Section = Literal["waiting on you", "new", "every thread"]
"""Where a thread is in the review: something in it asks the operator, or it's
done for them to confirm; else something came they haven't read that asks
nothing; else nothing calls for them."""

type Stated = Annotated[
    Parked | Done | Settled | Declined | Reopened, Field(discriminator="kind")
]
"""A thread's status, as its latest edge saying one says it."""


class Joined(Model):
    """One thing in a thread, where it is in it: a node, an item or a check, or a part of an item moved in, and when it came."""

    node: int
    part: int | None = None
    """The part moved in, by its place in its item; none for the node itself."""
    came: datetime


class Ledgered(Model):
    """What one reading of the threads holds of the ledger, every repository's: each thread, what's in each and its status, each check and its answer, the references to each."""

    threads: dict[int, Thread]
    members: dict[int, list[Joined]]
    """What's in each thread, by its number, in the order it came."""
    statuses: dict[int, Stated]
    """Each thread's latest status, by its number, where one was said."""
    checks: dict[int, Check]
    answers: dict[int, Answered]
    """Each check's answer, by its number, where the operator gave one."""
    references: dict[int, list[int]]
    """The items of other threads that name each, by its number."""

    @classmethod
    def read(cls, concerns: Concerns) -> Ledgered:
        """Read every thread off the ledger `concerns` holds, each kind's records in one read."""
        ledger = concerns.inbox.ledger
        with ledger.together():
            threads = ledger.every(Thread)
            ins = ledger.drawn_of(In)
            moved = ledger.drawn_of(Moved)
            statuses = [
                each
                for each in ledger.drawn_of(Status)
                if isinstance(each, Parked | Done | Settled | Declined | Reopened)
            ]
            checks = ledger.every(Check)
            answers = ledger.drawn_of(Answered)
            refers = ledger.drawn_of(Refers)
        current = {each.source: each for each in ins}
        parts = {(each.source, each.part): each for each in moved}
        joined = sorted(
            [
                *(
                    (each.target, Joined(node=each.source, came=each.at))
                    for each in current.values()
                ),
                *(
                    (
                        each.target,
                        Joined(node=each.source, part=each.part, came=each.at),
                    )
                    for each in parts.values()
                ),
            ],
            key=lambda each: each[1].came,
        )
        return cls(
            threads={each.number: each for each in threads},
            members={
                number: [member for target, member in joined if target == number]
                for number in dict.fromkeys(target for target, _ in joined)
            },
            statuses={each.target: each for each in statuses},
            checks={each.number: each for each in checks},
            answers={each.target: each for each in answers},
            references={
                number: [each.source for each in refers if each.target == number]
                for number in dict.fromkeys(each.target for each in refers)
            },
        )


class Placing(Model):
    """Where a thread is in the review, and since when."""

    section: Section
    since: datetime


class Made(Model):
    """What a reading of the threads was made from: how far the ledger was written, the inbox's version, the launches served, by id, whose conversations hold what they hold, and each session's name, which the paths say."""

    ledger: Written
    inbox: int
    served: list[str]
    names: dict[str, str]


class ReadTo(Model):
    """How far what's in a thread was read: how many of what's in it, in the order it came, and when the last of them came; none read where nothing says so."""

    members: int = 0
    at: datetime | None = None

    @classmethod
    def by(cls, members: list[Joined], at: datetime) -> ReadTo:
        """Return what of `members`, in the order they came, came by `at` as read."""
        came = [each for each in members if each.came <= at]
        return cls(members=len(came), at=at)


class Spot(Model):
    """Where one entry of a thread's conversation is: a node, an item or a check, or one of an item's parts by its place."""

    node: int
    part: int | None = None


class Ask(Model):
    """One thing in a thread asking the operator: an item or a check waiting on them, by its number, what it is in a few words (`a question`, `a check`), and when it came into the thread."""

    node: int
    what: str
    came: datetime


class ThreadRead(Model):
    """One thread as the review reads it: where it stands, the section it's in and why, what's new, and who answers for it."""

    thread: Thread
    state: State
    status: Stated | None = None
    """Its latest status, which says what a parked one waits for and what to
    try on one done; none where none was said."""
    section: Section
    since: datetime
    """Since when it's been in its section: what first asked the operator
    there of what asks them still, its being done where nothing does; the
    first of what's new; else what last came into it, or its making."""
    asks: list[Ask] = []
    """What in it asks the operator, in the order it came."""
    new: list[int] = []
    """The items in it the operator hasn't read that ask nothing, in the order
    they came: what makes it new."""
    pile: list[int] = []
    """Its frictions and how it felt the operator hasn't read, for the pile to
    read, which make it neither new nor waiting."""
    unanswered: list[Spot] = []
    """The parts of the operator's words moved into it that nothing in it
    answers yet (`Standing.unanswered`), in the order they came: each open in
    the thread, waiting on whoever answers for it, never on the operator."""
    members: int = 0
    """How much is in it: items, checks and parts moved in."""
    earlier: int = 0
    """How much of it came before where the operator last read it."""
    mark: ReviewMark | None = None
    """The operator's review mark on it, where they've read it."""
    answering: Conversation | None = None
    """Who answers for it: its holder where they go on, else the holder of the
    nearest thread above that does; none where nobody does."""


class ThreadEntry(Model):
    """One entry of a thread's conversation: what's in the thread, or the operator's words on it, where it's laid out under what it answers, and when it came."""

    spot: Spot
    under: Spot | None = None
    """The entry it answers, which it's laid out under; none for one answering
    nothing in the thread."""
    came: datetime
    member: bool
    """Whether it's in the thread; else it's the operator's words on what is."""
    new: bool = False
    earlier: bool = False
    """Whether it came before where the operator last read the thread: shown
    where something after it is under it."""
    unanswered: bool = False
    """Whether it's a part of the operator's words moved in that nothing in the
    thread answers yet: open, waiting on whoever answers for it."""
    said: str | None = None
    """The operator's words there, where it's a part of an item of theirs: a
    comment, a ruling, a message; none for an item or a check whole, which the
    page reads from the item."""
    to: Conversation | None = None
    """Whom those words were written to, where they're a review's message or
    remark (`Anchor.to`); none else."""


class CheckRead(Model):
    """A check in a thread, with the operator's answer, where they gave one."""

    check: Check
    answer: Answered | None = None


class ThreadShown(Reply):
    """One thread's conversation: the thread as the review reads it, each entry in the order it came, and what they name."""

    kind: Literal["inbox-thread-shown"] = "inbox-thread-shown"
    read: ThreadRead
    entries: list[ThreadEntry]
    left: int = 0
    """How many entries came before where the operator last read it and are
    left out, folded under one line; none where it's read whole."""
    items: list[Item] = []
    """Every item an entry names, and each item of another thread naming this
    one, as they stand."""
    checks: list[CheckRead] = []
    references: list[int] = []
    """The items of other threads that name this one, in the order drawn."""
    under: list[int] = []
    """The threads right under it, by number."""
    on: list[Conversation] = []
    """Who's on it: its holder, then each conversation that wrote what's in it,
    in the order they first did: whose places its code is read from."""
    paths: list[Pathed] = []


class Working(Model):
    """Where a conversation works: the thread what they send lands in where they name none, by its number."""

    conversation: Conversation
    thread: int


class ThreadsRead(Reply):
    """Every thread as the review reads it, by number, each conversation they name by their path, and where each conversation going on works."""

    kind: Literal["inbox-threads-read"] = "inbox-threads-read"
    threads: list[ThreadRead]
    paths: list[Pathed] = []
    working: list[Working] = []
    """Where each conversation going on works, as far as it's known
    (`Readings.working`): the thread whose group the page lays their "since you
    approved" out at the end of."""


class ListThreads(Request, reads=True):
    """List every thread, every repository's, as the review reads it: where each stands, its section and why, what's new and who answers for it."""

    kind: Literal["inbox-threads"] = "inbox-threads"


class ShowThread(Request, reads=True):
    """Show one thread's conversation, from where the operator last read it, or `whole`."""

    kind: Literal["inbox-thread"] = "inbox-thread"
    number: int
    whole: bool = False


class SettleThread(Request, reads=False):
    """Settle a thread, as the operator does: Space `d` on one done, to confirm."""

    kind: Literal["inbox-settle-thread"] = "inbox-settle-thread"
    number: int


class DeclineThread(Request, reads=False):
    """Decline a thread, as the operator does, saying why: Space `x` on one done, to confirm."""

    kind: Literal["inbox-decline-thread"] = "inbox-decline-thread"
    number: int
    why: str = ""


class ReopenThread(Request, reads=False):
    """Reopen a thread, as the operator does, saying why: back to whoever held it."""

    kind: Literal["inbox-reopen-thread"] = "inbox-reopen-thread"
    number: int
    why: str = ""


class ThreadStated(Reply):
    """A thread as it stands once the operator settled, declined or reopened it, and who answers for it, by their path."""

    kind: Literal["inbox-thread-stated"] = "inbox-thread-stated"
    read: ThreadRead
    paths: list[Pathed] = []


def pile(item: Item) -> bool:
    """Say whether `item` is for the pile to read: a friction or how it felt."""
    return isinstance(item.reason, Friction | HowItFelt)


class Beside(Model):
    """What a thread is read with beside the ledger's records: the operator's review mark on it, who answers for it, and the parts of their words moved in that nothing in it answers yet."""

    mark: ReviewMark | None = None
    """The operator's review mark on it, the core's (`on_node`); none where
    they never read it."""
    answering: Conversation | None = None
    """Its holder where they go on, else the holder of the nearest thread
    above it who does; none where nobody does."""
    unanswered: list[Spot] = []
    """In the order they came (`Standing.unanswered`)."""


class ThreadSource(ABC):
    """What the review's threads are read from beside the ledger's records (`Ledgered`): the inbox's items, what each thread is read with (`Beside`), and how each conversation is called.

    The host's is its inbox (`Concerned`); the demo's, its stand-ins
    (`lup_dashboard/demo.py`), so both read the threads alike.
    """

    @abstractmethod
    def items(self) -> Mapping[int, Item]:
        """Return every item, by its number."""

    @abstractmethod
    def beside(self, thread: Thread, *, moved: bool) -> Beside:
        """Return what `thread` is read with: its unanswered parts only where a part was `moved` in, which is all that reads them."""

    @abstractmethod
    def paths(self, conversations: Sequence[Conversation]) -> list[Pathed]:
        """Return each of `conversations` lup knows a path for, with it, once (`Pathed`)."""


class Concerned(Model, ThreadSource, arbitrary_types_allowed=True):
    """The host's threads' source: its inbox, through what it says of its threads (`Concerns`)."""

    concerns: Concerns

    @override
    def items(self) -> Mapping[int, Item]:
        return self.concerns.inbox.items

    @override
    def beside(self, thread: Thread, *, moved: bool) -> Beside:
        standing = self.concerns.threads.standing(thread.number) if moved else None
        return Beside(
            mark=self.concerns.inbox.marks.of(
                thread.repository, CORE, on_node(thread.number)
            ),
            answering=self.concerns.answering(thread),
            unanswered=[]
            if standing is None
            else [
                Spot(node=each.node.number, part=each.part)
                for each in standing.unanswered
            ],
        )

    @override
    def paths(self, conversations: Sequence[Conversation]) -> list[Pathed]:
        roster = self.concerns.roster
        return [
            Pathed(conversation=each, path=path, alike=bool(roster.alike(each)))
            for each in dict.fromkeys(conversations)
            if (path := roster.path(each)) is not None
        ]

    def working(self) -> list[Working]:
        """Return where each conversation going on works, from their whereabouts alone, so reading makes no root: the thread they joined, hold or were handed, else their session's root."""
        places = self.concerns.inbox.whereabouts

        def root(conversation: Conversation) -> int | None:
            main = places.get(conversation.main().key())
            return None if main is None else main.root

        found = [
            Working(conversation=place.conversation, thread=number)
            for place in places.values()
            if self.concerns.live(place.conversation)
            and (number := place.thread or root(place.conversation)) is not None
        ]
        return sorted(found, key=lambda each: each.conversation.key())


class Readings(Model, arbitrary_types_allowed=True):
    """The threads, read once from the ledger (`Ledgered`) and their `source`, as the review reads each, and where each conversation going on works."""

    source: ThreadSource
    ledgered: Ledgered
    working: list[Working] = []

    @classmethod
    def of(cls, concerns: Concerns) -> Readings:
        """Read the threads of the inbox `concerns` holds."""
        source = Concerned(concerns=concerns)
        return cls(
            source=source, ledgered=Ledgered.read(concerns), working=source.working()
        )

    def listed(self) -> ThreadsRead:
        """List every thread as the review reads it, and each conversation they name by their path."""
        threads = [self.read(each) for each in self.ledgered.threads]
        named = [
            each
            for read in threads
            for each in [read.thread.holder, read.answering]
            if each is not None
        ]
        working = [
            each for each in self.working if each.thread in self.ledgered.threads
        ]
        return ThreadsRead(
            threads=threads,
            paths=self.source.paths([*named, *(each.conversation for each in working)]),
            working=working,
        )

    def read(self, number: int) -> ThreadRead:
        """Read thread `number` as the review does."""
        ledgered = self.ledgered
        thread = ledgered.threads[number]
        items = self.source.items()
        members = ledgered.members.get(number, [])
        status = ledgered.statuses.get(number)

        def asked(member: Joined) -> Ask | None:
            # A part of the operator's words moved into a thread waits on its
            # holder, not on them: it shows open in the thread until an item
            # there cites it, and never keeps the operator from inbox zero.
            if member.part is not None:
                return None
            item = items.get(member.node)
            if item is not None:
                waiting = asks(item.recipient, item.reason, item.state)
                return (
                    Ask(node=item.number, what=what(item), came=member.came)
                    if waiting
                    else None
                )
            check = ledgered.checks.get(member.node)
            answer = ledgered.answers.get(member.node)
            if check is None or not check.waiting([] if answer is None else [answer]):
                return None
            return Ask(node=check.number, what="a check", came=member.came)

        asking = [ask for each in members if (ask := asked(each)) is not None]
        beside = self.source.beside(
            thread, moved=any(each.part is not None for each in members)
        )
        mark = beside.mark
        read_to = self.read_to(members, mark, status)

        def unread(member: Joined) -> Item | None:
            item = None if member.part is not None else items.get(member.node)
            if item is None:
                return None
            return (
                item
                if isinstance(item.state, Waiting)
                and ranked(item.reason).name == "news"
                else None
            )

        unreads = [
            item
            for each in members[read_to.members :]
            if (item := unread(each)) is not None
        ]
        new = [each.number for each in unreads if not pile(each)]
        placing = self.placed(
            thread, asking=asking, status=status, new=new, members=members
        )
        return ThreadRead(
            thread=thread,
            state=stood(status, waiting=bool(asking)),
            status=status,
            section=placing.section,
            since=placing.since,
            asks=asking,
            new=new,
            pile=[each.number for each in unreads if pile(each)],
            unanswered=beside.unanswered,
            members=len(members),
            earlier=read_to.members,
            mark=mark,
            answering=beside.answering,
        )

    def read_to(
        self, members: list[Joined], mark: ReviewMark | None, status: Stated | None
    ) -> ReadTo:
        """Return how far what's in a thread was last read: up to what its review `mark` names, or, where that's moved out of it since, what came by when the mark was moved; or what came by when the operator settled or declined it, `status`, where that's further: lup's settling isn't their reading."""
        marked = ReadTo()
        if mark is not None and mark.up_to is not None and mark.up_to.isdecimal():
            named = int(mark.up_to)
            places = [
                at
                for at, each in enumerate(members, start=1)
                if each.node == named and each.part is None
            ]
            marked = (
                ReadTo(members=places[-1], at=members[places[-1] - 1].came)
                if places
                else ReadTo.by(members, mark.at)
            )
        closed = (
            ReadTo.by(members, status.at)
            if isinstance(status, Settled | Declined) and status.by == Operator()
            else ReadTo()
        )
        return marked if marked.members >= closed.members and marked.at else closed

    def placed(
        self,
        thread: Thread,
        *,
        asking: list[Ask],
        status: Stated | None,
        new: list[int],
        members: list[Joined],
    ) -> Placing:
        """Return the section a thread is in, and since when."""
        if asking:
            return Placing(section="waiting on you", since=asking[0].came)
        if isinstance(status, Done):
            return Placing(section="waiting on you", since=status.at)
        came = {each.node: each.came for each in members if each.part is None}
        if new:
            return Placing(section="new", since=came[new[0]])
        return Placing(
            section="every thread",
            since=max([thread.at, *(each.came for each in members)]),
        )

    def shown(self, number: int, *, whole: bool) -> ThreadShown:
        """Read thread `number`'s conversation: from where the operator last read it, each entry an entry after it is under counted too, or `whole`."""
        read = self.read(number)
        ledgered = self.ledgered
        members = ledgered.members.get(number, [])
        items = self.source.items()
        mark = read.mark
        read_to = self.read_to(members, mark, read.status)
        numbers = [each.node for each in members if each.part is None]

        def earlier(came: datetime) -> bool:
            return read_to.at is not None and came <= read_to.at

        moved = [
            Spot(node=each.node, part=each.part)
            for each in members
            if each.part is not None
        ]

        def words(member: Joined) -> Anchor | None:
            item = None if member.part is None else items.get(member.node)
            if item is None:
                return None
            return next(
                (each for each in spoken(item) if each.id.part == member.part), None
            )

        own = [
            ThreadEntry(
                spot=Spot(node=each.node, part=each.part),
                came=each.came,
                member=True,
                new=each.node in read.new and each.part is None,
                earlier=at <= read_to.members,
                unanswered=Spot(node=each.node, part=each.part) in read.unanswered,
                said=None if (anchor := words(each)) is None else anchor.text,
                to=None if anchor is None else anchor.to,
            )
            for at, each in enumerate(members, start=1)
        ]
        said = [
            ThreadEntry(
                spot=Spot(node=item.number, part=anchor.id.part),
                under=Spot(node=anchor.item),
                came=item.made,
                member=False,
                earlier=earlier(item.made),
                said=anchor.text,
            )
            for item in items.values()
            for anchor in anchors(item)
            if anchor.item is not None and anchor.item in numbers
        ]

        def answering(entry: ThreadEntry) -> ThreadEntry:
            item = None if entry.spot.part is not None else items.get(entry.spot.node)
            if item is None:
                return entry
            cited = [
                spot
                for each in item.citations
                if each.part is not None
                and (spot := Spot(node=each.item, part=each.part)) in moved
            ]
            if cited:
                return entry.model_copy(update={"under": cited[0]})
            if not isinstance(item.reason, Message):
                return entry
            answered = item.reason.answers
            before = [
                each
                for each in said
                if each.spot.node in answered and each.came <= item.made
            ]
            if not before:
                return entry
            return entry.model_copy(update={"under": before[-1].spot})

        entries = sorted(
            [*(answering(each) for each in own), *said], key=lambda each: each.came
        )
        asking = {each.node: each for each in read.asks}
        kept = (
            entries
            if whole
            else self.after(
                entries,
                lambda each: (
                    each.unanswered
                    or (
                        each.member
                        and each.spot.part is None
                        and each.spot.node in asking
                    )
                ),
            )
        )
        named = list(
            dict.fromkeys(
                [
                    *(each.spot.node for each in kept),
                    *ledgered.references.get(number, []),
                ]
            )
        )
        shown = [items[each] for each in named if each in items]
        thread = ledgered.threads[number]
        writers = [
            sender
            for each in members
            if (item := items.get(each.node)) is not None
            and isinstance(sender := item.sender, Conversation)
        ]
        holder = [] if thread.holder is None else [thread.holder]
        on = list(dict.fromkeys([*holder, *writers]))
        addressed = [each.to for each in kept if each.to is not None]
        return ThreadShown(
            read=read,
            entries=kept,
            left=len(entries) - len(kept),
            items=shown,
            checks=[
                CheckRead(check=check, answer=ledgered.answers.get(check.number))
                for each in kept
                if (check := ledgered.checks.get(each.spot.node)) is not None
            ],
            references=ledgered.references.get(number, []),
            under=[
                each.number
                for each in ledgered.threads.values()
                if each.parent == number
            ],
            on=on,
            paths=self.source.paths([*named_by(shown), *on, *addressed]),
        )

    def after(
        self, entries: list[ThreadEntry], open_: Callable[[ThreadEntry], bool]
    ) -> list[ThreadEntry]:
        """Return the entries after where the operator last read, each earlier one still `open_`, as what asks them or a part of theirs nothing answers yet, which never folds away as read, and each earlier one an entry kept is under, at any depth, in order."""
        later = [each for each in entries if not each.earlier or open_(each)]
        by_spot = {(each.spot.node, each.spot.part): each for each in entries}

        def above(entry: ThreadEntry, depth: int) -> list[ThreadEntry]:
            under = entry.under
            found = None if under is None else by_spot.get((under.node, under.part))
            if found is None or depth > len(entries):
                return []
            return [found, *above(found, depth + 1)]

        wanted = {
            (each.spot.node, each.spot.part): each
            for entry in later
            for each in [entry, *above(entry, 0)]
        }
        return [each for each in entries if (each.spot.node, each.spot.part) in wanted]


class ThreadReading(MutableModel, arbitrary_types_allowed=True):
    """The threads as the review reads them, over one delivery: read again only once the ledger, the inbox or a launch served changed since the last reading, since the page's watch asks again at every hook."""

    delivery: Delivery
    made: Made | None = None
    """What the last reading was made from; none before the first."""
    readings: Readings | None = None

    def readings_now(self) -> Readings:
        """Return the threads as they stand: those last read, where nothing they're read from changed since."""
        delivery = self.delivery
        launches = delivery.layout.launches
        made = Made(
            ledger=delivery.inbox.ledger.written(),
            inbox=delivery.inbox.version,
            served=sorted(each.name for each in launches.iterdir())
            if launches.is_dir()
            else [],
            names=Names(path=delivery.layout.names).all(),
        )
        if self.readings is not None and self.made == made:
            return self.readings
        self.readings = Readings.of(delivery.concerns())
        self.made = made
        return self.readings

    def listed(self) -> ThreadsRead:
        """List every thread as the review reads it."""
        return self.readings_now().listed()

    def thread(self, number: int) -> Thread:
        """Return thread `number`; say where there's none."""
        return self.delivery.concerns().thread(number)

    def stated(self, number: int) -> ThreadStated:
        """Return thread `number` as it stands, and who answers for it by their path."""
        readings = self.readings_now()
        read = readings.read(number)
        answering = [] if read.answering is None else [read.answering]
        return ThreadStated(read=read, paths=readings.source.paths(answering))


class ThreadsListing(Model, Reading[ListThreads], arbitrary_types_allowed=True):
    """Answers `ListThreads`: every thread as the review reads it; the operator's alone."""

    reading: ThreadReading

    @override
    def request(self) -> type[ListThreads]:
        return ListThreads

    @override
    async def answer(self, request: ListThreads) -> Reply:
        return self.reading.listed()

    @override
    async def scoped(self, request: ListThreads, repository: Path) -> Reply:
        message = "the review's threads are the operator's: a room reads a thread with `inbox`'s `thread`"
        raise InboxError(message)


class ThreadShowing(Model, Reading[ShowThread], arbitrary_types_allowed=True):
    """Answers `ShowThread`: one thread's conversation; the operator's alone."""

    reading: ThreadReading

    @override
    def request(self) -> type[ShowThread]:
        return ShowThread

    @override
    async def answer(self, request: ShowThread) -> Reply:
        self.reading.thread(request.number)
        return self.reading.readings_now().shown(request.number, whole=request.whole)

    @override
    async def scoped(self, request: ShowThread, repository: Path) -> Reply:
        message = "the review's threads are the operator's: a room reads a thread with `inbox`'s `thread`"
        raise InboxError(message)


class ThreadStating(Model, Handler[SettleThread], arbitrary_types_allowed=True):
    """Answers `SettleThread`: the thread settled, whoever answers for it told."""

    reading: ThreadReading

    @override
    def request(self) -> type[SettleThread]:
        return SettleThread

    @override
    async def answer(self, request: SettleThread) -> Reply:
        concerns = self.reading.delivery.concerns()
        concerns.settled(self.reading.thread(request.number))
        return self.reading.stated(request.number)


class ThreadDeclining(Model, Handler[DeclineThread], arbitrary_types_allowed=True):
    """Answers `DeclineThread`: the thread declined, whoever answers for it told why."""

    reading: ThreadReading

    @override
    def request(self) -> type[DeclineThread]:
        return DeclineThread

    @override
    async def answer(self, request: DeclineThread) -> Reply:
        concerns = self.reading.delivery.concerns()
        concerns.declined(self.reading.thread(request.number), request.why)
        return self.reading.stated(request.number)


class ThreadReopening(Model, Handler[ReopenThread], arbitrary_types_allowed=True):
    """Answers `ReopenThread`: the thread reopened, back to whoever held it, told why."""

    reading: ThreadReading

    @override
    def request(self) -> type[ReopenThread]:
        return ReopenThread

    @override
    async def answer(self, request: ReopenThread) -> Reply:
        concerns = self.reading.delivery.concerns()
        concerns.reopened(self.reading.thread(request.number), request.why)
        return self.reading.stated(request.number)


def routes(delivery: Delivery) -> list[Route]:
    """Route reading the review's threads, and settling, declining and reopening one, over `delivery`, each reading shared."""
    reading = ThreadReading(delivery=delivery)
    return [
        Route.reading(ThreadsListing(reading=reading)),
        Route.reading(ThreadShowing(reading=reading)),
        Route.to(ThreadStating(reading=reading)),
        Route.to(ThreadDeclining(reading=reading)),
        Route.to(ThreadReopening(reading=reading)),
    ]
