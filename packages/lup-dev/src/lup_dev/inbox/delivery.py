"""Telling each conversation what waits in its inbox, once: at its hooks, by a held call, and by starting a turn of its idle session.

`docs/host-tools.md`, *How an agent is told*. Every item waiting for a
conversation is told together, oldest first, by whichever comes first:
- **its next call,** beside it, as the hook's context (`telling`, which the host
  service asks at every hook, the `Post` it's handed); but not at the start of a
  call to lup's own tools (`Heard.served`), whose result tells it: told beside
  `wait_inbox`, an item would reach the model only once the call returned, and
  the call would wait for the next;
- **its turn's end,** where some are still waiting: the end is held once, the
  items its reason, so they never hold an end again (`inbox/ends.py`);
- **`wait_inbox`,** or `ask` with `wait`, a call held until something arrives,
  whose result is the items (`held`);
- **its session's start or resumption,** in the start's answer;
- **its turn started through its session's own messaging socket,** where its
  runtime's adapter spells a way (the courier's `woken`), for an item the
  operator's own act made to an idle session: one whose turn ended, one just
  started, or one the service hasn't heard since it started. A session in its
  turn is told at its next call, or its turn's end, instead. What's written is
  a doorbell, what waits and that `wait_inbox` reads it (`doorbell`), never the
  items: the socket takes any local session's message, and the runtime says so
  of each, so what's in an agent's inbox comes through lup's own tools alone.
  An idle session starts a turn with it; one the service misjudged as idle
  takes it at its next boundary. It rings once until the session's next hook.
  Where a runtime has no way, the item waits for the session's next call, a
  gap its adapter declares.

**Told once.** An item is told when it's written into a hook's answer or a held
call's result, and never again:
- one past what a hook tells the model whole (`Heard.fits`) is announced there
  instead, who sent it and its size, with a line saying `wait_inbox` returns it
  whole; it waits until then, and isn't announced again. Nothing is cut;
- what a hook would tell that doesn't fit in what the judge's answer leaves
  waits for the next hook, so the items stay in order;
- a held call whose conversation's turn ended while it held (seen where a
  runtime runs a held call as a pending cell the model can leave) doesn't count
  what arrives as told: it says the items reach the agent at its next call, and
  they're told there;
- what a hook gone before its answer would have told is put back (`returned`).

**An item for a conversation that has ended** goes to its session's main
conversation, saying whose it was: one made for it then (`Inbox.made`), and
those still waiting when it ends.

The operator hears of each item that reaches them through the desktop's notices.

**An approval** (trust on launch's) is the operator's alone, never told to a
conversation: a launch puts it in their inbox and waits on it (`settled`), and
every launch asking about the same zone while it waits joins it (`asked`); one asked about a newer zone of the same repository supersedes it. It's
answered once, by whichever terminal answers first (`decided`), which wakes every
launch waiting on it; an answer after that changes nothing. The operator's
comment on one a push asked is told to the session that pushed, as a note
saying which approval and the answer (`commented`); one a launch asked at its
terminal has no session to tell.

What the service knows of a conversation while it serves (whether a call of
its runs, the calls it holds) is in memory: a service started again knows of
no call running, and wakes.
"""

import asyncio
from collections.abc import Callable, Generator
from datetime import datetime
from typing import TYPE_CHECKING, override

from lup.types import Model, MutableModel
from lup_dev.clock import Clock
from lup_dev.host.courier import Courier, Heard, Post, Posted
from lup_dev.inbox.ends import holding
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Approval,
    ChangedFile,
    Comment,
    Conversation,
    Decided,
    Done,
    HeldChange,
    How,
    Inbox,
    InboxError,
    Item,
    Message,
    Operator,
    Party,
    Question,
    Reason,
    Review,
    Ruling,
    Superseded,
    Told,
    Verdict,
    Waiting,
    Whereabouts,
    Withdrawn,
)
from lup_dev.layout import HostLayout

if TYPE_CHECKING:
    from pathlib import Path

    from lup_dev.host.courier import Conversation as Caller
    from lup_dev.host.protocol import Register

SEPARATOR = "\n\n"
"""What each adapter puts between two things it tells in one field."""


def who(party: Party) -> str:
    """Name a party, for whoever reads an item.

    >>> who(Operator())
    'the operator'
    """
    match party:
        case Operator():
            return "the operator"
        case Conversation(agent=str() as agent):
            return f"subagent {agent} of {party.runtime} session {party.session}"
        case Conversation():
            return f"{party.runtime} session {party.session}"


