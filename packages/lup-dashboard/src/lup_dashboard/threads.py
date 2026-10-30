"""The demo's threads: stand-in concerns over its stand-in items, read for the review as the host reads its own.

`docs/dashboard.md`, *The page*, its demo; `docs/inbox.md`, *Threads in the
review*. Each thread is kept as the ledger keeps one, a `Thread` with what's
in it in the order it came, its checks and its status, and read through the
host's own reading (`Readings`), so its section, what asks the operator, what's
new since their review mark and its conversation are what the host would say of
them: the demo stands in only for the inbox's items, its review marks, who goes
on and how each is called (`StandInThreads`). The operator settles, declines and
reopens a thread, and answers a check, in memory.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, override

from lup.types import Model, MutableModel
from lup_dev.inbox.marks import CORE, MarkStore, on_node
from lup_dev.inbox.protocol import Pathed
from lup_dev.inbox.store import Item, Message
from lup_dev.inbox.threaded import (
    Beside,
    Joined,
    Ledgered,
    Readings,
    Spot,
    Stated,
    ThreadShown,
    ThreadSource,
    ThreadsRead,
    ThreadStated,
    Working,
)
from lup_ledger.parties import Conversation, Operator
from lup_ledger.threads import (
    Answered,
    Check,
    Declined,
    Reopened,
    Settled,
    Thread,
)

if TYPE_CHECKING:
    from datetime import datetime


class StoodIn(Model):
    """One stand-in thread: the thread, what's in it, and the moment each came, by the node's number, a part moved in by the part's id (`412.3`)."""

    thread: Thread
    members: list[Joined] = []


