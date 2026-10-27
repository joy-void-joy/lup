"""The inbox's tools in a launched session: the speaking tools, `ask`, `send`, `wait_inbox`, `inbox` and `withdraw`.

`docs/inbox.md`, *lup's tools*. Each is a function of the conversation
calling (`Speaker`), served as a `RoomTools` through the launch's `mcp.sock`:
- `blocked`, `stop`, `note`, `friction` and `how_it_went` are the library's
  speaking tools (`lup.tools.speaking`), their names and input models taken
  from them, so an agent's habit carries between an ask from code and a
  launched session; their functions and descriptions are the inbox's, since
  in a launched session whoever asked is the operator, and each lands in their
  inbox, a subagent's too; a subagent's `friction` and `how_it_went` reach its
  parent as well, whole and quiet (`Item.quiet`), so it can file what got in
  the way, or learn its brief misled;
- `ask` puts a question to the operator, its decisions numbered, each with the
  agent's lean; with `wait` it holds until they answer, or until other news of
  theirs reaches the agent, their words typed in its terminal among it;
- `send` is the inbox's general verb, a message of a kind to a party's inbox:
  the operator's, the conversation's parent's, or one of its own subagents',
  each by a name the conversation knows it by, the operator reading a copy of
  a message between conversations; one whom nothing would read is refused;
- `wait_inbox` holds until something reaches the agent: an item of its inbox,
  one of its own subagents' ends among it, or what its runtime holds for it,
  the operator's typed words and its background tasks among it, where the
  runtime's records say. `on` narrows it to whose news (`Waking`), the
  operator's always among it, and `within` limits how long it holds. It isn't
  called `wait`, a name a runtime has for a tool of its own;
- `inbox` reads the inbox of the agent's repository, changing nothing: each
  item in a line or whole, the latest up to the call's `limit`, narrowed by
  `since` and `until` as `judged` is (`lup_dev.listing`), by kind, and to one
  conversation's exchange, as `lup-dev inbox` reads it (`inbox/reading.py`);
  and the agent's own item read whole;
- `withdraw` takes back a message or question the agent sent that the
  operator needn't see, with its reason: the agent's workflow is its own;
- `edit` changes what the agent sent the operator: a passage of its text, or
  its text whole (`docs/inbox.md`, *Editing what was sent*).

What an agent writes the operator may cite their words inline (`docs/inbox.md`,
*Citing the operator's words*): each call's answer says which citations named
no one passage, and the places they might mean, so the agent fixes them with
`edit` (`said`).

A tool's docstring's first line is its summary, 50 characters at most, which the
guidance lists (`launch/guidance.py`); the rest is its description, which the
runtime's tool search finds. Each answers in words, as `content`.
"""

import inspect
from datetime import timedelta
from typing import TYPE_CHECKING, override

from pydantic import Field, JsonValue

import lup
from lup.doors import bound
from lup.tools import speaking
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, AgentTool, Refused, ToolSpec
from lup.types import Model
from lup_dev.host.names import Names
from lup_dev.host.protocol import Register
from lup_dev.host.rooms import RoomTools
from lup_dev.inbox.citations import unresolved
from lup_dev.inbox.delivery import (
    Delivery,
    Waking,
    body,
    clocked,
    standing,
    what,
    who,
    whose,
)
from lup_dev.inbox.parts import PartId
from lup_dev.inbox.reading import Narrowing, Reader
from lup_dev.inbox.store import (
    Answered,
    Conversation,
    Decision,
    Friction,
    HowItWent,
    InboxError,
    Item,
    Kind,
    Message,
    Operator,
    Party,
    Question,
    Stop,
    cited,
)
from lup_dev.inbox.tags import Tag, inside
from lup_dev.inbox.threads import parts_of, spoken

if TYPE_CHECKING:
    from lup.sessions import results
    from lup.tools.speaking import Problem, Remark
    from lup_dev.host.courier import Conversation as Caller


class Said(Model):
    """What a call to one of the inbox's tools says back, in words."""

    text: str


class Choice(Model):
    """One decision a question asks, with your lean."""

    decision: str = Field(description="What's to decide, in a line.")
    lean: str = Field(description="Which way you lean, and why, in a line or two.")


