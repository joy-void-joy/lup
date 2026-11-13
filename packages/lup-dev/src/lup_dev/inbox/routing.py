"""Where what the operator sends with Space `s` goes, as their draft is sent.

`docs/dashboard.md`, *The keys*; `docs/inbox.md`, *Threads in the review*. Space
`s` on a thing in the review picks where it goes, and nothing moves until the
draft is sent (`Destination`, `Destined`, `lup_dev.inbox.store`):
- **a concern** goes to an agent, who holds it; under another concern, nested
  there; into a pile, nested in it; or to `No agent`, at the top, nobody
  holding it (`Concerns.given`);
- **an item** goes into a concern or a pile, which the review lays it out in
  rather than in its agent's group (`Concerns.into`);
- **what the operator wrote,** a comment, a message or a remark, goes to an
  agent, or to a concern, reaching whoever answers for it, as a message there
  quoting what it's on; written to a pile nobody answers for, it stays there as
  the operator's words, waking nobody, until someone takes the pile.

A pile is named by its title (`Destination.pile`): the concern of the thing's
repository at the top, nobody answering for it, titled so, opened as the draft
is sent where there's none, `Later` among them (`Concerns.pile`).

Every route is read before anything moves (`Routing.planned`), so a draft
refused moves nothing; then each concern moves, then each item, so what's
written on a concern given to an agent reaches them (`Routing.routed`).
"""

from pathlib import Path
from typing import TYPE_CHECKING

from lup.types import Model
from lup_dev.inbox.concerns import Concerns
from lup_dev.inbox.roster import Roster
from lup_dev.inbox.store import (
    Approval,
    Comment,
    HeldChange,
    Destination,
    Destined,
    Draft,
    InboxError,
    Item,
    Letter,
    Remark,
    cited,
)
from lup_dev.inbox.texts import body, what
from lup_dev.inbox.threads import located, parts_of
from lup_ledger.parties import Conversation
from lup_ledger.threads import Thread

if TYPE_CHECKING:
    from collections.abc import Iterator


def quoting(item: Item, comment: Comment) -> str:
    r"""Say the operator's comment on `item` as a message carries it elsewhere than to whoever sent it: on the part of `item` the passage starts in, by its id, the passage quoted under it, then the comment; on the item whole, by its number.

    >>> from datetime import UTC, datetime
    >>> from lup_dev.inbox.store import Message, Quote
    >>> from lup_ledger.parties import Operator
    >>> own = Item(number=7, reason=Message(kind="note", text="One.\n\nTwo."),
    ...     sender=Operator(), recipient=Operator(), made=datetime(2026, 1, 1, tzinfo=UTC))
    >>> print(quoting(own, Comment(item=7, quote=Quote(text="Two.", start=6, end=10), text="Or three.")))
    On @7.2:
    <BLANKLINE>
    > Two.
    <BLANKLINE>
    Or three.
    >>> print(quoting(own, Comment(item=7, text="All of it.")))
    On @7:
    <BLANKLINE>
    All of it.
    """
    if comment.quote is None:
        return f"On {cited(item.number)}:\n\n{comment.text}"
    text = body(item)
    part = located(parts_of(item, text), text, comment.quote)
    on = cited(item.number) if part is None else part.id.cited()
    return f"On {on}:\n\n{quoted(comment.quote.text)}\n\n{comment.text}"


def quoted(text: str) -> str:
    r"""Say `text` as a Markdown quote, each line of it.

    >>> print(quoted("One.\nTwo."))
    > One.
    > Two.
    """
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def repository_of(item: Item) -> Path | None:
    """Return the repository `item` is of: its conversations', or what an approval is about; none for one between the operator and themselves."""
    for party in (item.sender, item.recipient, item.addressed):
        if isinstance(party, Conversation):
            return party.repository
    return item.reason.repository if isinstance(item.reason, Approval) else None


class Bound(Model, arbitrary_types_allowed=True):
    """Where a thing goes, read against the ledger before anything moves: an agent going on, a concern, a pile of a repository by its title, or `No agent`, nobody."""

    to: Conversation | None = None
    thread: Thread | None = None
    pile: str | None = None
    repository: Path
    """The repository of what's sent, whose pile it is where it's one."""

    @property
    def nobody(self) -> bool:
        """Say whether it's `No agent`: nobody holding it, at the top."""
        return self.to is None and self.thread is None and self.pile is None