class StandInThreads(MutableModel, ThreadSource, arbitrary_types_allowed=True):
    """The demo's threads, read as the host reads its own (`Readings`) over the demo's items, its review marks and who goes on; their statuses and their checks' answers kept in memory, as the operator changes them."""

    threads: list[StoodIn]
    checks: list[Check] = []
    statuses: dict[int, Stated] = {}
    """Each thread's latest status, by its number, where one was said."""
    answers: dict[int, Answered] = {}
    """Each check's answer, by its number, once the operator gave one."""
    every: Callable[[], list[Item]]
    """The demo's items, as they stand."""
    pathed: Callable[[], list[Pathed]]
    """Each conversation the demo lists, with their path."""
    ended: Callable[[], list[Conversation]]
    """The conversations that have ended, who hold nothing."""
    marks: MarkStore
    working: list[Working] = []
    """Where each conversation going on works."""

    @override
    def items(self) -> Mapping[int, Item]:
        return {each.number: each for each in self.every()}

    @override
    def beside(self, thread: Thread, *, moved: bool) -> Beside:
        return Beside(
            mark=self.marks.of(thread.repository, CORE, on_node(thread.number)),
            answering=self.answering(thread),
            unanswered=self.unanswered(thread) if moved else [],
        )

    @override
    def paths(self, conversations: Sequence[Conversation]) -> list[Pathed]:
        known = {each.conversation: each for each in self.pathed()}
        return [known[each] for each in dict.fromkeys(conversations) if each in known]

    def answering(self, thread: Thread) -> Conversation | None:
        """Return who answers for `thread`: its holder where they go on, else the holder of the nearest thread above it who does."""
        by_number = {each.thread.number: each.thread for each in self.threads}
        ended = self.ended()
        at: Thread | None = thread
        while at is not None:
            if at.holder is not None and at.holder not in ended:
                return at.holder
            at = None if at.parent is None else by_number.get(at.parent)
        return None

    def unanswered(self, thread: Thread) -> list[Spot]:
        """Return the parts of the operator's words moved into `thread` that nothing in it answers yet: an item there citing the part, or answering the item it's of."""
        stood = self.stood(thread.number)
        items = self.items()
        members = [items[each.node] for each in stood.members if each.node in items]

        def answered(part: Joined) -> bool:
            return any(
                any(
                    cited.item == part.node and cited.part == part.part
                    for cited in item.citations
                )
                or (
                    isinstance(item.reason, Message)
                    and part.node in item.reason.answers
                )
                for item in members
                if item.made >= part.came
            )

        return [
            Spot(node=each.node, part=each.part)
            for each in stood.members
            if each.part is not None and not answered(each)
        ]

    def stood(self, number: int) -> StoodIn:
        """Return stand-in thread `number`; say where there's none."""
        found = next(
            (each for each in self.threads if each.thread.number == number), None
        )
        if found is None:
            message = f"the demo has no thread @{number}"
            raise KeyError(message)
        return found

    def readings(self) -> Readings:
        """Return the threads as the host reads them for the review, over the demo's stand-ins."""
        items = self.items()
        members = {
            each.thread.number: [
                member
                for member in each.members
                if member.part is not None
                or member.node in items
                or any(check.number == member.node for check in self.checks)
            ]
            for each in self.threads
        }
        return Readings(
            source=self,
            ledgered=Ledgered(
                threads={each.thread.number: each.thread for each in self.threads},
                members={
                    number: listed for number, listed in members.items() if listed
                },
                statuses=self.statuses,
                checks={each.number: each for each in self.checks},
                answers=self.answers,
                references={},
            ),
            working=self.working,
        )

    def listed(self) -> ThreadsRead:
        """List every thread as the review reads it."""
        return self.readings().listed()

    def shown(self, number: int, *, whole: bool) -> ThreadShown:
        """Read thread `number`'s conversation, from where the operator last read it, or `whole`."""
        self.stood(number)
        return self.readings().shown(number, whole=whole)

    def stated(self, number: int, status: Stated) -> ThreadStated:
        """Say `status` of thread `number`, the operator's, and return the thread as it stands."""
        self.stood(number)
        self.statuses = {**self.statuses, number: status}
        read = self.readings().read(number)
        answering = [] if read.answering is None else [read.answering]
        return ThreadStated(read=read, paths=self.paths(answering))

    def settled(self, number: int, at: datetime) -> ThreadStated:
        """Settle thread `number`, as the operator does."""
        thread = self.stood(number).thread
        return self.stated(
            number,
            Settled(target=number, repository=thread.repository, by=Operator(), at=at),
        )

    def declined(self, number: int, why: str, at: datetime) -> ThreadStated:
        """Decline thread `number`, as the operator does, saying why."""
        thread = self.stood(number).thread
        return self.stated(
            number,
            Declined(
                target=number,
                repository=thread.repository,
                by=Operator(),
                at=at,
                why=why,
            ),
        )

    def reopened(self, number: int, why: str, at: datetime) -> ThreadStated:
        """Reopen thread `number`, as the operator does, saying why: back to whoever held it."""
        thread = self.stood(number).thread
        return self.stated(
            number,
            Reopened(
                target=number,
                repository=thread.repository,
                by=Operator(),
                at=at,
                why=why,
            ),
        )

    def checked(self, number: int, text: str, at: datetime) -> Check:
        """Answer check `number` with what the operator saw, or a tick; say where there's none."""
        check = next((each for each in self.checks if each.number == number), None)
        if check is None:
            message = f"the demo has no check @{number}"
            raise KeyError(message)
        self.answers = {
            **self.answers,
            number: Answered(
                target=number,
                repository=check.repository,
                by=Operator(),
                at=at,
                text=text,
            ),
        }
        return check

    def containing(self, number: int) -> Thread | None:
        """Return the thread node `number` is in; none where it's in none."""
        return next(
            (
                each.thread
                for each in self.threads
                if any(member.node == number for member in each.members)
            ),
            None,
        )

    def replied(self, numbers: Sequence[int], at: datetime) -> None:
        """Reopen each thread done, to confirm, holding one of the items `numbers`, which the operator replied to, as the host does (`Delivery.reopening`)."""
        for each in self.threads:
            number = each.thread.number
            status = self.statuses.get(number)
            if status is None or status.kind != "ledger:done":
                continue
            if any(
                member.node in numbers and member.part is None
                for member in each.members
            ):
                self.reopened(number, "the operator replied there", at)