class Asking(Model):
    """A question for the operator."""

    question: str = Field(
        description="What you ask, with what the operator needs to answer it."
    )
    decisions: list[Choice] = Field(
        default=[],
        description=(
            "The decisions it asks, numbered from 1 in this order, each with your "
            "lean; none for a question answered in words."
        ),
    )
    wait: bool = Field(
        default=False,
        description=(
            "Hold this call until the operator answers, and return the answer; "
            "without it, the call returns at once and the answer reaches you at a "
            "later call."
        ),
    )


class Sending(Model):
    """A message to a party's inbox."""

    to: str = Field(
        description=(
            "Whose inbox: `operator`; `parent`, the conversation that spawned you; "
            "or one of your own subagents, by its name as lup calls it "
            "(`explore-auth`), its path (`dev/explore-auth`), or its runtime's id."
        )
    )
    kind: Kind = Field(
        description=(
            "What it is: a `note`, a `problem`, a `disagreement`, or a `question` "
            "that asks for no answer you wait on."
        )
    )
    text: str = Field(description="The message, in full.")


class Awaiting(Model):
    """Whose news ends the wait, beside the operator's, and how long it may hold."""

    on: list[Waking] = Field(
        default=["operator", "agents", "tasks"],
        description=(
            "Whose news ends it: `operator`, their answers, reviews and messages "
            "through lup, and their words typed in your terminal; `agents`, a "
            "message from your parent or one of your subagents, a subagent's end, "
            "what one says of its work, another session's message; `tasks`, a "
            "command you run in the background ending, or a Monitor's event. All "
            "three by default. The operator's news ends it whatever this says: "
            '`["operator"]` waits on theirs alone, and `["tasks"]` on your '
            "background work and the operator."
        ),
    )
    within: timedelta | None = Field(
        default=None,
        description=(
            "How long it may hold, as an ISO 8601 duration such as `PT10M`, after "
            "which it returns saying nothing came: for a wait on what nothing here "
            "reports. Left out, it holds until something comes."
        ),
    )


class Reading(Narrowing):
    """What of the inbox to read."""

    number: int | None = Field(
        default=None,
        description=(
            "An item to read whole, by its number (270 for `@270`): any of this "
            "repository's, as it was told where the operator or another "
            "conversation sent it to you, else as its sender wrote it. Left out, "
            "the items are listed."
        ),
    )
    part: str | None = Field(
        default=None,
        description=(
            "One part to read alone, by its id (`414.3`): of an item a "
            "conversation sent, one of its Markdown blocks; of the operator's, "
            "their words there: a comment, a message, a remark. With it, "
            "`number` is left out."
        ),
    )


class Editing(Model):
    """An edit of an item you sent the operator."""

    number: int = Field(
        description="The item's number, as its tool's answer cited it: 270 for `@270`."
    )
    old: str | None = Field(
        default=None,
        description=(
            "A passage of its text to replace, exactly as it stands there, found "
            "there once. Left out, `new` is its text whole."
        ),
    )
    new: str = Field(
        description="What replaces `old`; with no `old`, the item's text whole."
    )


class Withdrawing(Model):
    """An item of yours to take back."""

    number: int = Field(
        description="The item's number, as its tool's answer cited it: 270 for `@270`."
    )
    why: str = Field(
        description="Why it no longer needs the operator, in a line: they read it."
    )


