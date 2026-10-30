"""Past conversations made threads: what each session and their subagents sent the operator before threads, put in that session's root, once; and the check of it the operator runs on the host.

`docs/inbox.md`, *Threads*. Everything a conversation sends the operator lands
in a thread (`Concerns.landed`); what was sent before threads were is in none,
and the review, grouped by thread, would show it nowhere. So as the host
service opens the inbox it puts each such item, a conversation's to the
operator, the operator's copy of a message between agents among them, in its
session's root thread (`rooted`): their own, where they have one, its status
left as it stands; else one opened for them, named as `Concerns.root` names a
root, from the session's name, `-2` where that's taken, held by them as a root
is and kept as their root on their whereabouts, so they go on there. A
subagent's items go to their session's root too, as a subagent starts on their
parent's thread and lands there unless they open another.

A root opened for a past conversation is settled, by lup, saying why
(`CONVERTED`): its act, never put in the operator's name; unless something in
it still waits on them, or its session goes on: one that
asks them stays open, and so does one whose session is still at work, whose
next items land there. A later session taking its name takes it reopened
(`Concerns.took`). Nobody is told: what's put there is past.

It runs at each start, and does something only where an item lies outside
every thread: the first time, every item from before threads; after, none, but
what an earlier lup run meanwhile made. Each item keeps its number, its fields
and where it stands, `In` edges drawn by lup alone.
"""

import time
from typing import TYPE_CHECKING, Literal

from lup.types import Model
from lup_dev.clock import SystemClock
from lup_dev.host.names import Names, shaped
from lup_dev.inbox.concerns import ROOT, Concerns
from lup_dev.inbox.conversion import Differs
from lup_dev.inbox.roster import Roster
from lup_dev.inbox.store import KINDS, Inbox, Item, cited
from lup_dev.inbox.threaded import Readings
from lup_dev.listing import many
from lup_ledger.environment.store import Ledger
from lup_ledger.parties import Conversation, Lup, Operator
from lup_ledger.threads import In, Settled, Thread

if TYPE_CHECKING:
    from lup_dev.layout import Layout
    from lup_ledger.environment.layout import LedgerLayout


CONVERTED = "nothing waited when threads came: converted"
"""Why lup settles a root it opens for a past conversation."""


def loose(inbox: Inbox) -> list[Item]:
    """Return the items that land in a thread and lie in none, by number: a conversation's to the operator, the operator's copy of a message between agents among them."""
    placed = {each.source: each for each in inbox.ledger.drawn_of(In)}
    return sorted(
        (
            each
            for each in inbox.items.values()
            if isinstance(each.sender, Conversation)
            and each.recipient == Operator()
            and each.number not in placed
        ),
        key=lambda each: each.number,
    )


class Rooted(Model):
    """What putting past conversations in threads did: how many of each."""

    sessions: int
    opened: int
    """Roots opened for a session that had none."""
    items: int
    settled: int
    """Roots opened and settled: nothing in them waits, and their session has
    ended."""
    waiting: int
    """Roots opened and left open, something in them waiting on the operator."""
    going_on: int
    """Roots opened and left open, their session still at work."""

    def said(self) -> str:
        """Say it in a line, as the host service tells the operator.

        >>> print(Rooted(sessions=3, opened=2, items=40, settled=1, waiting=1, going_on=0).said())
        40 items of 3 sessions in their roots, 2 opened: 1 settled, 1 left open as something in it waits on you
        """
        open_ = [
            *(
                [f"{self.waiting} left open as something in it waits on you"]
                if self.waiting
                else []
            ),
            *(
                [f"{self.going_on} left open as its session goes on"]
                if self.going_on
                else []
            ),
        ]
        return (
            f"{many(self.items, 'item')} of {many(self.sessions, 'session')} in "
            f"their roots, {self.opened} opened: "
            + ", ".join([f"{self.settled} settled", *open_])
        )