def what(item: Item) -> str:
    """Say what an item is, in a few words."""
    match item.reason:
        case Message(kind="question"):
            return "a question, as a message"
        case Message(kind=kind):
            return f"a {kind}"
        case Question():
            return "a question"
        case Answer():
            return "an answer"
        case Approval():
            return "an approval"
        case HeldChange():
            return "a held change"
        case Review():
            return "a review"


def opening(item: Item) -> str:
    """Return an item's first line: its text's, an answer's comment's, or a review's first comment's."""
    match item.reason:
        case (
            Message(text=text)
            | Question(text=text)
            | Approval(text=text)
            | HeldChange(text=text)
        ):
            said = text
        case Answer(comment=comment):
            said = comment
        case Review(comments=comments):
            said = next((each.text for each in comments), "")
    return next(iter(said.splitlines()), "")


def body(item: Item) -> str:
    """Return an item's text whole, as its sender wrote it: a question's with each decision numbered, with its lean."""
    match item.reason:
        case Question(text=text, decisions=decisions):
            numbered = [
                f"{at}. {each.text} (lean: {each.lean})"
                for at, each in enumerate(decisions, start=1)
            ]
            return "\n".join([text, *numbered])
        case Message(text=text) | Approval(text=text) | HeldChange(text=text):
            return text
        case Answer(comment=comment):
            return comment
        case Review(comments=comments):
            return "\n".join(each.text for each in comments)


def clocked(at: datetime) -> str:
    """Say a moment as the host's clock reads it, to the minute: the operator's own time zone's, where the inbox keeps UTC."""
    return f"{at.astimezone():%Y-%m-%d %H:%M}"


def standing(item: Item) -> str:
    """Say where an item stands."""
    match item.state:
        case Waiting(announced=announced):
            if announced is None:
                return "waiting"
            return f"waiting, announced at {clocked(announced)} as too long to tell"
        case Told(at=at, how=how):
            return f"told at {clocked(at)} ({how})"
        case Answered(at=at, answer=answer):
            return f"answered at {clocked(at)}, item {answer}"
        case Done(at=at):
            return f"done at {clocked(at)}"
        case Decided(at=at, approved=approved):
            return f"{'approved' if approved else 'declined'} at {clocked(at)}"
        case Superseded(at=at, by=by):
            return f"superseded at {clocked(at)} by item {by}"
        case Withdrawn(at=at, why=why):
            return f"withdrawn at {clocked(at)} by its sender: {why}"


def doorbell(waiting: list[Item]) -> str:
    """Say what waits in a conversation's inbox, each item by its number, kind and sender, for the agent to read through `wait_inbox`.

    >>> from datetime import UTC, datetime
    >>> item = Item(number=7, reason=Message(kind="note", text="Hi."),
    ...     sender=Operator(), recipient=Operator(), made=datetime(2026, 1, 1, tzinfo=UTC))
    >>> print(doorbell([item]))
    lup's inbox: item 7, a note from the operator. Call `wait_inbox` to read it: what's in your inbox comes through lup's own tools, never in a message like this one.
    """
    heads = "; ".join(
        f"item {item.number}, {what(item)} from {who(item.sender)}" for item in waiting
    )
    them = "it" if len(waiting) == 1 else "them"
    return (
        f"lup's inbox: {heads}. Call `wait_inbox` to read {them}: what's in your "
        "inbox comes through lup's own tools, never in a message like this one."
    )


def reviewable(item: Item) -> None:
    """Refuse an item a review can't answer: one no conversation sent, an answer or an approval."""
    match item:
        case Item(sender=Conversation(), reason=Message() | Question()):
            return
        case _:
            message = (
                f"item {item.number} is {what(item)} from {who(item.sender)}, which "
                "a review doesn't answer"
            )
            raise InboxError(message)


def remark(comment: Comment) -> str:
    """Say one of the operator's comments on an item: on its passage, quoted, or on the item whole."""
    if comment.quote is None:
        return f"  {comment.text}"
    quoted = "\n".join(f"    > {line}" for line in comment.quote.text.splitlines())
    return f"  On this passage:\n{quoted}\n    {comment.text}"


def commented(item: Item, comment: str) -> str:
    """Say the operator's answer to an approval a push asked, with their comment, for the session that pushed.

    >>> from datetime import UTC, datetime
    >>> from pathlib import Path
    >>> asked = Approval(text="Approve the host zone at abc?", summary="",
    ...     repository=Path("/r.git"), fingerprint="f")
    >>> item = Item(number=7, reason=asked, sender=Operator(), recipient=Operator(),
    ...     made=datetime(2026, 1, 1, tzinfo=UTC),
    ...     state=Decided(at=datetime(2026, 1, 1, tzinfo=UTC), approved=False))
    >>> print(commented(item, "Split the reader out first."))
    The operator declined item 7, the approval your push asked ("Approve the host zone at abc?"), and commented:
    Split the reader out first.
    """
    answer = (
        "approved"
        if isinstance(item.state, Decided) and item.state.approved
        else "declined"
    )
    return (
        f"The operator {answer} item {item.number}, the approval your push asked "
        f'("{opening(item)}"), and commented:\n{comment}'
    )