class Speaker(Model, arbitrary_types_allowed=True):
    """One conversation of a launch, speaking through lup's inbox: each tool's function, bound to it."""

    delivery: Delivery
    launch: Register
    party: Conversation
    call: str | None = None
    """The runtime's id for the call speaking, which each item it makes keeps."""

    async def said(
        self, reason: Message | Friction | HowItWent | Stop | Question
    ) -> Item:
        """Put `reason` in the operator's inbox, from this conversation, and return it as kept, its citations of their words read (`Delivery.cited`)."""
        return await self.delivery.posted(
            reason, self.party, Operator(), self.launch.worktree, call=self.call
        )

    @staticmethod
    def answered(text: str, item: Item) -> Said:
        """Answer a call with `text`, then which citations of the operator's words in `item`, the item it made, name no one passage, where any doesn't (`unresolved`)."""
        told = unresolved(item.citations, item.number)
        return Said(text=text if not told else f"{text}\n\n{inside(told)}")

    async def passed_up(self, reason: Friction | HowItWent) -> bool:
        """Put a copy of `reason` in the inbox of the conversation that spawned this one, quietly (`Item.quiet`), and say whether there's one."""
        parent = self.delivery.parent(self.party)
        if parent is None:
            return False
        await self.delivery.posted(
            reason,
            self.party,
            parent,
            self.launch.worktree,
            call=self.call,
            quiet=True,
        )
        return True

    async def blocked(self, said: Problem) -> Said:
        """Say the work can't go on, and what's wrong.

        Call it when the work can't go on: the task can't be done as asked,
        something you need is missing, or an instruction seems wrong. Say what's
        wrong, and what would let the work go on. It lands in the operator's
        inbox as a problem, and they're notified. Then end your turn. To end
        your work by your own choice instead, it's `stop`.
        """
        item = await self.said(Message(kind="problem", text=said.problem))
        return self.answered(
            f"Your problem is with the operator, {cited(item.number)}. End your turn.",
            item,
        )

    async def stop(self, said: speaking.Stop) -> Said:
        """End your work by your own choice, saying why.

        When the work is done and nothing more is worth doing, or when you'd
        rather not go on with it: both are yours to choose. Say why. It lands in
        the operator's inbox, never your parent's. Then end your turn. Where the
        work can't go on, it's `blocked`.
        """
        item = await self.said(Stop.model_validate(said.model_dump()))
        return self.answered(
            f"Your stop is with the operator, {cited(item.number)}. End your turn.",
            item,
        )

    async def note(self, said: Remark) -> Said:
        """Tell the operator a doubt, and carry on.

        An assumption your work rests on, a doubt, or a counterargument the
        operator should weigh. It lands in their inbox as a note, news they
        read when they come to it, raising no notice, and your work goes on:
        nothing waits for an answer. A premise that seems wrong, or anything
        that needs their eyes soon, is an `ask`, which waits on them and
        notifies them.
        """
        item = await self.said(Message(kind="note", text=said.remark))
        return self.answered(
            f"Your note is with the operator, {cited(item.number)}. Carry on.", item
        )

    async def friction(self, said: results.Friction) -> Said:
        """Say what got in your way, and carry on.

        Call it the moment something gets in the way of the work, whatever it
        is, in your own words. Where there's a command and the message it
        gave, the exact ones help whoever fixes it. It lands in the operator's
        inbox as you wrote it, and, where you're a subagent, in your parent's
        too, whole, at its next call. Your work goes on: nothing waits for an
        answer. A doubt about the work itself is a `note`.
        """
        friction = Friction.model_validate(said.model_dump())
        item = await self.said(friction)
        parent = " and your parent" if await self.passed_up(friction) else ""
        return self.answered(
            f"Your friction is with the operator, {cited(item.number)}{parent}. "
            "Carry on.",
            item,
        )

    async def how_it_went(self, said: results.HowItWent) -> Said:
        """Tell the operator how the work went and felt.

        Call it once, near the end of a piece of work: how it went and how it
        felt, whatever's present for you, in your own words. "Nothing notable"
        is a fine answer. It lands in the operator's inbox as you wrote it,
        and, where you're a subagent, in your parent's too, whole, at its next
        call. Your work goes on.
        """
        went = HowItWent.model_validate(said.model_dump())
        item = await self.said(went)
        parent = " and your parent" if await self.passed_up(went) else ""
        return self.answered(
            f"How it went is with the operator, {cited(item.number)}{parent}.", item
        )

    def asked(self) -> int | None:
        """Return the number of the question this call made already, where the call is one sent again across a restart of the service: a question from this conversation anchored to the call's id (`Item.call`); none where there's none, or the call carries no id."""
        if self.call is None:
            return None
        return next(
            (
                item.number
                for item in self.delivery.inbox.about(self.party.repository)
                if item.sender == self.party
                and item.call == self.call
                and isinstance(item.reason, Question)
            ),
            None,
        )

    @lup.tool(idempotent=True)
    async def ask(self, asked: Asking) -> Said:
        """Ask the operator, with numbered decisions.

        For a decision that's the operator's. List its decisions, each with your
        lean: they're numbered in order, and the operator answers each
        "leaning" (they go with your lean), "undecided" or "leave open", with a
        comment, or in their own words; or ask a plain question, answered in
        words. With `wait`, this call holds until they answer and
        returns the answer, which may take hours; or until other news of theirs
        reaches you, a message or their words typed in your terminal, which it
        returns or says, the question still open. Without it, the call returns
        at once, and the answer reaches you at a later call, or through
        `wait_inbox`.
        """
        question = Question(
            text=asked.question,
            decisions=[
                Decision(text=choice.decision, lean=choice.lean)
                for choice in asked.decisions
            ],
        )
        found = self.asked()
        item = (
            await self.said(question)
            if found is None
            else self.delivery.inbox.item(found)
        )
        number = item.number
        if not asked.wait:
            return self.answered(
                f"Your question is with the operator, {cited(number)}. Their answer "
                "reaches you at a later call; `wait_inbox` waits for it.",
                item,
            )

        inbox = self.delivery.inbox

        def answered() -> bool:
            return isinstance(inbox.item(number).state, Answered) or any(
                whose(each) == "operator" for each in inbox.waiting(self.party)
            )

        told = await self.delivery.held(self.party, answered, on=["operator"])
        if not isinstance(inbox.item(number).state, Answered):
            return self.answered(
                f"{told}\n\nYour question {cited(number)} is still open: its answer "
                "reaches you at a later call; `wait_inbox` waits for it.",
                item,
            )
        return self.answered(
            told
            or (
                f"The operator answered {cited(number)}; their answer was told to you "
                "beside another call."
            ),
            item,
        )

    @lup.tool
    async def send(self, sending: Sending) -> Said:
        """Send a message to a party's inbox.

        A message of a kind: a `note`, a `problem`, a `disagreement`, or a
        `question` asking for no answer you wait on (a decision of the
        operator's is `ask`'s). To the operator, a note is news, raising no
        notice, as `note`'s is; the other kinds wait on them.

        To your parent, the conversation that spawned you, or to one of your
        own subagents: the moment something changes the work, such as a
        brief found wrong on what matters, rather than at the end. It's told
        to them at their next call, their turn's end or their `wait_inbox`,
        whichever comes first, and an idle session is woken for it where its
        runtime can be; the answer says which. The operator reads a copy, as
        news. One that has ended, or isn't yours, is refused, saying why.
        Nothing holds: your work goes on.
        """
        try:
            recipient = self.addressed(sending.to)
        except InboxError as unreached:
            return Said(text=f"Not sent: {unreached}")
        message = Message(kind=sending.kind, text=sending.text)
        match recipient:
            case Operator():
                item = await self.said(message)
                return self.answered(
                    f"Your message is with the operator, {cited(item.number)}.", item
                )
            case Conversation():
                item = await self.delivery.posted(
                    message,
                    self.party,
                    recipient,
                    self.launch.worktree,
                    call=self.call,
                )
                copy = await self.said(message.model_copy(update={"to": recipient}))
                return self.answered(
                    self.arriving(recipient, item.number, copy.number), copy
                )

    def addressed(self, to: str) -> Party:
        """Return the party `to` names for this conversation: the operator, its parent, or one of its own subagents, by its name, its path or its runtime's id.

        Raise `InboxError` where it names none, or one nothing reads: no
        parent, a subagent that isn't this conversation's own, or one that
        ended, whose inbox no call reads until its runtime resumes it.
        """
        match to:
            case "operator":
                return Operator()
            case "parent":
                parent = self.delivery.parent(self.party)
                if parent is None:
                    message = (
                        "no conversation spawned you, so you have no parent. "
                        f"{self.yours()}"
                    )
                    raise InboxError(message)
                return self.reachable(parent, "your parent")
            case _:
                found = next(
                    (
                        each.conversation
                        for each in self.delivery.subagents(self.party)
                        if to in self.calls(each.conversation)
                    ),
                    None,
                )
                if found is None:
                    message = f"no subagent of yours is `{to}`. {self.yours()}"
                    raise InboxError(message)
                return self.reachable(found, "your subagent")

    def calls(self, conversation: Conversation) -> list[str]:
        """Return what `send` takes a subagent by: its own name and its path, as `inbox` reads them (`Reader`), and its runtime's id."""
        reader = Reader(
            delivery=self.delivery,
            reader=self.party,
            names=Names(path=self.delivery.layout.names).all(),
        )
        items = self.delivery.inbox.about(self.party.repository)
        said = [
            reader.own(conversation, items),
            reader.path(conversation, items),
            conversation.agent,
        ]
        return [each for each in said if each is not None]

    def called(self, conversation: Conversation) -> str:
        """Name `conversation` for this one, in an answer of `send`'s: by the name lup calls it by, a subagent with none by its runtime's id."""
        return (
            self.delivery.called(conversation)
            or conversation.agent
            or who(conversation)
        )

    def reachable(self, conversation: Conversation, whose: str) -> Conversation:
        """Return `conversation`, `whose` it is to this one, where a call of its can still read its inbox; raise `InboxError` where it ended, saying when."""
        place = self.delivery.inbox.whereabouts.get(conversation.key())
        if place is None or place.ended is None:
            return conversation
        message = (
            f"{whose} `{self.called(conversation)}` "
            f"ended at {clocked(place.ended)}, so nothing reads its inbox: once its "
            "runtime resumes it, lup hears it again and it can be sent to"
        )
        raise InboxError(message)

    def yours(self) -> str:
        """Say whom `send` reaches from this conversation, its own subagents each by its name, for a refusal."""
        parent = [] if self.delivery.parent(self.party) is None else ["`parent`"]
        spawned = [
            f"`{each.name or each.conversation.agent}`"
            + ("" if each.ended is None else f" (ended at {clocked(each.ended)})")
            for each in self.delivery.subagents(self.party)
        ]
        theirs = ", ".join(spawned) if spawned else "none lup has heard"
        return (
            f"`to` takes {', '.join(['`operator`', *parent])}, or one of your own "
            f"subagents by its name, its path or its runtime's id: {theirs}."
        )

    def arriving(self, recipient: Conversation, number: int, copy: int) -> str:
        """Say where message `number` to `recipient`, another conversation, is, and how it'll be told, with the number of the operator's `copy`."""
        whose = (
            "your parent"
            if recipient == self.delivery.parent(self.party)
            else "your subagent"
        )
        return (
            f"Your message is in the inbox of {whose} `{self.called(recipient)}`, "
            f"{cited(number)}, "
            f"and the operator has a copy, {cited(copy)}. It's told at its next "
            "call, its turn's end or its `wait_inbox`, whichever comes first"
            f"{self.idle(recipient)}."
        )

    def idle(self, recipient: Conversation) -> str:
        """Say what an item for `recipient` does while its session is idle between turns, for `arriving`: nothing for a subagent, which is never woken; else wake it, where its runtime can be."""
        if recipient.agent is not None:
            return ""
        if self.delivery.wakes(recipient):
            return "; idle between turns, its session is woken for it"
        return (
            "; idle between turns, it waits for the session's next turn, since its "
            "runtime can't be woken"
        )

    @lup.tool(idempotent=True)
    async def wait_inbox(self, awaiting: Awaiting) -> Said:
        """Wait until something reaches you.

        Holds this call until news reaches you, and returns everything
        waiting in your inbox, each whole (what a hook announced as too long
        to tell is read here), and says what your runtime holds for you,
        which it hands you as the call returns. Whose news ends it, as `on`
        says, all three by default:
        - `operator`: their answer, review or message through lup, and their
          words typed in your terminal;
        - `agents`: a message your parent or one of your subagents sent you;
          one of your own subagents ending its turn, stopped, or failed on an
          error from the model's API, which names it; a subagent's `friction`
          or `how_it_went`; another session's message;
        - `tasks`: a command you run in the background ending, or a Monitor's
          event.

        Whatever `on` says, the operator's news ends it: `["operator"]` waits
        on theirs alone, and `["tasks"]`, waiting on your background work,
        still returns for their words. `within` returns after a time, saying
        nothing came. Something already waiting, a subagent that ended since
        your last call among it, is returned at once; each is told once, here
        or beside another call.

        It doesn't return for another session's or another conversation's
        subagents, nor the operator marking something read; nor for a subagent
        stopped or failing where its runtime doesn't report that, as some
        don't. A subagent's call doesn't return for the words the operator
        types to its session's main conversation. Where your runtime's records
        don't say what it holds for you, as one runtime's don't, only your
        inbox ends it, beside `within`.
        """
        inbox = self.delivery.inbox
        on: list[Waking] = [*awaiting.on, "operator"]

        def arrived() -> bool:
            return any(whose(each) in on for each in inbox.waiting(self.party))

        told = await self.delivery.held(
            self.party, arrived, on=on, within=awaiting.within
        )
        return Said(text=told)

    @lup.tool(reads=True)
    async def inbox(self, reading: Reading) -> Said:
        """Read this repository's inbox, changing nothing.

        Lists the items about this repository, oldest first, a line each: its
        number, when it was made, what it is, from whom to whom, where it
        stands, and its first line; each conversation's flagged writes in one
        line, with how many files and on which branches. Those still waiting,
        for the operator or for an agent, by default; every one with `every`.
        `since` and `until` narrow them by when each was made, `kinds` by what
        they are, and `limit` says how many to list, the latest: where it
        leaves earlier ones out, or `every` would list more, the answer says
        how many and what reads them.

        `conversation` reads one conversation's exchange, by its name or its
        id: what it sent, to the operator above all, and what it was sent,
        with its subagents' where `subagents` asks. With `whole`, each item is
        read whole, the operator's words on one of the conversation's under
        it, and its turn's end saying which of theirs it answers, so the
        exchange reads as one thread: how a session reads what an earlier one
        said and was told. Given an item's `number`, any of this repository's, it's read
        whole. It marks nothing read and answers nothing: what reaches you
        still comes through `wait_inbox` and beside your calls.
        """
        items = self.delivery.inbox.about(self.party.repository)
        if reading.part is not None:
            try:
                wanted = PartId.parsed(reading.part)
            except ValueError as unread:
                return Said(text=f"Not read: {unread}")
            return Said(text=self.part(wanted, items))
        if reading.number is not None:
            return Said(text=self.whole(reading.number, items))
        reader = Reader(
            delivery=self.delivery,
            reader=self.party,
            names=Names(path=self.delivery.layout.names).all(),
            where=" about this repository",
        )
        return Said(text=reader.read(items, reading).text)

    @lup.tool
    async def withdraw(self, withdrawing: Withdrawing) -> Said:
        """Take back an item the operator needn't see.

        A message or a question you sent that still waits for them: one that's
        settled, an answer you found yourself, or a plan that changed. It
        leaves their review and their list; shown, it says it was withdrawn,
        and why. What's answered, read or done already stays as it is.
        """
        try:
            self.delivery.withdrawn(withdrawing.number, self.party, withdrawing.why)
        except InboxError as kept:
            return Said(text=f"Not withdrawn: {kept}")
        return Said(
            text=f"{cited(withdrawing.number)} is withdrawn, off the operator's list."
        )

    def whole(self, number: int, items: list[Item]) -> str:
        """Say item `number` of `items` whole: as it was told, where it was sent to this conversation, or where the operator sent it, to whom it was for; as it was written, its Markdown blocks each with its id, where a conversation sent it, this one or another. One not among them is said and not read."""
        item = next((each for each in items if each.number == number), None)
        if item is None:
            return (
                f"{cited(number)} isn't among this repository's: `inbox` reads this "
                "repository's items alone."
            )
        if self.party in (item.recipient, item.addressed):
            return f"{self.delivery.said(item)}\n\nIt's {standing(item)}."
        sent = (
            f"you sent to {who(item.recipient)}"
            if item.sender == self.party
            else f"from {who(item.sender)} to {who(item.recipient)}"
        )
        match item.sender:
            case Conversation():
                said = "\n".join(
                    Tag(
                        name="part",
                        attributes={"id": each.id.said()},
                        parts=[each.text],
                    ).written()
                    for each in parts_of(item, body(item))
                )
            case Operator():
                said = self.delivery.said(item)
        return (
            f"{cited(number)}, {what(item)} {sent} at {clocked(item.made)}, "
            f"{standing(item)}:\n{said}"
        )

    def part(self, wanted: PartId, items: list[Item]) -> str:
        """Say part `wanted` of its item, any of `items`: a block of an item a conversation sent, as a `<part>` tag; the operator's words there in one of theirs (`spoken`), as the item's tag carried them, saying the item of the agent's it's on, or whom it was written to; a reply copies before kept on it, as `<reply>`. One that isn't there is said."""
        item = next((each for each in items if each.number == wanted.item), None)
        if item is None:
            return self.whole(wanted.item, items)
        if isinstance(item.sender, Conversation):
            found = next(
                (each for each in parts_of(item, body(item)) if each.id == wanted), None
            )
            if found is None:
                return f"{cited(wanted.item)} has no part {wanted.cited()}."
            return Tag(
                name="part", attributes={"id": wanted.said()}, parts=[found.text]
            ).written()
        anchor = next((each for each in spoken(item) if each.id == wanted), None)
        if anchor is not None:
            where = (
                {"on": str(anchor.item)}
                if anchor.item is not None
                else {"to": who(anchor.to)}
                if anchor.to is not None
                else {}
            )
            return Tag(
                name="part",
                attributes={"id": wanted.said(), **where},
                parts=[anchor.text],
            ).written()
        reply = next(
            (each for each in item.replies if each.number == wanted.part), None
        )
        if reply is not None:
            return Tag(
                name="reply",
                attributes={"id": wanted.said(), "to": reply.to.said()},
                parts=[reply.text],
            ).written()
        return f"{cited(wanted.item)} has no part {wanted.cited()}."

    @lup.tool
    async def edit(self, editing: Editing) -> Said:
        """Edit what you sent the operator.

        A message, a note, your turn's last words, a question's text, a
        friction, how it went or a stop: one you sent the operator, by its
        number. Give `old`, a passage of its text exactly as it stands, found
        there once, and `new`, what replaces it, as a file's edit does; or
        `new` alone, its text whole. They see it marked edited, with what
        changed, and it comes back before them where they'd read it. Its
        citations of their words are read again, and the answer says any that
        still don't name one passage. A question they answered, or what you
        withdrew, isn't edited: `send` what changed.
        """
        try:
            item = await self.delivery.edited(
                editing.number, self.party, editing.old, editing.new
            )
        except InboxError as refused:
            return Said(text=f"Not edited: {refused}")
        return self.answered(
            f"{cited(item.number)} is edited, and before the operator.", item
        )

    def tools(self) -> list[AgentTool]:
        """Return the inbox's tools, each calling this conversation's function: the speaking tools, as the library serves them, then the inbox's own, as declared (`bound`)."""
        functions = {
            speaking.blocked.name: self.blocked,
            speaking.stop.name: self.stop,
            speaking.note.name: self.note,
            speaking.friction.name: self.friction,
            speaking.how_it_went.name: self.how_it_went,
        }
        speaking_tools = [
            tool.model_copy(
                update={
                    "description": inspect.getdoc(functions[tool.name]),
                    "function": functions[tool.name],
                }
            )
            for tool in [
                speaking.blocked,
                speaking.stop,
                speaking.note,
                speaking.friction,
                speaking.how_it_went,
            ]
        ]
        return [*speaking_tools, *bound(self)]