def rooted(concerns: Concerns) -> Rooted | None:
    """Put each item that lands in a thread and lies in none in its session's root, in one transaction: their own, or one opened for them, settled by lup unless something in it waits on the operator or the session goes on; and say what it did. None where no item lies outside every thread.

    Raise `InboxError` where the ledger refuses a thread or an edge, keeping
    none of it.
    """
    found = loose(concerns.inbox)
    if not found:
        return None
    ledger = concerns.inbox.ledger

    def session(item: Item) -> Conversation | None:
        return item.sender.main() if isinstance(item.sender, Conversation) else None

    mains = [main for each in found if (main := session(each)) is not None]
    sessions = {
        main: [each for each in found if session(each) == main]
        for main in dict.fromkeys(mains)
    }

    def root(main: Conversation) -> Thread | None:
        place = concerns.inbox.whereabouts.get(main.key())
        kept = None if place is None or place.root is None else ledger.found(place.root)
        return kept if isinstance(kept, Thread) else None

    def opened(main: Conversation) -> Thread:
        own = concerns.roster.own(main) or main.session
        lettered = any(each.isalpha() for each in own)
        name = shaped(own if lettered else f"session-{own}") or "session"
        thread = concerns.kept(
            Thread(
                number=ledger.numbered(),
                repository=main.repository,
                by=Lup(),
                at=concerns.now(),
                name=concerns.free(main.repository, name, but=main),
                title=ROOT,
                holder=main,
            ),
            but=main,
        )
        concerns.placed(main, root=thread.number)
        return thread

    def left(main: Conversation, thread: Thread) -> Leaving:
        if concerns.standing(thread).waiting:
            return "waiting"
        if concerns.live(main):
            return "going on"
        concerns.drawn(
            Settled(
                target=thread.number,
                repository=thread.repository,
                by=Lup(),
                at=concerns.now(),
                why=CONVERTED,
            )
        )
        return "settled"

    def put(main: Conversation, items: list[Item]) -> Leaving | None:
        kept = root(main)
        thread = kept if kept is not None else opened(main)
        for item in items:
            concerns.drawn(
                In(
                    source=item.number,
                    target=thread.number,
                    repository=thread.repository,
                    by=Lup(),
                    at=concerns.now(),
                )
            )
        return None if kept is not None else left(main, thread)

    with ledger.writing():
        outcomes = [put(main, items) for main, items in sessions.items()]
    return Rooted(
        sessions=len(sessions),
        opened=len([each for each in outcomes if each is not None]),
        items=len(found),
        settled=outcomes.count("settled"),
        waiting=outcomes.count("waiting"),
        going_on=outcomes.count("going on"),
    )


type Leaving = Literal["settled", "waiting", "going on"]
"""How a root opened for a past conversation is left: settled; open, as
something in it waits on the operator; or open, as its session goes on."""


def concerned(inbox: Inbox, layout: Layout) -> Concerns:
    """Return the threads of `inbox` as the host service reads them at its start: its conversations named by the sessions' names lup keeps in its state at `layout`, a launch served while its record is there."""
    return Concerns(
        inbox=inbox,
        roster=Roster(
            names=Names(path=layout.host.names).all(),
            places=inbox.whereabouts,
            items=inbox.items,
            version=inbox.version,
        ),
        clock=SystemClock(),
        served=lambda launch: layout.host.record(launch).is_file(),
    )