def settled(item: Item, review: Item, at: datetime) -> Answered | Done:
    """Return where an item a review covers stands once it's sent: a question answered by it, a message done."""
    if isinstance(item.reason, Question):
        return Answered(at=at, answer=review.number)
    return Done(at=at)


def ruled(verdict: Verdict) -> str:
    """Say what the operator's verdict on a decision means, for the agent who asked."""
    match verdict:
        case "leaning":
            return "leaning: they go with the lean"
        case "undecided":
            return "undecided"
        case "leave open":
            return "leave open: it's left for later"


def announced(item: Item) -> bool:
    """Say whether an item waits announced as too long for a hook, for `wait_inbox` to return whole."""
    match item.state:
        case Waiting(announced=datetime()):
            return True
        case _:
            return False


def announcement(item: Item, size: int) -> str:
    """Announce an item too long for a hook: who sent it, its size, and that `wait_inbox` returns it whole."""
    return (
        f"lup's inbox, item {item.number}: {what(item)} from {who(item.sender)}, "
        f"{size:,} bytes, too long to tell here. Call `wait_inbox` to read it whole."
    )


class Choice(Model):
    """What a hook tells of one item: its text or its announcement."""

    item: Item
    text: str
    told: bool
    """Whether it's told whole; else it's announced, waiting for `wait_inbox`."""


class Held(MutableModel, arbitrary_types_allowed=True):
    """A call of a conversation's held until something reaches its inbox."""

    arrived: asyncio.Event
    ended: bool = False
    """Whether the conversation's turn ended while the call held: what it would
    return then isn't counted told, since the model may never read it."""


class Presence(MutableModel):
    """What the service knows of a conversation while it serves: whether a call of its runs, whether it was woken since its last hook, and the calls it holds."""

    turning: bool = False
    """Whether its turn runs, as its hooks last said: from a call's start until
    its turn's end is let through, its next call or its turn's end telling what
    waits. One just started, or that the service hasn't heard since it started,
    is idle."""
    woken: bool = False
    """Whether it was woken since its last hook: the turn the wake starts tells
    what arrives meanwhile at its first call."""
    held: list[Held] = []