class ConcernRoute(Model, arbitrary_types_allowed=True):
    """A concern sent somewhere, and where."""

    thread: Thread
    to: Bound


class ItemRoute(Model, arbitrary_types_allowed=True):
    """An item sent into a concern or a pile, and which."""

    item: Item
    to: Bound


class WrittenRoute(Model, arbitrary_types_allowed=True):
    """What the operator wrote, sent to an agent, a concern or a pile, and what it's on, said as a message carries it there."""

    id: str
    text: str
    """Their words, after what they're on, quoted."""
    to: Bound


class Plan(Model):
    """What a draft sends somewhere, read before anything moves: each concern and item moved, and where, and each thing written that goes elsewhere than where it was written."""

    concerns: list[ConcernRoute] = []
    items: list[ItemRoute] = []
    written: list[WrittenRoute] = []

    @property
    def empty(self) -> bool:
        """Say whether it moves nothing and sends nothing written."""
        return not self.concerns and not self.items and not self.written


class Went(Model):
    """A concern or an item the operator's send moved, and where, as the reply says it: `to dev/parser`, `into @later`, `to No agent`."""

    thread: int | None = None
    """The concern moved, by number; none for an item."""
    item: int | None = None
    """The item moved, by number; none for a concern."""
    name: str = ""
    """The concern's name, where one moved."""
    into: int | None = None
    """The concern or pile it went into or under, by number; none where it went to an agent or to `No agent`."""
    to: str
    """Where it went, in a few words."""


class Split(Model):
    """A draft split where Ctrl+Enter sends one destination alone (`Routing.split`): what reaches it, sent; and the rest, kept drafted."""

    sending: Draft
    staying: Draft


class Routed(Model):
    """What moving a draft's routes did: each concern and item moved, and where, and the messages what was written there is sent as, each where it goes."""

    went: list[Went] = []
    letters: list[Letter] = []


def going(draft: Draft, comment: Comment) -> Destination | None:
    """Return where `comment` goes elsewhere than to whoever sent its item: where the operator sent it, else where they sent its item, since a comment goes with what it's on; none where it goes with the reply."""
    moved = next((each.to for each in draft.moves if each.item == comment.item), None)
    return comment.sent or moved


def unsent(draft: Draft) -> Draft:
    """Return `draft` without what it sends somewhere with Space `s`: each move, and each thing written going elsewhere than where it was written (`going`), which `Routing` takes."""
    return draft.model_copy(
        update={
            "comments": [each for each in draft.comments if going(draft, each) is None],
            "letters": [each for each in draft.letters if each.sent is None],
            "remarks": [each for each in draft.remarks if each.sent is None],
            "moves": [],
        }
    )


