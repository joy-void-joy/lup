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
  agent's lean; with `wait` it holds until they answer;
- `send` is the inbox's general verb, a message of a kind to a party's inbox:
  the operator's, in this piece;
- `wait_inbox` holds until something reaches the agent's inbox, one of its own
  subagents' ends among it. It isn't called `wait`, a name a runtime has for a
  tool of its own;
- `inbox` reads the inbox of the agent's repository, changing nothing: each
  item in a line, the latest up to the call's `limit`, narrowed by `since` and
  `until` as `judged` is (`lup_dev.listing`), and the agent's own read whole;
- `withdraw` takes back a message or question the agent sent that the
  operator needn't see, with its reason: the agent's workflow is its own;
- `reply` answers the operator's comments by their ids, several in one call,
  each kept on their item as a thread (`docs/inbox.md`, *Replying by id*).

A tool's docstring's first line is its summary, 50 characters at most, which the
guidance lists (`launch/guidance.py`); the rest is its description, which the
runtime's tool search finds. Each answers in words, as `content`.
"""

import inspect
from typing import TYPE_CHECKING, Literal, override

from pydantic import Field, JsonValue, PositiveInt

from lup.tools import speaking
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, AgentTool, Refused, ToolSpec, lup_tool
from lup.types import Model
from lup_dev.host.protocol import Register
from lup_dev.host.rooms import RoomTools
from lup_dev.inbox.delivery import (
    Delivery,
    body,
    clocked,
    opening,
    replied_to,
    standing,
    what,
    who,
)
from lup_dev.inbox.parts import PartId
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
    Waiting,
    cited,
)
from lup_dev.inbox.tags import Tag
from lup_dev.inbox.threads import Replying, anchors, parts_of
from lup_dev.listing import Span, latest, unlisted

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

    to: Literal["operator"] = Field(description="Whose inbox: the operator's.")
    kind: Kind = Field(
        description=(
            "What it is: a `note`, a `problem`, a `disagreement`, or a `question` "
            "that asks for no answer you wait on."
        )
    )
    text: str = Field(description="The message, in full.")


class Nothing(Model):
    """No input."""


class Reading(Span):
    """What of the inbox to read."""

    number: int | None = Field(
        default=None,
        description=(
            "An item to read whole, by its number (270 for `@270`): one you sent, "
            "or that was sent to you. Left out, the items are listed, a line each."
        ),
    )
    part: str | None = Field(
        default=None,
        description=(
            "One part to read alone, by its id (`414.3`): of an item you sent, "
            "one of its Markdown blocks; of one sent to you, the operator's words "
            "there, or a reply of yours. With it, `number` is left out."
        ),
    )
    every: bool = Field(
        default=False,
        description=(
            "List every item, those answered, done or told too; left out, those "
            "still waiting alone."
        ),
    )
    limit: PositiveInt = Field(
        default=50,
        description=(
            "How many items to list at most, the latest. Those left out are counted."
        ),
    )


class Answering(Model):
    """One reply: what it answers, by its id, and its words."""

    to: str = Field(
        description=(
            "The id of what it answers, as the tag carried it (`546.2`): a comment "
            "or reply of the operator's in a review, a message or an answer sent "
            "to you."
        )
    )
    text: str = Field(description="Your reply to it, in full.")


class Replies(Model):
    """Your replies, each to a part of the operator's by its id."""

    replies: list[Answering] = Field(
        min_length=1,
        description="Each reply, in the order you'd have them read.",
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
    ) -> int:
        """Put `reason` in the operator's inbox, from this conversation, and return its number."""
        item = await self.delivery.posted(
            reason, self.party, Operator(), self.launch.worktree, call=self.call
        )
        return item.number

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
        number = await self.said(Message(kind="problem", text=said.problem))
        return Said(
            text=f"Your problem is with the operator, {cited(number)}. End your turn."
        )

    async def stop(self, said: speaking.Stop) -> Said:
        """End your work by your own choice, saying why.

        When the work is done and nothing more is worth doing, or when you'd
        rather not go on with it: both are yours to choose. Say why. It lands in
        the operator's inbox, never your parent's. Then end your turn. Where the
        work can't go on, it's `blocked`.
        """
        number = await self.said(Stop.model_validate(said.model_dump()))
        return Said(
            text=f"Your stop is with the operator, {cited(number)}. End your turn."
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
        number = await self.said(Message(kind="note", text=said.remark))
        return Said(text=f"Your note is with the operator, {cited(number)}. Carry on.")

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
        number = await self.said(friction)
        parent = " and your parent" if await self.passed_up(friction) else ""
        return Said(
            text=f"Your friction is with the operator, {cited(number)}{parent}. "
            "Carry on."
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
        number = await self.said(went)
        parent = " and your parent" if await self.passed_up(went) else ""
        return Said(text=f"How it went is with the operator, {cited(number)}{parent}.")

    async def ask(self, asked: Asking) -> Said:
        """Ask the operator, with numbered decisions.

        For a decision that's the operator's. List its decisions, each with your
        lean: they're numbered in order, and the operator answers each
        "leaning" (they go with your lean), "undecided" or "leave open", with a
        comment, or in their own words; or ask a plain question, answered in
        words. With `wait`, this call holds until they answer and
        returns the answer, which may take hours. Without it, the call returns
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
        number = await self.said(question)
        if not asked.wait:
            return Said(
                text=(
                    f"Your question is with the operator, {cited(number)}. Their "
                    "answer reaches you at a later call; `wait_inbox` waits for it."
                )
            )

        def answered() -> bool:
            return isinstance(self.delivery.inbox.item(number).state, Answered)

        told = await self.delivery.held(self.party, answered)
        return Said(
            text=told
            or (
                f"The operator answered {cited(number)}; their answer was told to you "
                "beside another call."
            )
        )

    async def send(self, sending: Sending) -> Said:
        """Send a message to a party's inbox.

        A message of a kind: a `note`, a `problem`, a `disagreement`, or a
        `question` asking for no answer you wait on (a decision of the
        operator's is `ask`'s). A note is news to the operator, raising no
        notice, as `note`'s is; the other kinds wait on them. The operator's
        inbox is the one there is; it never holds.
        """
        number = await self.said(Message(kind=sending.kind, text=sending.text))
        return Said(text=f"Your message is with the {sending.to}, {cited(number)}.")

    async def wait_inbox(self, nothing: Nothing) -> Said:
        """Wait until something reaches your inbox.

        Holds this call until an item reaches your inbox, and returns
        everything waiting there, each whole: what a hook announced as too
        long to tell is read here. An item is the operator's answer or
        message; one of your own subagents ending its turn, or stopped, which
        names it; or a subagent's `friction` or `how_it_went`. Something
        already waiting, a subagent that ended since your last call among it,
        is returned at once; each is told once, here or beside another call.

        It doesn't return for what no item says: a background command's end,
        another session's or another conversation's subagents, the operator
        marking something read. Nor for a subagent stopped or failing where
        its runtime doesn't report that, as some don't.
        """
        del nothing
        inbox = self.delivery.inbox

        def arrived() -> bool:
            return bool(inbox.waiting(self.party))

        return Said(text=await self.delivery.held(self.party, arrived))

    async def inbox(self, reading: Reading) -> Said:
        """Read this repository's inbox, changing nothing.

        Lists the items about this repository, oldest first, a line each: its
        number, when it was made, what it is, from whom to whom, where it
        stands, and its first line. Those still waiting, for the operator or
        for an agent, by default; every one with `every`. `since` and `until`
        narrow them by when each was made, and `limit` says how many to list,
        the latest: where it leaves earlier ones out, the answer says how many,
        the `until` that reads them, and the `limit` that lists them all. Given
        an item's `number`, one you sent or that was sent to you, it's read
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
        window = reading.window(self.delivery.clock.now())
        chosen = sorted(
            (
                item
                for item in items
                if (reading.every or isinstance(item.state, Waiting))
                and window.covers(item.made)
            ),
            key=lambda item: item.made,
        )
        if not chosen:
            where = "is in" if reading.every else "waits in"
            return Said(
                text=f"Nothing about this repository {where} the inbox{window.said()}."
            )
        shown = latest(chosen, lambda item: item.made, reading.limit)
        lines = [
            *(self.line(item) for item in shown),
            *unlisted(
                len(chosen) - len(shown), "earlier item", shown[0].made, len(chosen)
            ),
        ]
        return Said(text="\n".join(lines))

    async def reply(self, replying: Replies) -> Said:
        """Reply to the operator's comments, each by its id.

        Each `<reply id="546.2">` or `<comment id>` in a review, a message or
        an answer sent to you can be answered by its id, and one call carries
        every reply of a round. Each is kept on the operator's item under what
        it answers, never as an item of its own, and the dashboard shows it
        there, under their comment, so the exchange reads as a thread: the
        item of yours their comment was on comes back before them with the
        thread, and their next comment on your reply reaches you as an `<on>`
        naming the reply's id. An id naming no part, a comment on another
        agent's item, or a reply of your own is refused, naming what you may
        answer, and nothing of the call is kept. What answers no point of
        theirs is your turn's last words, which reach them as a note; `note`
        is for what they didn't say.
        """
        try:
            replies = [
                Replying(to=PartId.parsed(each.to), text=each.text)
                for each in replying.replies
            ]
            kept = await self.delivery.replied_by(self.party, replies)
        except (ValueError, InboxError) as refused:
            return Said(text=f"Not replied: {refused}")
        said = [
            replied_to([reply], self.delivery.anchored(self.party, each))
            for reply, each in zip(kept, replies, strict=True)
        ]
        return Said(text=f"Your replies are with the operator: {'; '.join(said)}.")

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

    def named(self, party: Party) -> str:
        """Name a party for this conversation: itself as you."""
        return "you" if party == self.party else who(party)

    def line(self, item: Item) -> str:
        """Say an item in a line, as `inbox` lists it."""
        return (
            f"{cited(item.number)}  {clocked(item.made)}  {what(item)} from "
            f"{self.named(item.sender)} to {self.named(item.recipient)}, "
            f"{standing(item)}: {opening(item)}"
        )

    def whole(self, number: int, items: list[Item]) -> str:
        """Say item `number` of `items` whole, where it's this conversation's own: as it was told, where it was sent to it; as it was written, where it sent it. One not among them, or another conversation's, is said and not read."""
        item = next((each for each in items if each.number == number), None)
        if item is None:
            return (
                f"{cited(number)} isn't among this repository's: `inbox` reads this "
                "repository's items alone."
            )
        if self.party in (item.recipient, item.addressed):
            return f"{self.delivery.said(item)}\n\nIt's {standing(item)}."
        if item.sender == self.party:
            parts = "\n".join(
                Tag(
                    name="part", attributes={"id": each.id.said()}, parts=[each.text]
                ).written()
                for each in parts_of(item, body(item))
            )
            return (
                f"{cited(number)}, {what(item)} you sent to {who(item.recipient)} at "
                f"{clocked(item.made)}, {standing(item)}:\n{parts}"
            )
        return (
            f"{cited(number)} is {what(item)} from {who(item.sender)} to "
            f"{who(item.recipient)}, which isn't yours: only your own items are read "
            f"whole. Its first line: {opening(item)}"
        )

    def part(self, wanted: PartId, items: list[Item]) -> str:
        """Say part `wanted` of its item, where the item is this conversation's own (`whole`): a block of an item it sent, as a `<part>` tag; the operator's words there in one sent to it, as the item's tag carried them; a reply of its own, as `<reply>`. One that isn't there is said."""
        item = next((each for each in items if each.number == wanted.item), None)
        if item is None or self.party not in (
            item.recipient,
            item.addressed,
            item.sender,
        ):
            return self.whole(wanted.item, items)
        if item.sender == self.party:
            found = next(
                (each for each in parts_of(item, body(item)) if each.id == wanted), None
            )
            if found is None:
                return f"{cited(wanted.item)} has no part {wanted.cited()}."
            return Tag(
                name="part", attributes={"id": wanted.said()}, parts=[found.text]
            ).written()
        anchor = next((each for each in anchors(item) if each.id == wanted), None)
        if anchor is not None:
            where = {} if anchor.item is None else {"on": str(anchor.item)}
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

    def tools(self) -> list[AgentTool]:
        """Return the inbox's tools, each calling this conversation's function: the speaking tools, as the library serves them, then the inbox's own."""
        functions = {
            speaking.blocked.name: self.blocked,
            speaking.stop.name: self.stop,
            speaking.note.name: self.note,
            speaking.friction.name: self.friction,
            speaking.how_it_went.name: self.how_it_went,
        }
        spoken = [
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
        own = [
            lup_tool(self.ask),
            lup_tool(self.send),
            lup_tool(self.wait_inbox),
            lup_tool(self.inbox),
            lup_tool(self.withdraw),
            lup_tool(self.reply),
        ]
        return [*spoken, *own]


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
