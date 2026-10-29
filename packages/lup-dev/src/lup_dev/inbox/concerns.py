"""Threads as agents work in them: where each works, what lands where, and who's told.

`docs/inbox.md`, *Threads*. A thread is a concern, kept on the ledger
(`lup_ledger.threads`): this is the inbox's side of it.
- **Where an agent works** (`working`) is the thread what they send lands in
  where they name none: the one they started on, until they join, hold or are
  handed another. A subagent starts on their parent's; a session's own
  conversation on a root thread of their own, top-level in the repository,
  held by them and named as they are (`root`). It's opened at the session's
  first need of one, or taken where a root nobody holds has their name, so a
  session called as an earlier one goes on with what that one left.
- **What lands in a thread** (`landed`) is what a conversation sends the
  operator, the operator's copy of a message between agents among it: in the
  thread its call named, or where they work; `how_it_felt` where they
  started. Where it names another thread with `@`, a reference is drawn to
  that one (`Refers`), so it shows there as a line.
- **Who's told** (`telling`), through lup's words left for a conversation,
  told at their next call, their turn's or their session's start, never
  holding an end or waking them: whoever answers for the thread, its holder
  or else the holder of the nearest thread above, each item whole; everyone
  else on it, one line. A subagent's items are told to none of the
  conversations above them (`forebears`), who hear them through their
  runtime already, and whose context is what threads are meant to spare. How it felt is told to nobody, as it reaches the
  operator alone, nor a flag or a hold, the judge's, which its writer hears.
- **A holder that has ended holds nothing** (`live`): a subagent ended, a
  session cleared in their launch, or one whose launch has ended. It's read at
  each read rather than written as they end, so a session resumed under the
  same ids holds their threads again.

What an agent says of a thread besides sending into it is the `thread` tool's
(`inbox/tools.py`): open, join, hold, hand, move into, park, say done. Settling,
declining and reopening are the operator's (`settled`, `declined`,
`reopened`), and so is answering a check (`checked`).
"""