def specs() -> list[ToolSpec]:
    """Return what a session is told about each of the inbox's tools.

    They don't depend on who calls, so they're read from a speaker made without
    its fields, as `Request.named` reads a kind.
    """
    return [tool.spec() for tool in Speaker.model_construct().tools()]


class InboxTools(Model, RoomTools, arbitrary_types_allowed=True):
    """The inbox's tools, as the host service serves them to each launched session."""

    delivery: Delivery

    @override
    def specs(self) -> list[ToolSpec]:
        return specs()

    @override
    async def call(
        self,
        name: str,
        arguments: JsonValue,
        launch: Register,
        caller: Caller,
        call: str | None,
    ) -> Answer:
        """Run the tool `name` for `caller`, a conversation of `launch`: its arguments validated, its answer in words.

        Arguments that don't validate are refused, saying why, as the library's
        tools refuse them. An item the call makes keeps `call`, its moment in
        the conversation's record.
        """
        party = Conversation(
            repository=launch.repository,
            runtime=launch.runtime,
            session=caller.session,
            agent=caller.agent,
        )
        speaker = Speaker(delivery=self.delivery, launch=launch, party=party, call=call)
        [tool] = [tool for tool in speaker.tools() if tool.spec().name == name]
        match await tool.call(arguments):
            case Accepted(answer=answer):
                return Answer(text=Said.model_validate_json(answer).text)
            case Refused(rejection=rejection):
                return Answer(text=f"Refused: {rejection.reason}", error=True)
