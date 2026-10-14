"""Telling each conversation what waits in its inbox, once: at its hooks, by a held call, and by starting a turn of its idle session.

`docs/host-tools.md`, *How an agent is told*. Every item waiting for a
conversation is told together, oldest first, by whichever comes first:
- **its next call,** beside it, as the hook's context (`telling`, which the host
  service asks at every hook, the `Post` it's handed);
- **its turn's end,** where some are still waiting: the end is held once, the
  items its reason, so they never hold an end again (`inbox/ends.py`);
- **`wait_inbox`,** or `ask` with `wait`, a call held until something arrives,
  whose result is the items (`held`);
- **its session's start or resumption,** in the start's answer;
- **while it's idle,** where its runtime's adapter spells a way to start a turn
  of an idle session (the courier's `woken`), through the session's own
  messaging socket: only for an item the operator's own act made, and a burst
  of them once, since the turn it starts tells the rest at its first call.
  Where a runtime has no way, the item waits for the session's next call, a gap
  its adapter declares.

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

What the service knows of a conversation while it serves (whether it's idle,
the calls it holds) is in memory: a service started again knows a conversation
idle only once its turn ends again, so an idle session isn't woken until then.
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
    Conversation,
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
    Ruling,
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


def opening(item: Item) -> str:
    """Return an item's first line: its text's, or an answer's comment's."""
    match item.reason:
        case Message(text=text) | Question(text=text):
            said = text
        case Answer(comment=comment):
            said = comment
    return next(iter(said.splitlines()), "")


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
    """What the service knows of a conversation while it serves: whether it's idle, and the calls it holds."""

    idle: bool = False
    """Whether its turn ended, its end let through, with no hook since: a turn
    started in its session reaches it."""
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
                if heard.event == "conversation-ended" and party.agent is not None:
                    self.ended(party)
                presence.idle = party.agent is None
                return Posted()
            case "session-started":
                presence.idle = False
                return self.told(party, room, heard.fits, "start")
            case "call-started" | "call-finished":
                presence.idle = False
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
            case Message(text=text) | Question(text=text):
                return f"{head}{passed}:\n{text}"
            case Answer() as answer:
                return (
                    f"{head}{passed}, to the question of item {answer.question}:\n"
                    f"{self.answered(answer)}"
                )

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
        """Start a turn of `party`'s idle session with everything waiting for it, where its runtime has a way.

        Only a session's main conversation is idle; one that isn't, or whose
        runtime has no way, is told at its next hook. Where the session's
        messaging socket can't be reached, that's said, and the items wait.
        """
        presence = self.presence(party)
        place = self.inbox.whereabouts.get(party.key())
        waiting = self.inbox.waiting(party)
        if not presence.idle or presence.held or place is None or not waiting:
            return
        text = SEPARATOR.join(self.said(item) for item in waiting)
        line = self.courier.woken(party.runtime, party.session, text)
        if line is None:
            return
        socket = self.layout.launch(place.launch).messages
        try:
            _, writer = await asyncio.open_unix_connection(str(socket))
            writer.write(f"{line}\n".encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except OSError as unreached:
            self.say(
                f"{place.launch}: {who(party)} wasn't woken through {socket}, so "
                f"what waits for it is told at its next call: {unreached}"
            )
            return
        presence.idle = False
        self.whole(party, "wake")
        self.say(f"{place.launch}: woke {who(party)} with {len(waiting)} items")

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
        """Answer the question item `number`: the answer an item for the conversation that asked, the question answered.

        Refused where it isn't a question waiting; where its decisions aren't
        each ruled once, or a plain question has no words for its answer.
        """
        item = self.inbox.item(number)
        match item:
            case Item(
                reason=Question(decisions=decisions),
                state=Waiting(),
                sender=Conversation() as asker,
            ):
                pass
            case _:
                message = f"item {number} isn't a question waiting for an answer"
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
            case Item(reason=Question(), state=Waiting()):
                message = (
                    f"item {number} is a question: answer it, `lup-dev inbox answer "
                    f"{number}`"
                )
                raise InboxError(message)
            case _:
                message = f"item {number} isn't a message waiting in your inbox"
                raise InboxError(message)

    async def sent(self, launch: str, text: str) -> Item:
        """Send the operator's message to the main conversation of the session `launch` runs."""
        return await self.posted(
            Message(kind="note", text=text), Operator(), self.main_of(launch), None
        )