import textwrap
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from lup.types import Model
from lup_dev.clock import Clock
from lup_dev.host.names import shaped
from lup_dev.inbox.mentions import mentioned
from lup_dev.inbox.parts import PartId
from lup_dev.inbox.roster import Roster
from lup_dev.inbox.store import (
    Flagged,
    HeldChange,
    HowItFelt,
    Inbox,
    InboxError,
    Item,
    Message,
    after,
    cited,
)
from lup_dev.inbox.tags import Tag
from lup_dev.inbox.texts import body, kind, opening, what, written
from lup_dev.inbox.threads import cue, parts_of, spoken
from lup_ledger.environment.threads import Threads
from lup_ledger.errors import LupLedgerError
from lup_ledger.parties import Conversation, Operator
from lup_ledger.records import Edge
from lup_ledger.threads import (
    Answered,
    BranchLanded,
    Check,
    CommitLanded,
    ConditionHeld,
    ConversationEnded,
    Declined,
    Done,
    In,
    IssueClosed,
    Moved,
    Parked,
    Refers,
    Reopened,
    Settled,
    Standing,
    Thread,
    TimeCame,
    Trigger,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from lup_ledger.parties import Party
    from lup_ledger.records import Node

ROOT = "a main session's root thread"
"""What every root thread is titled: what it holds is whatever its session is given."""

type Telling = Literal["whole", "line", "none"]
"""How an item landing in a thread is told: whole, in a line, or not at all."""


class Reach(Model):
    """How an item landing in a thread is told to whoever answers for it, and to everyone else on it."""

    holder: Telling
    others: Telling


def told(item: Item) -> Reach:
    """Say how `item`, landing in a thread, is told to whoever answers for it, then to everyone else on it.

    How it felt reaches the operator alone, so nobody. A flag or a hold is the
    judge's, the operator's to answer, and its writer is told of it already:
    nobody else, since a worker's writes would each make a line for whoever
    leads its thread. A turn's last words are its sender's answer to the
    operator: told whole to the holder, and to nobody else, since each turn
    makes one.

    >>> from datetime import UTC, datetime
    >>> made = datetime(2026, 1, 1, tzinfo=UTC)
    >>> told(Item(number=7, reason=Message(kind="note", text="x"), sender=Operator(), recipient=Operator(), made=made))
    Reach(holder='whole', others='line')
    """
    match item.reason:
        case HowItFelt() | Flagged() | HeldChange():
            return Reach(holder="none", others="none")
        case Message(ending=True):
            return Reach(holder="whole", others="none")
        case _:
            return Reach(holder="whole", others="line")


def slugged(title: str, longest: int = 40) -> str:
    """Return a thread's name made from its `title`: shortened to `longest` characters at a word's end, lowercase, each run of what a name can't hold a `-`; `thread` where that leaves no letter.

    >>> slugged("The cursor jumps when typing fast in a long comment")
    'the-cursor-jumps-when-typing-fast-in-a'
    >>> slugged("#316")
    'thread-316'
    """
    short = textwrap.shorten(title, width=longest, placeholder="")
    made = shaped(short) or ""
    lettered = any(each.isalpha() for each in made)
    return made if lettered else "-".join(each for each in ["thread", made] if each)


def triggers(until: list[Trigger]) -> str:
    """Say what a parked thread waits for, in prose: the first of them to come.

    >>> from lup_ledger.threads import BranchLanded, IssueClosed
    >>> triggers([IssueClosed(issue=12), BranchLanded(branch="feat")])
    'issue #12 closing, or `feat` landing'
    """

    def said(each: Trigger) -> str:
        match each:
            case IssueClosed(issue=str() as issue):
                return f"issue {issue} closing"
            case IssueClosed(issue=issue):
                return f"issue #{issue} closing"
            case BranchLanded(branch=branch):
                return f"`{branch}` landing"
            case CommitLanded(commit=commit):
                return f"commit {commit} landing"
            case ConversationEnded():
                return "a conversation ending"
            case TimeCame(at=at):
                return f"{at:%Y-%m-%d %H:%M %Z}"
            case ConditionHeld(when=when):
                return f"`{when}` holding"

    return ", or ".join(said(each) for each in until)


class Concerns(Model, arbitrary_types_allowed=True):
    """The threads of the inbox's repositories, as agents work in them and are told of them; made from the inbox as it stands (`Delivery.concerns`)."""

    inbox: Inbox
    roster: Roster
    clock: Clock
    served: Callable[[str], bool] = lambda _: True
    """Says whether a launch, by its id, is still served: one that has ended
    leaves its conversations holding nothing."""
    whole_up_to: int = 4000
    """The most an item landing in a thread is told whole to its holder, in
    bytes of UTF-8: past it, they're told a line saying how to read it, since
    what's told beside a call shares one hook's answer."""

    @property
    def threads(self) -> Threads:
        """The threads on the inbox's ledger."""
        return Threads(ledger=self.inbox.ledger)

    def now(self, earlier: datetime | None = None) -> datetime:
        """Return the time a record is written at: the clock's, or just after `earlier`, a node's version before, where the clock reads no later."""
        now = self.clock.now()
        return now if earlier is None else max(now, after(earlier))

    def live(self, conversation: Conversation) -> bool:
        """Say whether `conversation` goes on, holding what they hold: heard, not ended, the latest of their session's launch where they're its own, and that launch still served (`Inbox.live`)."""
        place = self.inbox.whereabouts.get(conversation.key())
        return (
            place is not None
            and self.inbox.live(conversation)
            and self.served(place.launch)
        )

    def thread(self, number: int) -> Thread:
        """Return thread `number`, or say there's none."""
        try:
            return self.threads.thread(number)
        except LupLedgerError as missing:
            raise InboxError(str(missing)) from missing

    def found(self, repository: Path, said: str) -> Node | None:
        """Return the node of `repository` that `said` names, as `@` takes it: a thread's or another node's name, or a number; none where none is."""
        try:
            return self.inbox.ledger.cited(repository, said)
        except LupLedgerError:
            return None

    def named(self, repository: Path, said: str) -> Thread:
        """Return the thread of `repository` that `said` names, by its name or its number, `@` before either or not; say where it names none, or something else."""
        found = self.found(repository, said)
        match found:
            case Thread():
                return found
            case None:
                message = f"no thread of this repository is `{said}`"
            case _:
                message = f"`{said}` is a `{found.kind}`, not a thread"
        raise InboxError(message)

    def taken(self, repository: Path, but: Conversation | None = None) -> list[str]:
        """Return the names of `repository`'s agents that go on, a session's and a subagent's own, but `but`'s: those no thread there takes."""
        return [
            name
            for place in self.inbox.whereabouts.values()
            if place.conversation.repository == repository
            and place.conversation != but
            and self.live(place.conversation)
            and (name := self.roster.own(place.conversation)) is not None
        ]

    def free(
        self, repository: Path, wanted: str, but: Conversation | None = None
    ) -> str:
        """Return `wanted` where no node or agent of `repository` has it, but `but`, else the first of `wanted-2`, `wanted-3`… that's free."""
        taken = self.taken(repository, but)

        def held(name: str) -> bool:
            return (
                name in taken or self.inbox.ledger.named(repository, name) is not None
            )

        if not held(wanted):
            return wanted
        number = 2
        while held(f"{wanted}-{number}"):
            number += 1
        return f"{wanted}-{number}"

    def kept(self, thread: Thread, but: Conversation | None = None) -> Thread:
        """Keep `thread` on the ledger, its name refused where an agent of its repository has it, but `but`; say why where the ledger refuses it."""
        try:
            return self.inbox.ledger.kept(thread, self.taken(thread.repository, but))
        except LupLedgerError as refused:
            raise InboxError(str(refused)) from refused

    def drawn[
        E: In
        | Moved
        | Refers
        | Answered
        | Parked
        | Done
        | Settled
        | Declined
        | Reopened
    ](self, edge: E) -> E:
        """Draw `edge` on the ledger; say why where the ledger refuses it."""
        try:
            return self.inbox.ledger.drawn(edge)
        except LupLedgerError as refused:
            raise InboxError(str(refused)) from refused

    def placed(self, party: Conversation, **fields: int | None) -> None:
        """Keep `fields` on `party`'s whereabouts: where they work, started, or their root; nothing where they were never heard."""
        place = self.inbox.whereabouts.get(party.key())
        if place is None:
            return
        self.inbox.placed(place.model_copy(update=fields))

    def left(self, party: Conversation, words: str) -> None:
        """Leave lup's `words` for `party`, told at their next call, their turn's or their session's start, never holding an end nor waking them; nothing where they were never heard, or have ended."""
        place = self.inbox.whereabouts.get(party.key())
        if place is None or not self.live(party):
            return
        self.inbox.placed(place.model_copy(update={"words": [*place.words, words]}))

    def root(self, main: Conversation) -> Thread:
        """Return the root thread of `main`, a session's own conversation: theirs where they have one; else the root nobody holds that has their name, which they take; else one opened, named as they are.

        A name another node holds already gives the root the first of
        `<name>-2`, `<name>-3`… that's free.
        """
        place = self.inbox.whereabouts.get(main.key())
        if place is not None and place.root is not None:
            kept = self.inbox.ledger.found(place.root)
            if isinstance(kept, Thread):
                return kept
        own = self.roster.own(main) or main.session
        lettered = any(each.isalpha() for each in own)
        name = shaped(own if lettered else f"session-{own}") or "session"
        taken = self.takeable(main.repository, name, main)
        if taken is not None:
            return self.took(main, taken)
        thread = self.kept(
            Thread(
                number=self.inbox.ledger.numbered(),
                repository=main.repository,
                by=main,
                at=self.now(),
                name=self.free(main.repository, name, but=main),
                title=ROOT,
                holder=main,
            ),
            but=main,
        )
        self.placed(main, root=thread.number)
        return thread

    def takeable(
        self, repository: Path, name: str, main: Conversation | None = None
    ) -> Thread | None:
        """Return the root thread of `repository` named `name` that a session taking the name takes as theirs: one at the top that nobody holds, or `main` does; none where there's none."""
        found = self.inbox.ledger.named(repository, name)
        match found:
            case Thread(parent=None, holder=holder) if (
                holder is None or holder == main or not self.live(holder)
            ):
                return found
            case _:
                return None

    def took(self, main: Conversation, root: Thread) -> Thread:
        """Make `root` the root thread of `main`, held by them, and return it."""
        held = (
            root
            if root.holder == main
            else self.kept(
                root.model_copy(update={"holder": main, "at": self.now(root.at)}),
                but=main,
            )
        )
        self.placed(main, root=held.number)
        return held

    def working(self, party: Conversation) -> Thread:
        """Return the thread `party` works in: the one they joined, hold or were handed, else the one they started on, their session's root where that's where they are."""
        place = self.inbox.whereabouts.get(party.key())
        number = None if place is None else place.thread
        found = None if number is None else self.inbox.ledger.found(number)
        return found if isinstance(found, Thread) else self.root(party.main())

    def started_on(self, party: Conversation) -> Thread:
        """Return the thread `party` started on: their parent's, for a subagent; their session's root else."""
        place = self.inbox.whereabouts.get(party.key())
        number = None if place is None else place.started
        found = None if number is None else self.inbox.ledger.found(number)
        return found if isinstance(found, Thread) else self.root(party.main())

    def opened(
        self, party: Conversation, title: str, under: Thread, name: str | None = None
    ) -> Thread:
        """Open a thread titled `title` under `under`, by `party`, held by nobody: named `name`, else after its title (`slugged`), made free where it's taken (`free`)."""
        wanted = slugged(title) if name is None else name
        return self.kept(
            Thread(
                number=self.inbox.ledger.numbered(),
                repository=party.repository,
                by=party,
                at=self.now(),
                name=wanted
                if name is not None
                else self.free(party.repository, wanted),
                title=title,
                parent=under.number,
            )
        )

    def addressed(self, party: Conversation, said: str | None) -> Thread | None:
        """Return the thread a call's `thread=` names: an existing thread of `party`'s repository, by its name or number; else one it opens, titled `said`, under where `party` works. None where it names none.

        Say where it's a number, or names a node that isn't a thread.
        """
        if said is None or not said.strip():
            return None
        found = self.found(party.repository, said)
        match found:
            case Thread():
                return found
            case None if not said.removeprefix("@").isdigit():
                return self.opened(party, said.strip(), self.working(party))
            case _:
                return self.named(party.repository, said)

    def landed(self, item: Item, thread: Thread | None = None) -> Thread:
        """Put `item`, a conversation's to the operator, in `thread`, else where its sender works, or how it felt where they started; draw a reference to each other thread it names with `@`; and tell whoever answers for the thread and everyone on it (`told`). Return the thread.

        Whoever already has it isn't told: its sender; the conversations
        above a subagent sending it, who hear them through their runtime
        (`forebears`); and for the operator's copy of a message between agents,
        the agent it went to.
        """
        sender = item.sender
        if not isinstance(sender, Conversation):
            message = (
                f"{cited(item.number)} is the operator's: it lands where they write it"
            )
            raise InboxError(message)
        landing = thread or (
            self.started_on(sender)
            if isinstance(item.reason, HowItFelt)
            else self.working(sender)
        )
        self.drawn(
            In(
                source=item.number,
                target=landing.number,
                repository=landing.repository,
                by=sender,
                at=self.now(),
            )
        )
        if not isinstance(item.reason, HowItFelt):
            self.referred(item, landing)
        reach = told(item)
        self.telling(
            landing,
            [sender, *self.forebears(sender), *self.copied(item)],
            whole=self.whole(item, landing) if reach.holder == "whole" else None,
            line=self.line(item, landing),
            holder=reach.holder != "none",
            others=reach.others != "none",
        )
        return landing

    def copied(self, item: Item) -> list[Conversation]:
        """Return the agent a message between agents went to, where `item` is the operator's copy of it: they have its words already; none else."""
        match item.reason:
            case Message(to=Conversation() as to):
                return [to]
            case _:
                return []

    def forebears(self, party: Conversation) -> list[Conversation]:
        """Return the conversations above `party`: the one that spawned them, theirs, and so on up to their session's own; none for a session's own.

        They hear `party` through their runtime, `party`'s result and end, and
        through what `party` sends them, so what `party` sends the operator is
        told to none of them.
        """
        if party.agent is None:
            return []

        def above(each: Conversation, depth: int) -> list[Conversation]:
            place = self.inbox.whereabouts.get(each.key())
            parent = None if place is None else place.parent
            if parent is None or depth > len(self.inbox.whereabouts):
                return []
            return [parent, *above(parent, depth + 1)]

        return list(dict.fromkeys([*above(party, 0), party.main()]))

    def referred(self, item: Item, landing: Thread) -> list[Thread]:
        """Draw a reference from `item` to each thread other than `landing` its words name with `@`, once each, and return them."""
        named = [self.found(landing.repository, each) for each in mentioned(body(item))]
        threads = {
            each.number: each
            for each in named
            if isinstance(each, Thread) and each.number != landing.number
        }
        for each in threads.values():
            self.drawn(
                Refers(
                    source=item.number,
                    target=each.number,
                    repository=landing.repository,
                    by=item.sender,
                    at=self.now(),
                )
            )
        return list(threads.values())

    def on(self, thread: Thread) -> list[Conversation]:
        """Return who's on `thread` and goes on: its holder, each conversation that wrote what's in it, and each that works in it."""
        standing = self.threads.standing(thread.number)
        working = [
            place.conversation
            for place in self.inbox.whereabouts.values()
            if place.conversation.repository == thread.repository
            and place.thread == thread.number
        ]
        return [
            each for each in dict.fromkeys([*standing.on, *working]) if self.live(each)
        ]

    def answering(self, thread: Thread) -> Conversation | None:
        """Return who answers for `thread`: its holder where they go on, else the holder of the nearest thread above it who does; none where nobody does."""
        return self.threads.answering(thread.number, live=self.live)

    def telling(
        self,
        thread: Thread,
        having: list[Conversation],
        *,
        whole: str | None,
        line: str,
        holder: bool = True,
        others: bool = True,
    ) -> None:
        """Tell who answers for `thread` `whole`, or `line` where it's none, where `holder` says; and everyone else on it `line`, where `others` says. Nobody among `having`, who has it already, is told."""
        answering = self.answering(thread)
        if holder and answering is not None and answering not in having:
            self.left(answering, whole or line)
        if not others:
            return
        for each in self.on(thread):
            if each != answering and each not in having:
                self.left(each, line)

    def whole(self, item: Item, thread: Thread, by: Conversation | None = None) -> str:
        """Tell `item`, in `thread`, whole, as a tag saying what it is and whom it's from, and who moved it there where `by` did; a line saying how to read it where it's longer than `whole_up_to`."""
        attributes = {
            "thread": thread.name,
            "item": str(item.number),
            "kind": kind(item),
            "from": self.roster.called(item.sender),
            **(
                {"to": self.roster.called(item.reason.to)}
                if isinstance(item.reason, Message) and item.reason.to
                else {}
            ),
            **({} if by is None else {"by": self.roster.called(by)}),
        }
        name = "landed" if by is None else "moved"
        said = Tag(name=name, attributes=attributes, parts=[written(item)]).written()
        if len(said.encode()) <= self.whole_up_to:
            return said
        return Tag(
            name=name,
            attributes={**attributes, "bytes": f"{len(said.encode()):,}"},
            parts=[
                f"Too long to tell here: `inbox` with `number` {item.number} reads it whole."
            ],
        ).written()

    def line(self, item: Item, thread: Thread, by: Conversation | None = None) -> str:
        """Tell `item`, in `thread`, in one line: what it is, from whom, and its first words; who moved it there where `by` did."""
        moved = "" if by is None else f", moved there by {self.roster.who(by)}"
        return (
            f"lup: in @{thread.name}, {what(item)} from {self.roster.who(item.sender)}, "
            f"{cited(item.number)}{moved}: {cue(opening(item))}"
        )

    def joined(self, party: Conversation, thread: Thread) -> None:
        """Make `thread` where `party` works: what they send lands there where they name none."""
        self.placed(party, thread=thread.number)

    def held(self, party: Conversation, thread: Thread) -> Thread:
        """Make `party` the holder of `thread`, and work there; whoever held it and goes on is told, in a line, that `party` took it. Return it as it stands."""
        before = thread.holder
        held = (
            thread
            if before == party
            else self.kept(
                thread.model_copy(update={"holder": party, "at": self.now(thread.at)})
            )
        )
        self.joined(party, held)
        if before is not None and before != party and self.live(before):
            self.left(
                before,
                f"lup: {self.roster.who(party)} took @{held.name}, which you held.",
            )
        return held

    def handed(self, party: Conversation, thread: Thread, to: Conversation) -> Thread:
        """Give `thread` to `to`, who holds it and works there from then on, told so in a line by `party`, who gave it. Return it as it stands."""
        held = (
            thread
            if thread.holder == to
            else self.kept(
                thread.model_copy(update={"holder": to, "at": self.now(thread.at)})
            )
        )
        self.joined(to, held)
        if to != party:
            self.left(
                to,
                f"lup: {self.roster.who(party)} handed you @{held.name}, "
                f'"{held.title}": you hold it, and what you send lands there.',
            )
        return held

    def moved(self, party: Conversation, thread: Thread, said: str) -> str:
        """Move what `said` names into `thread`, by `party`: an item of its repository by its number, or a part of the operator's words in one by its id; tell whoever answers for the thread whole, and everyone else on it in a line, as an item landing there is told (`told`), its sender among those who have it. Return its id, as cited.

        Say where it names nothing of the repository, a part of an agent's
        words, which moves with its item, or a thread.
        """
        bare = said.strip().removeprefix("@")
        if bare.isdigit():
            item = self.item(thread.repository, int(bare))
            self.drawn(
                In(
                    source=item.number,
                    target=thread.number,
                    repository=thread.repository,
                    by=party,
                    at=self.now(),
                )
            )
            reach = told(item)
            self.telling(
                thread,
                [party, item.sender]
                if isinstance(item.sender, Conversation)
                else [party],
                whole=self.whole(item, thread, by=party),
                line=self.line(item, thread, by=party),
                holder=reach.holder != "none",
                others=reach.others != "none",
            )
            return cited(item.number)
        try:
            wanted = PartId.parsed(bare)
        except ValueError as unread:
            message = f"`{said}` is neither an item's number (`2159`) nor a part's id (`2159.3`)"
            raise InboxError(message) from unread
        item = self.item(thread.repository, wanted.item)
        anchor = next((each for each in spoken(item) if each.id == wanted), None)
        if anchor is None:
            whose = (
                f"{what(item)} from {self.roster.who(item.sender)}, which moves whole: "
                f"`{wanted.item}`"
                if parts_of(item, body(item)) and item.sender != Operator()
                else "an item with no such part of the operator's words"
            )
            message = f"{wanted.cited()} isn't a part of the operator's words: {cited(wanted.item)} is {whose}"
            raise InboxError(message)
        self.drawn(
            Moved(
                source=item.number,
                part=wanted.part,
                target=thread.number,
                repository=thread.repository,
                by=party,
                at=self.now(),
            )
        )
        whole = Tag(
            name="moved",
            attributes={
                "thread": thread.name,
                "part": wanted.said(),
                "by": self.roster.called(party),
            },
            parts=[anchor.text],
        ).written()
        line = (
            f"lup: in @{thread.name}, the operator's words {wanted.cited()}, moved "
            f"there by {self.roster.who(party)}: {cue(anchor.text)}"
        )
        self.telling(thread, [party], whole=whole, line=line)
        return wanted.cited()

    def moved_parts(self, repository: Path) -> list[PartId]:
        """Return each part of the operator's words moved into a thread of `repository`, in the order first moved."""
        drawn = self.inbox.ledger.drawn_of(Moved)
        return list(
            dict.fromkeys(
                PartId(item=each.source, part=each.part)
                for each in drawn
                if each.repository == repository
            )
        )

    def item(self, repository: Path, number: int) -> Item:
        """Return item `number`, of `repository`; say where the inbox holds none, or it's another's."""
        found = self.inbox.items.get(number)
        if found is None or not found.of(repository):
            node = self.inbox.ledger.found(number)
            message = (
                f"{cited(number)} is a thread, which a thread holds by its `under`, not by moving it"
                if isinstance(node, Thread)
                else f"{cited(number)} isn't an item of this repository"
            )
            raise InboxError(message)
        return found

    def stated(
        self,
        thread: Thread,
        status: Parked | Done | Settled | Declined | Reopened,
        line: str,
        by: Party,
    ) -> Thread:
        """Draw `status` on `thread`, and tell whoever answers for it `line`, unless it's `by`, who said it. Return the thread."""
        self.drawn(status)
        answering = self.answering(thread)
        if answering is not None and answering != by:
            self.left(answering, line)
        return thread

    def parked(
        self, party: Conversation, thread: Thread, until: list[Trigger], why: str
    ) -> Thread:
        """Park `thread`, by `party`, until the first of `until` comes, saying `why`."""
        status = Parked(
            target=thread.number,
            repository=thread.repository,
            by=party,
            at=self.now(),
            until=until,
            why=why,
        )
        line = (
            f"lup: {self.roster.who(party)} parked @{thread.name} until "
            f"{triggers(until)}" + (f": {why}" if why else ".")
        )
        return self.stated(thread, status, line, party)

    def done(self, party: Conversation, thread: Thread, to_try: str) -> Thread:
        """Say `thread` is done, in `party`'s word, for the operator to confirm by trying `to_try`."""
        status = Done(
            target=thread.number,
            repository=thread.repository,
            by=party,
            at=self.now(),
            to_try=to_try,
        )
        line = (
            f"lup: {self.roster.who(party)} says @{thread.name} is done, for the "
            f"operator to try: {cue(to_try)}"
        )
        return self.stated(thread, status, line, party)

    def settled(self, thread: Thread) -> Thread:
        """Settle `thread`, as the operator does, telling whoever answers for it."""
        status = Settled(
            target=thread.number,
            repository=thread.repository,
            by=Operator(),
            at=self.now(),
        )
        line = f"lup: the operator settled @{thread.name}."
        return self.stated(thread, status, line, Operator())

    def declined(self, thread: Thread, why: str) -> Thread:
        """Decline `thread`, as the operator does, saying `why`, telling whoever answers for it."""
        status = Declined(
            target=thread.number,
            repository=thread.repository,
            by=Operator(),
            at=self.now(),
            why=why,
        )
        line = f"lup: the operator declined @{thread.name}" + (
            f": {why}" if why else "."
        )
        return self.stated(thread, status, line, Operator())

    def reopened(self, thread: Thread, why: str) -> Thread:
        """Reopen `thread`, as the operator does, saying `why`, telling whoever answers for it."""
        status = Reopened(
            target=thread.number,
            repository=thread.repository,
            by=Operator(),
            at=self.now(),
            why=why,
        )
        line = f"lup: the operator reopened @{thread.name}" + (
            f": {why}" if why else "."
        )
        return self.stated(thread, status, line, Operator())

    def checks(
        self, party: Conversation, thread: Thread, lines: list[str]
    ) -> list[Check]:
        """Put a check in `thread` for each of `lines`, by `party`: something only the operator can try, waiting on them until they answer it."""

        def checked(text: str) -> Check:
            check = self.inbox.ledger.kept(
                Check(
                    number=self.inbox.ledger.numbered(),
                    repository=thread.repository,
                    by=party,
                    at=self.now(),
                    text=text,
                )
            )
            self.drawn(
                In(
                    source=check.number,
                    target=thread.number,
                    repository=thread.repository,
                    by=party,
                    at=self.now(),
                )
            )
            return check

        return [checked(each) for each in lines if each.strip()]

    def check(self, number: int) -> Check | None:
        """Return check `number`; none where the ledger holds no check by that number."""
        found = self.inbox.ledger.found(number)
        return found if isinstance(found, Check) else None

    def containing(self, number: int) -> Thread | None:
        """Return the thread node `number` is in; none where it's in none."""
        drawn = self.inbox.ledger.drawn_from(number, In, current=True)
        found = None if not drawn else self.inbox.ledger.found(drawn[-1].target)
        return found if isinstance(found, Thread) else None

    def checked(self, number: int, text: str) -> Check:
        """Answer check `number`, as the operator does, with what they saw, or a tick where `text` is empty; tell whoever asked it, where they go on, else whoever answers for its thread.

        Say where it's no check, or one answered already.
        """
        check = self.check(number)
        if check is None:
            message = f"{cited(number)} isn't a check"
            raise InboxError(message)
        if not check.waiting(self.inbox.ledger.drawn_to(number, Edge)):
            message = f"{cited(number)} is answered already"
            raise InboxError(message)
        self.drawn(
            Answered(
                target=number,
                repository=check.repository,
                by=Operator(),
                at=self.now(),
                text=text,
            )
        )
        thread = self.containing(number)
        where = "" if thread is None else f" in @{thread.name}"
        said = Tag(
            name="checked",
            attributes={
                "item": str(number),
                **({} if thread is None else {"thread": thread.name}),
            },
            parts=[text or "Ticked: they saw what it says."],
        ).written()
        asker = check.by if isinstance(check.by, Conversation) else None
        whom = (
            asker
            if asker is not None and self.live(asker)
            else None
            if thread is None
            else self.answering(thread)
        )
        if whom is not None:
            self.left(
                whom,
                f"lup: the operator answered your check {cited(number)}{where}:\n{said}",
            )
        return check

    def standing(self, thread: Thread) -> Standing:
        """Return where `thread` stands (`Standing.read`)."""
        return self.threads.standing(thread.number)
