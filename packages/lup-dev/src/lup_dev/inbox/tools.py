"""The inbox's tools in a launched session: the speaking tools, `ask`, `send`, `wait_inbox`, `inbox` and `withdraw`.

`docs/inbox.md`, *lup's tools*. Each is a function of the conversation
calling (`Speaker`), served as a `RoomTools` through the launch's `mcp.sock`:
- `blocked`, `stop`, `note`, `friction` and `how_it_went` are the library's
  speaking tools (`lup.tools.speaking`), their names and input models taken
  from them, so an agent's habit carries between an ask from code and a
  launched session; their functions and descriptions are the inbox's, since
  in a launched session whoever asked is the operator, and each lands in their
  inbox, a subagent's too, never its parent's;
- `ask` puts a question to the operator, its decisions numbered, each with the
  agent's lean; with `wait` it holds until they answer;
- `send` is the inbox's general verb, a message of a kind to a party's inbox:
  the operator's, in this piece;
- `wait_inbox` holds until something reaches the agent's inbox. It isn't called
  `wait`, a name a runtime has for a tool of its own;
- `inbox` reads the inbox of the agent's repository, changing nothing: each
  item in a line, and the agent's own read whole;
- `withdraw` takes back a message or question the agent sent that the
  operator needn't see, with its reason: the agent's workflow is its own.

A tool's docstring's first line is its summary, 50 characters at most, which the
guidance lists (`launch/guidance.py`); the rest is its description, which the
runtime's tool search finds. Each answers in words, as `content`.
"""

import inspect
from typing import TYPE_CHECKING, Literal, override

from pydantic import Field, JsonValue

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
    standing,
    what,
    who,
)
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
)

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


class Reading(Model):
    """What of the inbox to read."""

    number: int | None = Field(
        default=None,
        description=(
            "An item to read whole: one you sent, or that was sent to you. Left "
            "out, the items are listed, a line each."
        ),
    )
    every: bool = Field(
        default=False,
        description=(
            "List every item, those answered, done or told too; left out, those "
            "still waiting alone."
        ),
    )


class Withdrawing(Model):
    """An item of yours to take back."""

    number: int = Field(description="The item's number, as its tool's answer said it.")
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
            text=f"Your problem is with the operator, item {number}. End your turn."
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
            text=f"Your stop is with the operator, item {number}. End your turn."
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
        return Said(text=f"Your note is with the operator, item {number}. Carry on.")

    async def friction(self, said: results.Friction) -> Said:
        """Say what got in your way, and carry on.

        Call it the moment something gets in the way of the work, whatever it
        is: a tool, a command, the guidance, a rule, the room, your brief. Give
        the exact command and the message it printed where there is one. It
        lands in the operator's inbox as it is, never your parent's, and your
        work goes on: nothing waits for an answer. A doubt about the work itself
        is a `note`.
        """
        number = await self.said(Friction.model_validate(said.model_dump()))
        return Said(
            text=f"Your friction is with the operator, item {number}. Carry on."
        )

    async def how_it_went(self, said: results.HowItWent) -> Said:
        """Tell the operator how the work went, once.

        Call it near the end of a piece of work: what got in the way, what was
        smooth, what you'd change, and how it felt, as openly as you like.
        Leave out what has nothing to say; "nothing notable" is a fine answer.
        It lands in the operator's inbox as it is, never your parent's, and your
        work goes on.
        """
        number = await self.said(HowItWent.model_validate(said.model_dump()))
        return Said(text=f"How it went is with the operator, item {number}.")

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
                    f"Your question is with the operator, item {number}. Their "
                    "answer reaches you at a later call; `wait_inbox` waits for it."
                )
            )

        def answered() -> bool:
            return isinstance(self.delivery.inbox.item(number).state, Answered)

        told = await self.delivery.held(self.party, answered)
        return Said(
            text=told
            or (
                f"The operator answered item {number}; their answer was told to you "
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
        return Said(text=f"Your message is with the {sending.to}, item {number}.")

    async def wait_inbox(self, nothing: Nothing) -> Said:
        """Wait until something reaches your inbox.

        Holds this call until an item reaches your inbox, an answer or a
        message, and returns everything waiting there, each whole: what a hook
        announced as too long to tell is read here. Something already waiting
        is returned at once.
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
        for an agent, by default; every one with `every`. Given an item's
        `number`, one you sent or that was sent to you, it's read whole. It
        marks nothing read and answers nothing: what reaches you still comes
        through `wait_inbox` and beside your calls.
        """
        items = self.delivery.inbox.about(self.party.repository)
        if reading.number is not None:
            return Said(text=self.whole(reading.number, items))
        listed = [
            item for item in items if reading.every or isinstance(item.state, Waiting)
        ]
        if not listed:
            return Said(
                text="Nothing about this repository is in the inbox."
                if reading.every
                else "Nothing about this repository waits in the inbox."
            )
        return Said(text="\n".join(self.line(item) for item in listed))

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
            text=f"Item {withdrawing.number} is withdrawn, off the operator's list."
        )

    def named(self, party: Party) -> str:
        """Name a party for this conversation: itself as you."""
        return "you" if party == self.party else who(party)

    def line(self, item: Item) -> str:
        """Say an item in a line, as `inbox` lists it."""
        return (
            f"{item.number}  {clocked(item.made)}  {what(item)} from "
            f"{self.named(item.sender)} to {self.named(item.recipient)}, "
            f"{standing(item)}: {opening(item)}"
        )

    def whole(self, number: int, items: list[Item]) -> str:
        """Say item `number` of `items` whole, where it's this conversation's own: as it was told, where it was sent to it; as it was written, where it sent it. One not among them, or another conversation's, is said and not read."""
        item = next((each for each in items if each.number == number), None)
        if item is None:
            return (
                f"Item {number} isn't among this repository's: `inbox` reads this "
                "repository's items alone."
            )
        if self.party in (item.recipient, item.addressed):
            return f"{self.delivery.said(item)}\n\nIt's {standing(item)}."
        if item.sender == self.party:
            return (
                f"Item {number}, {what(item)} you sent to {who(item.recipient)} at "
                f"{clocked(item.made)}, {standing(item)}:\n{body(item)}"
            )
        return (
            f"Item {number} is {what(item)} from {who(item.sender)} to "
            f"{who(item.recipient)}, which isn't yours: only your own items are read "
            f"whole. Its first line: {opening(item)}"
        )

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