class RootedRehearsal(Model):
    """What a check of putting past conversations in threads found: what it did, how long it took, and what differs."""

    rooted: Rooted | None
    """None where no item lay outside every thread: put there already."""
    conversion: float
    """Putting them there, on a snapshot of the ledger, in seconds."""
    threads: int
    """The threads on the ledger after."""
    listed: float
    """Reading every thread as the review does after, in seconds: what the
    page's watch asks once the ledger changed (`inbox-threads`)."""
    largest: int
    """How much the thread with the most in it holds."""
    shown: float
    """Reading that thread's conversation whole, in seconds (`inbox-thread`)."""
    differs: list[Differs]

    def said(self) -> list[str]:
        """Say it, a line each: counts, times and what differs by item or thread number and field, never what an item says."""
        did = (
            "No item lies outside every thread: every one is in one already."
            if self.rooted is None
            else f"Put them in threads in {self.conversion:.2f}s: {self.rooted.said()}."
        )
        differs = (
            [
                (
                    "Every item is in a thread, in its session's root where it "
                    "was put there, each as it was; each root opened settled but "
                    "where something waits or its session goes on."
                )
            ]
            if not self.differs
            else [
                f"{many(len(self.differs), 'difference')}:",
                *(f"  {each.of}: {each.field}" for each in self.differs),
            ]
        )
        return [
            did,
            (
                f"{many(self.threads, 'thread')} on the ledger after, read as the "
                f"review reads them in {self.listed:.2f}s; the largest, of "
                f"{self.largest}, read whole in {self.shown:.2f}s."
            ),
            *differs,
        ]


def rooted_compared(
    before: Inbox, concerns: Concerns, put: list[Item]
) -> list[Differs]:
    """Return what differs from what putting past conversations in threads should leave, `before` the inbox as it stood, `put` the items it put there: an item still in no thread, one of `put` not in its session's root, an item changed, and a root it opened settled with something in it waiting on the operator."""
    after = Inbox.opened(concerns.inbox.ledger)

    def changed(item: Item) -> list[Differs]:
        found = after.items.get(item.number)
        if found is None:
            return [Differs(of=cited(item.number), field="missing")]
        return [
            Differs(of=cited(item.number), field=field)
            for field in Item.model_fields
            if getattr(found, field) != getattr(item, field)
        ]

    def placed(item: Item) -> list[Differs]:
        thread = concerns.containing(item.number)
        sender = item.sender
        if (
            thread is None
            or not isinstance(sender, Conversation)
            or thread.parent is not None
            or thread.holder != sender.main()
        ):
            return [Differs(of=cited(item.number), field="not in its session's root")]
        return []

    roots = {
        thread.number: thread
        for each in put
        if (thread := concerns.containing(each.number)) is not None
    }
    settled = [
        Differs(
            of=cited(number),
            field="settled, with something in it waiting on the operator",
        )
        for number, thread in roots.items()
        if (standing := concerns.standing(thread)).state == "settled"
        and standing.waiting
    ]
    return [
        *(
            Differs(of=cited(each.number), field="in no thread")
            for each in loose(after)
        ),
        *(each for item in put for each in placed(item)),
        *(each for item in before.items.values() for each in changed(item)),
        *settled,
    ]


def rooted_rehearsed(layout: Layout, live: LedgerLayout) -> RootedRehearsal:
    """Put past conversations in threads on the ledger at `live`, a snapshot of the one lup's state at `layout` keeps, and compare what it left with what it should; the sessions named as lup's state names them.

    Raise `InboxError` where the snapshot doesn't read.
    """
    ledger = Ledger.opened(live, KINDS)
    try:
        before = Inbox.opened(ledger)
        put = loose(before)
        concerns = concerned(before, layout)
        started = time.perf_counter()
        done = rooted(concerns)
        converting = time.perf_counter() - started
        started = time.perf_counter()
        readings = Readings.of(concerns)
        listed = readings.listed()
        listing = time.perf_counter() - started
        largest = max(listed.threads, key=lambda each: each.members, default=None)
        started = time.perf_counter()
        if largest is not None:
            readings.shown(largest.thread.number, whole=True)
        showing = time.perf_counter() - started
        return RootedRehearsal(
            rooted=done,
            conversion=converting,
            threads=len(listed.threads),
            listed=listing,
            largest=0 if largest is None else largest.members,
            shown=showing,
            differs=rooted_compared(before, concerns, put),
        )
    finally:
        ledger.close()
