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
- **through its session's own messaging socket,** where its runtime's adapter
  spells a way (the courier's `woken`), for an item the operator's own act
  made: at once, unless a call of its is running, whose hook comes soon. An
  idle session starts a turn with it, a busy one takes it at its next
  boundary, so the service needn't know which: a session just started, one
  interrupted, and every one after the service starts again are reached. A
  burst is written once, since the turn it starts tells the rest at its first
  call. Where a runtime has no way, the item waits for the session's next
  call, a gap its adapter declares.

**Told once.** An item is told when it's written into a hook's answer, a held
call's result or the messaging socket, and never again:
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
launch waiting on it; an answer after that changes nothing.

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
    Comment,
    Conversation,
    Decided,
    Done,
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
        case Review():
            return "a review"


def opening(item: Item) -> str:
    """Return an item's first line: its text's, an answer's comment's, or a review's first comment's."""
    match item.reason:
        case Message(text=text) | Question(text=text) | Approval(text=text):
            said = text
        case Answer(comment=comment):
            said = comment
        case Review(comments=comments):
            said = next((each.text for each in comments), "")
    return next(iter(said.splitlines()), "")


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

    calling: bool = False
    """Whether a call of its started and hasn't finished: its next hook comes
    soon, and tells what waits."""
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
                presence.calling = False
                for each in presence.held:
                    each.ended = True
                fresh = [
                    item for item in self.inbox.waiting(party) if not announced(item)
                ]
                if holding(fresh, [], after_block=heard.after_block):
                    posted = self.told(party, room, heard.fits, "turn's end")
                    if posted.items:
                        return posted
                if heard.event == "conversation-ended" and party.agent is not None:
                    self.ended(party)
                return Posted()
            case "session-started":
                presence.calling = False
                return self.told(party, room, heard.fits, "start")
            case "call-started" if heard.served:
                presence.calling = True
                return Posted()
            case "call-started":
                presence.calling = True
                return self.told(party, room, heard.fits, "call")
            case "call-finished":
                presence.calling = False
                return self.told(party, room, heard.fits, "call")

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
            case Message(text=text) | Question(text=text) | Approval(text=text):
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
        """Say a review to the conversation it's for: each of its items it covers, with the operator's comments on it."""

        def part(number: int) -> str:
            item = self.inbox.item(number)
            whose = "yours" if item.sender == recipient else f"from {who(item.sender)}"
            head = f'On item {number}, {what(item)} {whose} ("{opening(item)}"):'
            said = [remark(each) for each in review.comments if each.item == number]
            return "\n".join([head, *(said or ["  (read, with nothing to add)"])])

        return "\n\n".join(part(each) for each in review.covers)

    async def reviewed(self) -> list[Item]:
        """Send the operator's draft: to each conversation whose items it covers, a review of those items with the comments on them alone; those items answered or done, and the draft left with what's parked.

        A message only marked done, with nothing to say on it, is taken off the
        list and its sender told nothing; a question is answered all the same,
        since its asker may be holding for the answer. Refused where the draft
        covers no item, or covers one no conversation sent.
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
        commented = [each.item for each in draft.comments]
        read = [
            item
            for item in covered
            if item.number not in commented and isinstance(item.reason, Message)
        ]
        for item in read:
            self.inbox.kept(item.model_copy(update={"state": Done(at=at)}))
        answering = [item for item in covered if item not in read]
        senders = [item.sender for item in answering]
        recipients = [
            each for at, each in enumerate(senders) if each not in senders[:at]
        ]

        def sent_to(recipient: Party) -> Item:
            own = [item for item in answering if item.sender == recipient]
            numbers = [item.number for item in own]
            review = Review(
                covers=numbers,
                comments=[each for each in draft.comments if each.item in numbers],
            )
            sent = self.inbox.made(review, Operator(), recipient, None, at)
            for item in own:
                settling = settled(item, sent, at)
                self.inbox.kept(item.model_copy(update={"state": settling}))
            return sent

        made = [sent_to(each) for each in recipients]
        self.inbox.drafted(draft.kept())
        for sent in made:
            await self.delivered(sent)
        return made

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
            comment = f" They add: {ruling.comment}" if ruling.comment else ""
            return (
                f"{ruling.decision}. {decision.text} (lean: {decision.lean}): "
                f"{ruled(ruling.verdict)}.{comment}"
            )

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
        self, reason: Reason, sender: Party, recipient: Party, worktree: Path | None
    ) -> Item:
        """Make an item and deliver it (`delivered`)."""
        item = self.inbox.made(reason, sender, recipient, worktree, self.clock.now())
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
        """Write everything waiting for `party`'s session to its messaging socket, unless a call of its is running, where its runtime has a way.

        Only a session's main conversation is woken. A call of its running
        (`Presence.calling`) means a hook comes soon and tells it there; a call
        it holds is given it; a wake since its last hook started a turn whose
        first call tells it; and a runtime with no way waits for its next hook.
        Otherwise it's written to the socket whatever the service knows of the
        session: just started, idle, generating, or unknown since the service
        started again or since the operator interrupted it. An idle session
        starts a turn with it, and a busy one takes it at its next boundary, as
        measured on the runtime that has a way (`docs/field-notes.md`, *Waking
        a session*). What the wake tells is counted told before it's written,
        so a hook meanwhile doesn't tell it again; where the session's messaging
        socket can't be reached, that's said, and the items wait again.
        """
        presence = self.presence(party)
        place = self.inbox.whereabouts.get(party.key())
        waiting = self.inbox.waiting(party)
        quiet = presence.calling or presence.woken or presence.held
        if party.agent is not None or quiet or place is None or not waiting:
            return
        text = SEPARATOR.join(self.said(item) for item in waiting)
        line = self.courier.woken(party.runtime, party.session, text)
        if line is None:
            return
        told = Told(at=self.clock.now(), how="wake")
        for item in waiting:
            self.inbox.kept(item.model_copy(update={"state": told}))
        presence.woken = True
        socket = self.layout.launch(place.launch).messages
        try:
            _, writer = await asyncio.open_unix_connection(str(socket))
            writer.write(f"{line}\n".encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except OSError as unreached:
            self.returned(Posted(numbers=[item.number for item in waiting]))
            self.say(
                f"{place.launch}: {who(party)} wasn't woken through {socket}, so "
                f"what waits for it is told at its next call: {unreached}"
            )
            return
        numbers = ", ".join(str(item.number) for item in waiting)
        self.say(f"{place.launch}: woke {who(party)}, telling items {numbers}")

    def main_of(self, launch: str) -> Conversation:
        """Return the main conversation of the session `launch` runs, the latest heard there."""
        found = [
            place
            for place in self.inbox.whereabouts.values()
            if place.launch == launch and place.conversation.agent is None
        ]
        if not found:
            message = (
                f"no session of launch `{launch}` has reached lup yet, so nothing "
                "there can be told"
            )
            raise InboxError(message)
        return max(found, key=lambda place: place.since).conversation

    async def answer(self, number: int, rulings: list[Ruling], comment: str) -> Item:
        """Answer the question item `number`, or reply to the message: the answer an item for the conversation that sent it.

        A question is answered; a message is replied to (`replied`). Refused
        where it's neither a question waiting nor a conversation's message;
        where a question's decisions aren't each ruled once, or a plain question
        has no words for its answer.
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
                "verdict (`leaning`, `undecided` or `leave open`); these were given "
                f"for {given or 'none'}"
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
            case Item(reason=Question() | Approval(), state=Waiting()):
                message = (
                    f"item {number} is {what(item)}: answer it, `lup-dev inbox answer "
                    f"{number}`"
                )
                raise InboxError(message)
            case _:
                message = f"item {number} isn't a message waiting in your inbox"
                raise InboxError(message)

    async def sent(self, launch: str, text: str, agent: str | None = None) -> Item:
        """Send the operator's message to a conversation of the session `launch` runs: its main one, or its subagent `agent`."""
        conversation = self.main_of(launch).model_copy(update={"agent": agent})
        return await self.posted(
            Message(kind="note", text=text), Operator(), conversation, None
        )

    async def asked(self, approval: Approval, diff: str, worktree: Path) -> Item:
        """Put an approval in the operator's inbox, its whole diff kept beside it, and raise its notice.

        Where one waits already about the same zone, a launch asking the same
        question meanwhile, that one is returned instead, for this launch to
        wait on too. Each one waiting about another zone of the same repository
        is superseded by it, off the operator's list, and every launch waiting on
        one is woken to ask about the zone at the tip instead.
        """
        joined = self.inbox.asking(approval.repository, approval.fingerprint)
        if joined is not None:
            return joined
        item = self.inbox.made(
            approval, Operator(), Operator(), worktree, self.clock.now()
        )
        self.inbox.attached(item.number, diff)
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
        """Return item `number`, or say it isn't an approval."""
        item = self.inbox.item(number)
        if not isinstance(item.reason, Approval):
            message = f"item {number} isn't an approval, but {what(item)}"
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

    def decided(self, number: int, *, approved: bool) -> Item:
        """Answer approval `number`, yes or no, and wake every launch waiting on it.

        One answered already keeps its answer, whichever came first, and is
        returned as it stands.
        """
        item = self.approval(number)
        if not isinstance(item.state, Waiting):
            return item
        decided = Decided(at=self.clock.now(), approved=approved)
        answered = self.inbox.kept(item.model_copy(update={"state": decided}))
        self.settle(number)
        said = "approved" if approved else "declined"
        self.say(f"item {number}, an approval, was {said}")
        return answered