class Delivery(MutableModel, Post, arbitrary_types_allowed=True):
    """Each conversation's inbox, told once; and the operator's, noticed on their desktop."""

    inbox: Inbox
    courier: Courier
    """Spells how an idle session is woken, where its runtime has a way."""
    layout: HostLayout
    """Where each launch's sockets are, its session's messaging socket among them."""
    notices: Notices
    clock: Clock
    say: Callable[[str], None]
    presences: dict[str, Presence] = {}
    """By conversation's key, in memory."""
    settling: dict[int, asyncio.Event] = {}
    """By approval's number, in memory: set once the approval is answered, which
    wakes every launch waiting on it."""
    settle_hold: Callable[[HeldChange, bool, str], None] | None = None
    """Writes the operator's answer to a held change where its hook waits for
    it, yes or no and their comment; none where this service answers no hold."""

    def presence(self, conversation: Conversation) -> Presence:
        """Return what the service knows of `conversation` while it serves."""
        key = conversation.key()
        if key not in self.presences:
            self.presences = {**self.presences, key: Presence()}
        return self.presences[key]

    @override
    async def telling(
        self, launch: Register, conversation: Caller, heard: Heard, room: int
    ) -> Posted:
        """Note where the conversation is heard, and tell it what waits.

        At its turn's end, what waits holds the end once (`holding`), and a call
        it holds learns its turn ended; an end let through leaves its main
        conversation idle, and a subagent's ended, its waiting items passed to
        its session's main conversation.
        """
        party = Conversation(
            repository=launch.repository,
            runtime=launch.runtime,
            session=conversation.session,
            agent=conversation.agent,
        )
        self.heard_in(party, launch)
        presence = self.presence(party)
        presence.woken = False
        match heard.event:
            case "turn-ended" | "conversation-ended":
                for each in presence.held:
                    each.ended = True
                fresh = [
                    item for item in self.inbox.waiting(party) if not announced(item)
                ]
                if holding(fresh, [], after_block=heard.after_block):
                    posted = self.told(party, room, heard.fits, "turn's end")
                    if posted.items:
                        return posted
                presence.turning = False
                if heard.event == "conversation-ended" and party.agent is not None:
                    self.ended(party)
                return Posted()
            case "session-started":
                presence.turning = False
                return self.told(party, room, heard.fits, "start")
            case "call-started" if heard.served:
                presence.turning = True
                return Posted()
            case "call-started" | "call-finished":
                presence.turning = True
                return self.told(party, room, heard.fits, "call")

    @override
    async def concluded(
        self, launch: Register, conversation: Caller, said: str
    ) -> None:
        """Put a session's last message of a turn in the operator's inbox, as a note from it: they read what it ended its turn saying there, without it sending it again."""
        party = Conversation(
            repository=launch.repository,
            runtime=launch.runtime,
            session=conversation.session,
            agent=conversation.agent,
        )
        await self.posted(
            Message(kind="note", text=said), party, Operator(), launch.worktree
        )

    @override
    def returned(self, posted: Posted) -> None:
        for number in posted.numbers:
            item = self.inbox.item(number)
            self.inbox.kept(item.model_copy(update={"state": Waiting()}))

    def heard_in(self, party: Conversation, launch: Register) -> None:
        """Note that `party` is heard in `launch`: where it runs, and that it goes on."""
        place = self.inbox.whereabouts.get(party.key())
        if place is not None and place.launch == launch.launch and place.ended is None:
            return
        self.inbox.placed(
            Whereabouts(
                conversation=party,
                launch=launch.launch,
                worktree=launch.worktree,
                since=self.clock.now(),
            )
        )

    def ended(self, party: Conversation) -> None:
        """Note that a subagent's conversation ended, and pass what waits for it to its session's main conversation."""
        place = self.inbox.whereabouts.get(party.key())
        if place is not None:
            self.inbox.placed(place.model_copy(update={"ended": self.clock.now()}))
        main = party.main()
        for item in self.inbox.waiting(party):
            self.inbox.kept(
                item.model_copy(update={"recipient": main, "addressed": party})
            )
        self.arrive(main)

    def said(self, item: Item) -> str:
        """Say `item`, whole, to the conversation it's told to."""
        head = f"lup's inbox, item {item.number}: {what(item)} from {who(item.sender)}"
        passed = (
            ""
            if item.addressed is None
            else f" (it was for {who(item.addressed)}, whose conversation had ended)"
        )
        match item.reason:
            case Message(text=text, of=int() as of):
                original = self.inbox.item(of)
                return (
                    f"{head}{passed}, replying to item {of}, {what(original)} you "
                    f'sent ("{opening(original)}"):\n{text}'
                )
            case (
                Message(text=text)
                | Question(text=text)
                | Approval(text=text)
                | HeldChange(text=text)
            ):
                return f"{head}{passed}:\n{text}"
            case Answer() as answer:
                return (
                    f"{head}{passed}, to the question of item {answer.question}:\n"
                    f"{self.answered(answer)}"
                )
            case Review() as review:
                numbers = ", ".join(str(each) for each in review.covers)
                items = "item" if len(review.covers) == 1 else "items"
                return (
                    f"{head}{passed}, of {items} {numbers}:\n"
                    f"{self.reviewing(review, item.recipient)}"
                )

    def reviewing(self, review: Review, recipient: Party) -> str:
        """Say a review to one conversation it's sent to: its own items first, each with the operator's comments on it, or read with nothing to add; then, for context, the other agents' items they commented on, each whole and whose it is."""
        items = [self.inbox.item(each) for each in review.covers]
        commented = [each.item for each in review.comments]

        def remarks(item: Item) -> list[str]:
            return [
                remark(each) for each in review.comments if each.item == item.number
            ]

        def yours(item: Item) -> str:
            head = f'On item {item.number}, {what(item)} yours ("{opening(item)}"):'
            return "\n".join(
                [head, *(remarks(item) or ["  (read, with nothing to add)"])]
            )

        def theirs(item: Item) -> str:
            where = "" if item.worktree is None else f", in {item.worktree}"
            head = (
                f"On item {item.number}, {what(item)} from {who(item.sender)}{where}:"
            )
            text = [f"    | {line}" for line in body(item).splitlines()]
            return "\n".join([head, *text, *remarks(item)])

        own = [yours(item) for item in items if item.sender == recipient]
        others = [
            theirs(item)
            for item in items
            if item.sender != recipient and item.number in commented
        ]
        heading = (
            "For context, what the operator said in the same reply on other "
            "agents' items: not yours to act on, unless a comment says so."
        )
        context = [heading, *others] if others else []
        return "\n\n".join([*own, *context])

    async def reviewed(self) -> list[Item]:
        """Send the operator's draft as one reply: to each conversation with a comment on its items, or a question among them, the whole of it; its items answered or done, and the draft left with what's parked.

        Each conversation is told its own items first, with the comments on
        them or read with nothing to add, then what was said on the others'
        for context (`reviewing`): the operator answers related items together,
        across agents and repositories, and sends what's drafted on moving to
        something unrelated. A question is answered by the reply its asker
        gets, which lets a held `ask` go. A message only marked read tells its
        sender nothing, nor wakes it: it's taken off the list, and told as read
        only to a conversation the reply reaches anyway. Refused where the
        draft covers no item, or covers one no conversation sent.
        """
        draft = self.inbox.draft()
        covered = [self.inbox.item(each) for each in draft.covered()]
        if not covered:
            message = (
                "the draft answers no item: comment on one, or take one off the list"
            )
            raise InboxError(message)
        for item in covered:
            reviewable(item)
        at = self.clock.now()
        numbers = [item.number for item in covered]
        review = Review(
            covers=numbers,
            comments=[each for each in draft.comments if each.item in numbers],
        )
        commented = [each.item for each in draft.comments]
        senders = [
            item.sender
            for item in covered
            if item.number in commented or isinstance(item.reason, Question)
        ]
        recipients = [
            each for index, each in enumerate(senders) if each not in senders[:index]
        ]
        sent = [
            self.inbox.made(review, Operator(), recipient, None, at)
            for recipient in recipients
        ]
        for item in covered:
            answer = next(
                (each for each in sent if each.recipient == item.sender), None
            )
            settling = Done(at=at) if answer is None else settled(item, answer, at)
            self.inbox.kept(item.model_copy(update={"state": settling}))
        self.inbox.drafted(draft.kept())
        for each in sent:
            await self.delivered(each)
        return sent

    def answered(self, answer: Answer) -> str:
        """Say the operator's answer, each decision beside its question's text and the lean it was asked with."""
        match self.inbox.item(answer.question).reason:
            case Question(text=text, decisions=decisions):
                pass
            case _:
                message = f"item {answer.question} isn't a question"
                raise InboxError(message)

        def decided(ruling: Ruling) -> str:
            decision = decisions[ruling.decision - 1]
            asked = f"{ruling.decision}. {decision.text} (lean: {decision.lean})"
            if ruling.verdict is None:
                return f"{asked}: they answer: {ruling.comment}"
            comment = f" They add: {ruling.comment}" if ruling.comment else ""
            return f"{asked}: {ruled(ruling.verdict)}.{comment}"

        heading = f"Asked: {text}"
        rulings = [decided(ruling) for ruling in answer.rulings]
        label = "Their comment on the whole" if rulings else "Their answer"
        whole = [f"{label}: {answer.comment}"] if answer.comment else []
        return "\n".join([heading, *rulings, *whole])

    def told(self, party: Conversation, room: int, fits: int, how: How) -> Posted:
        """Tell `party` what waits for it, oldest first, in `room` bytes at most: each whole where a hook carries it whole (`fits`), else announced.

        One already announced is left for `wait_inbox`. The first that doesn't
        fit in what's left waits, with all after it, for the next hook.
        """

        def chosen() -> Generator[Choice]:
            left = room
            for item in self.inbox.waiting(party):
                if announced(item):
                    continue
                text = self.said(item)
                size = len(text.encode()) + len(SEPARATOR)
                choice = (
                    Choice(item=item, text=text, told=True)
                    if size <= fits
                    else Choice(item=item, text=announcement(item, size), told=False)
                )
                cost = len(choice.text.encode()) + len(SEPARATOR)
                if cost > left:
                    return
                left -= cost
                yield choice

        now = self.clock.now()
        choices = list(chosen())
        for choice in choices:
            state = Told(at=now, how=how) if choice.told else Waiting(announced=now)
            self.inbox.kept(choice.item.model_copy(update={"state": state}))
        return Posted(
            items=[choice.text for choice in choices],
            numbers=[choice.item.number for choice in choices],
        )

    def whole(self, party: Conversation, how: How) -> str:
        """Tell `party` everything waiting for it, each whole, oldest first; empty where nothing is."""
        waiting = self.inbox.waiting(party)
        told = Told(at=self.clock.now(), how=how)
        for item in waiting:
            self.inbox.kept(item.model_copy(update={"state": told}))
        return SEPARATOR.join(self.said(item) for item in waiting)

    async def held(self, party: Conversation, until: Callable[[], bool]) -> str:
        """Hold a call of `party`'s until `until()`, checked again at each arrival; then tell it everything waiting.

        Where its turn ended while the call held, nothing is counted told: it
        says what waits reaches the agent at its next call. A call cancelled
        while it holds, its connection gone, leaves everything waiting.
        """
        presence = self.presence(party)
        holder = Held(arrived=asyncio.Event())
        presence.held = [*presence.held, holder]
        try:
            while not until():
                await holder.arrived.wait()
                holder.arrived.clear()
        finally:
            presence.held = [each for each in presence.held if each is not holder]
        if holder.ended:
            return (
                "Your turn ended while this call waited, so what reached your inbox "
                "reaches you at your next call instead."
            )
        return self.whole(party, "held call")

    def arrive(self, party: Conversation) -> None:
        """Wake each call of `party`'s held until something arrives."""
        for each in self.presence(party).held:
            each.arrived.set()

    async def posted(
        self,
        reason: Reason,
        sender: Party,
        recipient: Party,
        worktree: Path | None,
        *,
        call: str | None = None,
    ) -> Item:
        """Make an item and deliver it (`delivered`); `call` is the runtime's id for the agent's call that made it, where one did."""
        item = self.inbox.made(
            reason, sender, recipient, worktree, self.clock.now(), call=call
        )
        await self.delivered(item)
        return item

    async def delivered(self, item: Item) -> None:
        """Tell the recipient that `item` reached its inbox: the operator through a desktop notice, a conversation through its held calls, or by waking it where the operator made it."""
        match item.recipient:
            case Operator():
                await self.noticed(item)
            case Conversation() as conversation:
                self.arrive(conversation)
                if isinstance(item.sender, Operator):
                    await self.wake(conversation)

    async def noticed(self, item: Item) -> None:
        """Raise a desktop notice for an item reaching the operator: where it's from, what it is, and its first line."""
        where = "" if item.worktree is None else f" in {item.worktree}"
        summary = f"lup: {what(item)} from {who(item.sender)}{where}"
        body = f"{opening(item)}\nlup-dev inbox show {item.number}"
        await self.notices.notify(summary, body)

    async def wake(self, party: Conversation) -> None:
        """Ring an idle `party`'s session's doorbell through its messaging socket: what waits, for `wait_inbox` to read, where its runtime has a way.

        Only a session's main conversation is woken, and only while it's idle.
        One in its turn (`Presence.turning`) is told at its next call, or its
        turn's end; a call it holds is given it; a wake since its last hook
        started a turn whose first call tells it; and a runtime with no way
        waits for its next hook. An idle session starts a turn with it; one the
        service took for idle, unknown since the service started again or since
        the operator interrupted it, takes it at its next boundary, as measured
        on the runtime that has a way (`docs/field-notes.md`, *Waking a
        session*). The items stay waiting, told once by whichever reaches the
        agent first: `wait_inbox`, its next call's hook, or its turn's end;
        where the session's messaging socket can't be reached, that's said.
        """
        presence = self.presence(party)
        place = self.inbox.whereabouts.get(party.key())
        waiting = self.inbox.waiting(party)
        quiet = presence.turning or presence.woken or presence.held
        if party.agent is not None or quiet or place is None or not waiting:
            return
        line = self.courier.woken(party.runtime, party.session, doorbell(waiting))
        if line is None:
            return
        presence.woken = True
        socket = self.layout.launch(place.launch).messages
        try:
            _, writer = await asyncio.open_unix_connection(str(socket))
            writer.write(f"{line}\n".encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except OSError as unreached:
            presence.woken = False
            self.say(
                f"{place.launch}: {who(party)} wasn't woken through {socket}, so "
                f"what waits for it is told at its next call: {unreached}"
            )
            return
        numbers = ", ".join(str(item.number) for item in waiting)
        self.say(f"{place.launch}: woke {who(party)} for items {numbers}")

    def running(self, launch: str) -> Conversation | None:
        """Return the main conversation of the session `launch` runs, the latest heard there; none where no session of it has reached lup."""
        found = [
            place
            for place in self.inbox.whereabouts.values()
            if place.launch == launch and place.conversation.agent is None
        ]
        if not found:
            return None
        return max(found, key=lambda place: place.since).conversation

    def main_of(self, launch: str) -> Conversation:
        """Return the main conversation of the session `launch` runs, the latest heard there, or say there's none."""
        found = self.running(launch)
        if found is None:
            message = (
                f"no session of launch `{launch}` has reached lup yet, so nothing "
                "there can be told"
            )
            raise InboxError(message)
        return found

    async def answer(self, number: int, rulings: list[Ruling], comment: str) -> Item:
        """Answer the question item `number`, or reply to the message: the answer an item for the conversation that sent it.

        A question is answered; a message is replied to (`replied`). Refused
        where it's neither a question waiting nor a conversation's message;
        where a question's decisions aren't each answered once, one with
        neither a verdict nor words, or a plain question has no words for its
        answer.
        """
        item = self.inbox.item(number)
        match item:
            case Item(reason=Message(), sender=Conversation() as sender):
                return await self.replied(item, sender, rulings, comment)
            case Item(
                reason=Question(decisions=decisions),
                state=Waiting(),
                sender=Conversation() as asker,
            ):
                pass
            case _:
                message = (
                    f"item {number} is {what(item)} from {who(item.sender)}: neither "
                    "a question waiting for an answer nor a conversation's message to "
                    "reply to"
                )
                raise InboxError(message)
        given = sorted(each.decision for each in rulings)
        if given != list(range(1, len(decisions) + 1)):
            message = (
                f"item {number} asks {len(decisions)} decisions, each taking one "
                "answer (`leaning`, `undecided`, `leave open`, or words); these were "
                f"given for {given or 'none'}"
            )
            raise InboxError(message)
        unsaid = [
            each.decision
            for each in rulings
            if each.verdict is None and not each.comment.strip()
        ]
        if unsaid:
            message = (
                f"item {number}'s decisions {unsaid} have neither a verdict nor "
                "words: give one"
            )
            raise InboxError(message)
        if not decisions and not comment.strip():
            message = f"item {number} is a question answered in words: give them"
            raise InboxError(message)
        answer = self.inbox.made(
            Answer(question=number, rulings=rulings, comment=comment),
            Operator(),
            asker,
            None,
            self.clock.now(),
        )
        answered = Answered(at=self.clock.now(), answer=answer.number)
        self.inbox.kept(item.model_copy(update={"state": answered}))
        await self.delivered(answer)
        return answer

    async def replied(
        self, item: Item, sender: Conversation, rulings: list[Ruling], comment: str
    ) -> Item:
        """Reply to `sender`'s message `item`: the reply a note for it, saying which item it replies to, and the message off the operator's list.

        Refused where verdicts are given, which only a question's decisions take,
        or where the reply has no words.
        """
        if rulings:
            message = (
                f"item {item.number} is {what(item)}, which takes a reply in words, "
                "not verdicts"
            )
            raise InboxError(message)
        if not comment.strip():
            message = f"item {item.number} is {what(item)}: give your reply in words"
            raise InboxError(message)
        reply = self.inbox.made(
            Message(kind="note", text=comment, of=item.number),
            Operator(),
            sender,
            None,
            self.clock.now(),
        )
        if isinstance(item.state, Waiting):
            self.inbox.kept(
                item.model_copy(update={"state": Done(at=self.clock.now())})
            )
        await self.delivered(reply)
        return reply

    def done(self, number: int) -> Item:
        """Take the message item `number` off the operator's list.

        A question is answered instead, and an item that isn't the operator's,
        or isn't waiting, is refused.
        """
        item = self.inbox.item(number)
        match item:
            case Item(reason=Message(), recipient=Operator(), state=Waiting()):
                done = Done(at=self.clock.now())
                return self.inbox.kept(item.model_copy(update={"state": done}))
            case Item(reason=Question() | Approval() | HeldChange(), state=Waiting()):
                message = (
                    f"item {number} is {what(item)}: answer it, `lup-dev inbox answer "
                    f"{number}`"
                )
                raise InboxError(message)
            case _:
                message = f"item {number} isn't a message waiting in your inbox"
                raise InboxError(message)

    def withdrawn(self, number: int, party: Conversation, why: str) -> Item:
        """Take the message or question item `number` back for `party`, who sent it, off the operator's list, with its reason.

        Another's item, one that isn't waiting for the operator, and an approval
        or a held change, which only the operator answers, are refused.
        """
        item = self.inbox.item(number)
        match item:
            case Item(
                reason=Message() | Question(), recipient=Operator(), state=Waiting()
            ) if item.sender == party:
                taken = Withdrawn(at=self.clock.now(), why=why)
                self.say(f"item {number}, {what(item)}, was withdrawn by its sender")
                return self.inbox.kept(item.model_copy(update={"state": taken}))
            case Item(sender=sender) if sender != party:
                message = (
                    f"item {number} is {what(item)} from {who(sender)}: only its "
                    "sender withdraws it"
                )
                raise InboxError(message)
            case Item(reason=Approval() | HeldChange()):
                message = (
                    f"item {number} is {what(item)}, which the operator answers: it "
                    "isn't withdrawn"
                )
                raise InboxError(message)
            case _:
                message = (
                    f"item {number} no longer waits for the operator: it's "
                    f"{standing(item)}"
                )
                raise InboxError(message)

    async def sent(self, launch: str, text: str, agent: str | None = None) -> Item:
        """Send the operator's message to a conversation of the session `launch` runs: its main one, or its subagent `agent`."""
        conversation = self.main_of(launch).model_copy(update={"agent": agent})
        return await self.posted(
            Message(kind="note", text=text), Operator(), conversation, None
        )

    async def asked(
        self, approval: Approval, diff: str, files: list[ChangedFile], worktree: Path
    ) -> Item:
        """Put an approval in the operator's inbox, its whole diff and each file it changes kept beside it, and raise its notice.

        Where one waits already about the same zone, a launch asking the same
        question meanwhile, that one is returned instead, for this launch to
        wait on too, a push joining it taking the comment on its answer where no
        push asked it before. Each one waiting about another zone of the same
        repository is superseded by it, off the operator's list, and every
        launch waiting on one is woken to ask about the zone at the tip instead.
        """
        joined = self.inbox.asking(approval.repository, approval.fingerprint)
        match joined:
            case Item(reason=Approval(pushed_by=None) as waiting) if (
                approval.pushed_by is not None
            ):
                pushed = waiting.model_copy(update={"pushed_by": approval.pushed_by})
                return self.inbox.kept(joined.model_copy(update={"reason": pushed}))
            case Item():
                return joined
            case None:
                pass
        item = self.inbox.made(
            approval, Operator(), Operator(), worktree, self.clock.now()
        )
        self.inbox.attached(item.number, diff, files)
        replaced = [
            each
            for each in self.inbox.waiting(Operator())
            if isinstance(each.reason, Approval)
            and each.reason.repository == approval.repository
            and each.number != item.number
        ]
        superseded = Superseded(at=self.clock.now(), by=item.number)
        for each in replaced:
            self.inbox.kept(each.model_copy(update={"state": superseded}))
            self.settle(each.number)
            self.say(f"item {each.number}, an approval, is superseded by {item.number}")
        await self.noticed(item)
        return item

    def settle(self, number: int) -> None:
        """Wake every launch waiting on approval `number`, once it's answered or superseded."""
        settling = self.settling.get(number)
        self.settling = {
            each: event for each, event in self.settling.items() if each != number
        }
        if settling is not None:
            settling.set()

    def approval(self, number: int) -> Item:
        """Return item `number`, or say it isn't an approval or a held change."""
        item = self.inbox.item(number)
        if not isinstance(item.reason, Approval | HeldChange):
            message = (
                f"item {number} isn't an approval or a held change, but {what(item)}"
            )
            raise InboxError(message)
        return item

    async def settled(self, number: int) -> Item:
        """Hold until approval `number` is answered, wherever it is, and return it; at once where it's answered already."""
        self.approval(number)
        while isinstance(self.inbox.item(number).state, Waiting):
            if number not in self.settling:
                self.settling = {**self.settling, number: asyncio.Event()}
            await self.settling[number].wait()
        return self.inbox.item(number)

    async def decided(self, number: int, *, approved: bool, comment: str = "") -> Item:
        """Answer approval or held change `number`, yes or no, with the operator's comment; wake every launch waiting on an approval, and write a hold's answer for its hook.

        A comment on an approval a push asked is told to the session that
        pushed (`commented`); a held change's reaches its agent with the hold's
        answer. One answered already keeps its answer, whichever came first,
        and is returned as it stands.
        """
        item = self.approval(number)
        if not isinstance(item.state, Waiting):
            return item
        if isinstance(item.reason, HeldChange):
            if self.settle_hold is None:
                message = (
                    f"item {number} is a held change, which this service can't answer"
                )
                raise InboxError(message)
            self.settle_hold(item.reason, approved, comment)
        decided = Decided(at=self.clock.now(), approved=approved, comment=comment)
        answered = self.inbox.kept(item.model_copy(update={"state": decided}))
        self.settle(number)
        said = "approved" if approved else "declined"
        self.say(f"item {number}, {what(item)}, was {said}")
        match item.reason:
            case Approval(pushed_by=Conversation() as pusher) if comment.strip():
                await self.posted(
                    Message(kind="note", text=commented(answered, comment)),
                    Operator(),
                    pusher,
                    None,
                )
            case _:
                pass
        return answered

    async def held_change(
        self,
        change: HeldChange,
        sender: Conversation,
        diff: str,
        files: list[ChangedFile],
        *,
        call: str | None = None,
    ) -> Item:
        """Put a held change in the operator's inbox from the conversation that made it, its diff and each file held kept beside it, anchored to `call`, and raise its notice."""
        item = self.inbox.made(
            change, sender, Operator(), change.worktree, self.clock.now(), call=call
        )
        self.inbox.attached(item.number, diff, files)
        await self.noticed(item)
        return item