class Routing(Model, arbitrary_types_allowed=True):
    """Where what the operator sends with Space `s` goes, read and moved over the inbox's concerns."""

    concerns: Concerns
    roster: Roster

    def planned(self, draft: Draft) -> Plan:
        """Read where each thing `draft` sends somewhere goes, moving nothing; say where one can't go.

        Refused: a concern or an item lup doesn't keep; an agent lup's inbox
        has never heard of, or who has ended; an item or what's written sent to
        `No agent`, which they don't go to; an item sent to an agent; a
        concern or an item sent to one of another repository, or to one the
        operator cleared; an item sent into a concern or a pile holding it
        already; an approval or a held change sent into a concern someone
        answers for, which only the operator answers; a concern sent under
        itself, or under one nested under it.
        """
        concerns = [
            self.concerned(each.thread, each.to)
            for each in draft.moves
            if each.thread is not None
        ]
        items = [
            self.itemed(each.item, each.to)
            for each in draft.moves
            if each.item is not None
        ]
        written = [
            *(
                self.commented(each, sent)
                for each in draft.comments
                if (sent := going(draft, each)) is not None
            ),
            *(self.lettered(each) for each in draft.letters if each.sent is not None),
            *(self.remarked(each) for each in draft.remarks if each.sent is not None),
        ]
        return Plan(
            concerns=concerns,
            items=items,
            written=[each for each in written if each.text.strip()],
        )

    def concerned(self, number: int, to: Destination) -> ConcernRoute:
        """Return where concern `number` goes, sent to `to`; say where it can't (`nestable`)."""
        thread = self.concerns.thread(number)
        bound = self.bound(to, thread.repository)
        self.nestable(thread, bound)
        return ConcernRoute(thread=thread, to=bound)

    def itemed(self, number: int, to: Destination) -> ItemRoute:
        """Return where item `number` goes, sent to `to`: a concern or a pile of its repository; say where it's none of those, or no item lup keeps."""
        item = self.concerns.inbox.items.get(number)
        repository = None if item is None else repository_of(item)
        if item is None or repository is None:
            message = f"{cited(number)} isn't an item of a repository lup keeps"
            raise InboxError(message)
        bound = self.bound(to, repository)
        if bound.to is not None or bound.nobody:
            message = f"{cited(number)} goes into a concern or a pile, not to an agent"
            raise InboxError(message)
        there = bound.thread or (
            None if bound.pile is None else self.concerns.piled(repository, bound.pile)
        )
        if there is not None and self.concerns.holds(there, number):
            message = f"{cited(number)} is in @{there.name} already"
            raise InboxError(message)
        if (
            isinstance(item.reason, Approval | HeldChange)
            and there is not None
            and self.concerns.answering(there) is not None
        ):
            message = f"{cited(number)} is {what(item)}, which only the operator answers: it goes into a pile nobody answers for, not into @{there.name}"
            raise InboxError(message)
        return ItemRoute(item=item, to=bound)

    def bound(self, destination: Destination, repository: Path) -> Bound:
        """Read `destination` for what's sent from `repository`: an agent heard and going on; a concern of that repository; a pile of it by its title; or `No agent`. Say where it's none of those."""
        if destination.to is not None:
            to = destination.to
            if to.key() not in self.concerns.inbox.whereabouts:
                message = f"{self.roster.who(to)} of {to.repository} isn't an agent lup's inbox has heard of: send it to one the dashboard shows running"
                raise InboxError(message)
            if not self.concerns.live(to):
                message = f"{self.roster.who(to)} has ended: send it to an agent running, a concern or a pile"
                raise InboxError(message)
            return Bound(to=to, repository=repository)
        if destination.thread is not None:
            thread = self.concerns.thread(destination.thread)
            if thread.repository != repository:
                message = f"@{thread.name} is of {thread.repository}, and what's sent there of {repository}"
                raise InboxError(message)
            cleared = self.concerns.standing(thread).marks.operator
            if cleared is not None:
                message = f"@{thread.name} is {cleared.stands}: reopen it, or send it elsewhere"
                raise InboxError(message)
            return Bound(thread=thread, repository=repository)
        if destination.pile is not None:
            return Bound(pile=destination.pile.strip(), repository=repository)
        return Bound(repository=repository)

    def nestable(self, thread: Thread, bound: Bound) -> None:
        """Say where `thread` can't go to `bound`: an agent of another repository, or a concern it would be under itself under."""
        if bound.to is not None and bound.to.repository != thread.repository:
            message = f"@{thread.name} is of {thread.repository}, and {self.roster.who(bound.to)} of {bound.to.repository}: a concern goes to an agent of its own repository"
            raise InboxError(message)
        above = bound.thread
        while above is not None:
            if above.number == thread.number:
                message = f"@{thread.name} can't go under itself, nor under a concern nested under it"
                raise InboxError(message)
            above = self.concerns.at(above.parent)

    def commented(self, comment: Comment, sent: Destination) -> WrittenRoute:
        """Return where `comment` goes, `sent` elsewhere than to whoever sent its item, and its words quoting what it's on (`quoting`)."""
        item = self.concerns.inbox.items.get(comment.item)
        repository = None if item is None else repository_of(item)
        if item is None or repository is None:
            message = f"a comment on {cited(comment.item)} is sent somewhere, and lup keeps no such item of a repository"
            raise InboxError(message)
        to = self.bound(sent, repository)
        self.written_to(to, f"a comment on {cited(item.number)}")
        return WrittenRoute(id=comment.id, text=quoting(item, comment), to=to)

    def lettered(self, letter: Letter) -> WrittenRoute:
        """Return where `letter`, sent elsewhere than where it was written, goes, the lines of a concern's body it's on quoted before its words, saying whose."""
        thread = None if letter.thread is None else self.concerns.thread(letter.thread)
        repository = thread.repository if thread is not None else None
        if repository is None and letter.to is not None:
            repository = letter.to.repository
        if repository is None or letter.sent is None:
            message = "a message sent somewhere is written to an agent or on a concern"
            raise InboxError(message)
        to = self.bound(letter.sent, repository)
        self.written_to(to, "a message")
        text = (
            letter.text
            if letter.quote is None or thread is None
            else f"On @{thread.name}'s body:\n\n{quoted(letter.quote.text)}\n\n{letter.text}"
        )
        return WrittenRoute(id=letter.id, text=text, to=to)

    def remarked(self, remark: Remark) -> WrittenRoute:
        """Return where `remark`, sent elsewhere than to the agent whose drawer it's in, goes, the passage it's on quoted before its words, saying whose words or which file's lines."""
        if remark.sent is None:
            message = "a remark sent somewhere names where"
            raise InboxError(message)
        to = self.bound(remark.sent, remark.to.repository)
        self.written_to(to, "a remark")
        code = remark.code
        on = (
            f"{self.roster.who(remark.to)}'s words"
            if code is None
            else f"`{code.path}`, lines {code.first} to {code.first + len(code.lines) - 1}"
        )
        text = f"On {on}:\n\n{quoted(remark.quote.text)}\n\n{remark.text}"
        return WrittenRoute(id=remark.id, text=text, to=to)

    def written_to(self, to: Bound, what: str) -> None:
        """Say where `what`, written by the operator, is sent to `No agent`, which no words reach."""
        if to.nobody:
            message = f"{what} goes to an agent, a concern or a pile, not to `No agent`"
            raise InboxError(message)

    def routed(self, plan: Plan) -> Routed:
        """Move what `plan` moves, as the operator sends it: each pile it names opened once where there's none; each concern moved, then each item; and return the messages what was written there is sent as, each to whoever answers for the concern it goes to, or to no one on a pile nobody answers for, with what moved where."""
        # Each pile once, however many things go to it, by where it's named.
        piles: dict[Bound, Thread] = {}

        def place(bound: Bound) -> Thread | None:
            if bound.thread is not None:
                return self.concerns.thread(bound.thread.number)
            if bound.pile is None:
                return None
            if bound not in piles:
                piles[bound] = self.concerns.pile(bound.repository, bound.pile)
            return piles[bound]

        def moved() -> Iterator[Went]:
            for route in plan.concerns:
                thread = self.concerns.thread(route.thread.number)
                under = place(route.to)
                given = self.concerns.given(thread, route.to.to, under)
                yield Went(
                    thread=given.number,
                    name=given.name,
                    into=None if under is None else under.number,
                    to=self.said(route.to, under),
                )
            for route in plan.items:
                into = place(route.to)
                if into is not None:
                    self.concerns.into(route.item, into)
                    yield Went(
                        item=route.item.number,
                        into=into.number,
                        to=self.said(route.to, into),
                    )

        went = list(moved())

        def lettered(route: WrittenRoute) -> Letter:
            into = place(route.to)
            return Letter(
                id=route.id,
                to=route.to.to if into is None else self.concerns.answering(into),
                thread=None if into is None else into.number,
                text=route.text,
            )

        return Routed(went=went, letters=[lettered(each) for each in plan.written])

    def followed(self, letters: list[Letter], went: list[Went]) -> list[Letter]:
        """Return `letters`, each written on a concern `went` moved going to whoever answers for it where it went, so what's written on a concern goes with it; one written to no one stays so."""
        moved = [each.thread for each in went if each.thread is not None]

        def follows(letter: Letter) -> Letter:
            if letter.thread not in moved or letter.to is None:
                return letter
            to = self.concerns.answering(self.concerns.thread(letter.thread))
            return letter.model_copy(update={"to": to})

        return [follows(each) for each in letters]

    def reach(self, destination: Destination, repository: Path) -> Destination:
        """Return where `destination`, of what's sent from `repository`, reaches, as the line under the review groups what Ctrl+Enter sends: an agent; whoever answers for a concern, or for a pile there already, else that concern; a pile not opened yet by its title; `No agent`."""
        if destination.to is not None:
            return destination
        thread = (
            self.concerns.at(destination.thread)
            if destination.thread is not None
            else None
            if destination.pile is None
            else self.concerns.piled(repository, destination.pile.strip())
        )
        if thread is None:
            return destination
        answering = self.concerns.answering(thread)
        return (
            Destination(thread=thread.number)
            if answering is None
            else Destination(to=answering)
        )

    def reached(self, number: int) -> Destination | None:
        """Return where what's drafted on item `number` reaches with the reply, its sender; none where a conversation didn't send it, as an approval, whose answer goes its own way."""
        item = self.concerns.inbox.items.get(number)
        return (
            Destination(to=item.sender)
            if item is not None and isinstance(item.sender, Conversation)
            else None
        )

    def split(self, draft: Draft, only: Destination) -> Split:
        """Split `draft` where Ctrl+Enter sends `only` alone, as the line under the review groups it (`reach`): what reaches it, sent, each comment, message, remark and move, and each item of its marked done or declined; the rest, and every mark the page applies, staying drafted."""

        def item_repository(number: int) -> Path:
            item = self.concerns.inbox.items.get(number)
            found = None if item is None else repository_of(item)
            return Path("/") if found is None else found

        def letter_repository(letter: Letter) -> Path:
            thread = None if letter.thread is None else self.concerns.at(letter.thread)
            if thread is not None:
                return thread.repository
            return Path("/") if letter.to is None else letter.to.repository

        def reaching(destination: Destination | None, repository: Path) -> bool:
            if destination is None:
                return False
            reached = self.reach(destination, repository)
            return reached == self.reach(only, repository)

        def commented(comment: Comment) -> bool:
            sent = going(draft, comment)
            repository = item_repository(comment.item)
            if sent is not None:
                return reaching(sent, repository)
            return reaching(self.reached(comment.item), repository)

        def lettered(letter: Letter) -> bool:
            repository = letter_repository(letter)
            if letter.sent is not None:
                return reaching(letter.sent, repository)
            if letter.to is not None:
                return reaching(Destination(to=letter.to), repository)
            return reaching(Destination(thread=letter.thread), repository)

        def remarked(remark: Remark) -> bool:
            return reaching(
                remark.sent or Destination(to=remark.to), remark.to.repository
            )

        def moved(move: Destined) -> bool:
            if move.item is not None:
                return reaching(move.to, item_repository(move.item))
            thread = None if move.thread is None else self.concerns.at(move.thread)
            return thread is not None and reaching(move.to, thread.repository)

        def marked(number: int) -> bool:
            return reaching(self.reached(number), item_repository(number))

        sending = Draft(
            comments=[each for each in draft.comments if commented(each)],
            letters=[each for each in draft.letters if lettered(each)],
            remarks=[each for each in draft.remarks if remarked(each)],
            done=[each for each in draft.done if marked(each)],
            declined=[each for each in draft.declined if marked(each)],
            moves=[each for each in draft.moves if moved(each)],
        )
        staying = Draft(
            comments=[each for each in draft.comments if each not in sending.comments],
            letters=[each for each in draft.letters if each not in sending.letters],
            remarks=[each for each in draft.remarks if each not in sending.remarks],
            done=[each for each in draft.done if each not in sending.done],
            declined=[each for each in draft.declined if each not in sending.declined],
            moves=[each for each in draft.moves if each not in sending.moves],
            marks=draft.marks,
        )
        return Split(sending=sending, staying=staying)

    def said(self, bound: Bound, into: Thread | None) -> str:
        """Say where a thing went, in a few words: to an agent, by their path; into a concern or a pile, by its name; to `No agent`."""
        if bound.to is not None:
            return f"to {self.roster.called(bound.to)}"
        if into is not None:
            return f"into @{into.name}"
        return "to No agent"
