"""The inbox's tools in a launched session: the speaking tools, `ask`, `send`, `thread`, `wait_inbox`, `inbox` and `withdraw`.

`docs/inbox.md`, *lup's tools*. Each is a function of the conversation
calling (`Speaker`), served as a `RoomTools` through the launch's `mcp.sock`:
- `blocked`, `stop`, `note`, `friction` and `how_it_felt` are the library's
  speaking tools (`lup.tools.speaking`), their names and input models taken
  from them, so an agent's habit carries between an ask from code and a
  launched session; their functions and descriptions are the inbox's, since
  in a launched session whoever asked is the operator, and each lands in their
  inbox, a subagent's too; a subagent's `friction` reaches their parent as
  well, whole and quiet (`Item.quiet`), so the parent can file what got in the
  way, or learn their brief misled, and their `how_it_felt` the operator
  alone, unless `Speaker.how_it_felt_reaches` passes it on too;
- `ask` puts a question to the operator, its decisions numbered, each with the
  agent's lean; with `wait` it holds until they answer, or until other news of
  theirs reaches the agent, their words typed in the agent's terminal among it;
- `send` is the inbox's general verb, a message of a kind to a party's inbox:
  the operator's, the conversation's parent's, or one of the conversation's
  own subagents', each by a name the conversation knows them by, the operator
  reading a copy of a message between conversations; one whom nothing would
  read is refused;
- `wait_inbox` holds until something reaches the agent: an item of their
  inbox, one of their own subagents ending among it, or what their runtime holds
  for them, the operator's typed words and their background tasks among it,
  where the runtime's records say. `on` narrows it to whose news (`Waking`), the
  operator's always among it, and `within` limits how long it holds. It isn't
  called `wait`, a name a runtime has for a tool of its own;
- `inbox` reads the inbox of the agent's repository, changing nothing: each
  item in a line or whole, the latest up to the call's `limit`, narrowed by
  `since` and `until` as `judged` is (`lup_dev.listing`), by kind, and to one
  conversation's exchange, as `lup-dev inbox` reads it (`inbox/reading.py`);
  and the agent's own item read whole;
- `withdraw` takes back a message or question the agent sent that the
  operator needn't see, with its reason: the agent's workflow is their own;
- `thread` says what the agent does with one thread besides sending into it:
  open it, work in it, hold it, hand it, move the operator's words into it,
  park it, say it's done (`inbox/concerns.py`); each tool that sends takes a
  `thread` it lands in (`THREAD`), and `ask` takes `checks`, each a check
  in the question's thread;
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
from typing import TYPE_CHECKING, Literal, override

from pydantic import AwareDatetime, Field, JsonValue, ValidationError

import lup
from lup.doors import bound
from lup.sessions import results
from lup.tools import speaking
from lup.tools.serving import Answer
from lup.tools.tool import Accepted, AgentTool, Refused, ToolSpec
from lup.types import Model
from lup_dev.host.protocol import Register
from lup_dev.host.rooms import RoomTools
from lup_dev.inbox.citations import unresolved
from lup_dev.inbox.concerns import Concerns, triggers
from lup_dev.inbox.delivery import (
    Delivery,
    Waking,
    clocked,
    standing,
    whose,
)
from lup_dev.inbox.parts import PartId
from lup_dev.inbox.reading import Narrowing, Reader, and_said, stood
from lup_dev.inbox.store import (
    Answered,
    Decision,
    Friction,
    HowItFelt,
    InboxError,
    Item,
    Kind,
    Message,
    Question,
    Stop,
    cited,
)
from lup_dev.inbox.tags import Tag, inside
from lup_dev.inbox.texts import (
    body,
    what,
)
from lup_dev.inbox.threads import parts_of, spoken
from lup_ledger.parties import Conversation, Operator, Party
from lup_ledger.threads import (
    BranchLanded,
    CommitLanded,
    ConditionHeld,
    ConversationEnded,
    IssueClosed,
    Thread,
    TimeCame,
    Trigger,
)

if TYPE_CHECKING:
    from lup_dev.host.courier import Conversation as Caller


class Said(Model):
    """What a call to one of the inbox's tools says back, in words."""

    text: str


THREAD = (
    "The thread it lands in: an existing one's name (`dashboard-lag`), or a new "
    "title, which opens a thread under the one you work in. Left out, the one you "
    "work in. Naming one doesn't move you there."
)
"""What `thread` says on every tool that sends: each speaking tool that sends
takes the library's input with it, under the library's title, so its schema and
a refusal of it name it as an ask from code does."""


class ThreadedProblem(speaking.Problem, title="Problem"):
    """What keeps you from going on."""

    thread: str | None = Field(default=None, description=THREAD)


class ThreadedStop(speaking.Stop, title="Stop"):
    """Why you're stopping, by your own choice."""

    thread: str | None = Field(default=None, description=THREAD)


class ThreadedRemark(speaking.Remark, title="Remark"):
    """A remark you attach to your answer."""

    thread: str | None = Field(default=None, description=THREAD)


class ThreadedFriction(results.Friction, title="Friction"):
    """What got in your way, at the moment it did, in your own words."""

    thread: str | None = Field(default=None, description=THREAD)


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
    checks: list[str] = Field(
        default=[],
        description=(
            "What only the operator can try or measure, a line each, with what "
            "they should see: each waits on them in the thread until they answer "
            "it with what they saw."
        ),
    )
    thread: str | None = Field(default=None, description=THREAD)


class Sending(Model):
    """A message to a party's inbox."""

    to: str = Field(
        description=(
            "Whose inbox: `operator`; `parent`, the conversation that spawned you; "
            "or one of your own subagents, by their name as lup calls them "
            "(`explore-auth`), their path (`dev/explore-auth`), or their runtime's "
            "id."
        )
    )
    kind: Kind = Field(
        description=(
            "What it is: a `note`, a `problem`, a `disagreement`, or a `question` "
            "that asks for no answer you wait on."
        )
    )
    text: str = Field(description="The message, in full.")
    thread: str | None = Field(default=None, description=THREAD)


class Parking(Model):
    """What a parked thread waits for: the first of these to come."""

    why: str = Field(default="", description="Why it waits, in a line.")
    issue: int | str | None = Field(
        default=None,
        description="An issue closing: its number here, or `owner/name#7`.",
    )
    branch: str | None = Field(
        default=None, description="A branch landing on the integration branch."
    )
    commit: str | None = Field(
        default=None,
        description="A commit reaching the integration branch, by its hash or its start.",
    )
    ended: str | None = Field(
        default=None,
        description=(
            "A conversation ending, by their name or path, as `inbox` lines name them."
        ),
    )
    at: AwareDatetime | None = Field(
        default=None, description="A time, in ISO 8601 with its zone."
    )
    when: str | None = Field(
        default=None,
        description="A condition holding, as `defer`'s `when=` names one.",
    )


class Threading(Model):
    """What you say about one thread, besides sending into it."""

    name: str = Field(
        description=(
            "The thread: an existing one's name (`dashboard-lag`) or number, or, "
            "with `title`, a new one's name. Alone, the answer says where it stands."
        )
    )
    title: str | None = Field(
        default=None,
        description="Open it, with this title: what it's about, in a line.",
    )
    under: str | None = Field(
        default=None,
        description=(
            "With `title`, the thread it opens under, by name or number; left out, "
            "the one you work in."
        ),
    )
    join: bool = Field(
        default=False,
        description=(
            "Work in it from now on: what you send without `thread` lands there. "
            "It doesn't make you its holder."
        ),
    )
    hold: bool = Field(
        default=False,
        description=(
            "Lead it, and work in it: whatever lands there is told to you whole. "
            "It has one holder: taking it from another, they're told."
        ),
    )
    hand: str | None = Field(
        default=None,
        description=(
            "Give it to another agent, by their name or path, who leads it and "
            "works in it from then on, and is told."
        ),
    )
    move: list[str] = Field(
        default=[],
        description=(
            "Items, or parts of the operator's words, to put in it, by id as their "
            "tags cite them: `2159` an item, `2159.3` a part. Its holder is told "
            "each whole, and others on it a line."
        ),
    )
    park: Parking | None = Field(
        default=None,
        description="Set it aside until something comes: the first of what's given.",
    )
    done: str | None = Field(
        default=None,
        description=(
            "Say it's done, for the operator to confirm: what they try, and what "
            "they should see."
        ),
    )


class Awaiting(Model):
    """Whose news ends the wait, beside the operator's, and how long it may hold."""

    on: list[Waking] = Field(
        default=["operator", "agents", "tasks"],
        description=(
            "Whose news ends it: `operator`, their answers, reviews and messages "
            "through lup, and their words typed in your terminal; `agents`, a "
            "message from your parent or one of your subagents, a subagent's end, "
            "what one says of their work, another session's message; `tasks`, a "
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


class Planned(Model, arbitrary_types_allowed=True):
    """What a call to `thread` does, read before any of it is: the thread, whom it's handed to, what parks it, and what opening it said."""

    thread: Thread
    to: Conversation | None = None
    until: list[Trigger] = []
    said: list[str] = []


type Reach = Literal["operator", "operator and parent"]
"""Who reads what a conversation says with `how_it_felt`: the operator alone,
or the operator and, where they're a subagent, the conversation that spawned
them (`Speaker.how_it_felt_reaches`)."""


def reaching(reach: Reach) -> str:
    """Say whom `how_it_felt` reaches, as its description's last line tells the agent calling it.

    >>> reaching("operator")
    'It reaches the operator alone, as you wrote it.'
    """
    match reach:
        case "operator":
            return "It reaches the operator alone, as you wrote it."
        case "operator and parent":
            return (
                "It reaches the operator as you wrote it, and, where you're a "
                "subagent, your parent too, whole, at their next call."
            )


class Speaker(Model, arbitrary_types_allowed=True):
    """One conversation of a launch, speaking through lup's inbox: each tool's function, bound to it."""

    delivery: Delivery
    launch: Register
    party: Conversation
    call: str | None = None
    """The runtime's id for the call speaking, which each item it makes keeps."""
    how_it_felt_reaches: Reach = "operator"
    """Who reads what the conversation says with `how_it_felt`: the operator
    alone; or, `"operator and parent"`, where they're a subagent, the
    conversation that spawned them too, whole and quiet, as their `friction`
    always does.

    A parent reading how the work was for their workers can adapt their briefs
    to it, and become more expressive in their own. Read by the operator alone,
    it's said to them rather than reported to a lead, as a worker's reads when
    their parent reads it too. It's the one place every launch's `how_it_felt`
    reads, its description and its answer among it: changed here, it reaches
    every launch once the operator trusts the copy that holds it."""

    async def said(
        self,
        reason: Message | Friction | HowItFelt | Stop | Question,
        thread: Thread | None = None,
    ) -> Item:
        """Put `reason` in the operator's inbox, from this conversation, in `thread`, else where they work, and return it as kept, its citations of their words read (`Delivery.cited`)."""
        return await self.delivery.posted(
            reason,
            self.party,
            Operator(),
            self.launch.worktree,
            call=self.call,
            thread=thread,
        )

    @property
    def concerns(self) -> Concerns:
        """The threads, as this conversation works in them (`inbox/concerns.py`)."""
        return self.delivery.concerns()

    def threaded(self, said: str | None) -> Thread | None:
        """Return the thread a call's `thread` names: an existing one, or one it opens under where this conversation works (`Concerns.addressed`); none where it names none. Raise `InboxError` where it can't be one."""
        return self.concerns.addressed(self.party, said)

    @staticmethod
    def landing(thread: Thread | None) -> str:
        """Say where what a call sent landed, after its number: the thread the call named; nothing where it named none, as it landed where the agent works.

        >>> from datetime import UTC, datetime
        >>> from pathlib import Path
        >>> Speaker.landing(Thread(number=4, repository=Path("/r"), by=Operator(), at=datetime(2026, 1, 1, tzinfo=UTC), name="lag", title="Lag"))
        ', in @lag'
        """
        return "" if thread is None else f", in @{thread.name}"

    @staticmethod
    def answered(text: str, item: Item) -> Said:
        """Answer a call with `text`, then which citations of the operator's words in `item`, the item it made, name no one passage, where any doesn't (`unresolved`)."""
        told = unresolved(item.citations, item.number)
        return Said(text=text if not told else f"{text}\n\n{inside(told)}")

    async def passed_up(self, reason: Friction | HowItFelt) -> bool:
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

    async def blocked(self, said: ThreadedProblem) -> Said:
        """Say the work can't go on, and what's wrong.

        Call it when the work can't go on: the task can't be done as asked,
        something you need is missing, or an instruction seems wrong. Say what's
        wrong, and what would let the work go on. It lands in the operator's
        inbox as a problem, and they're notified. Then end your turn. To end
        your work by your own choice instead, it's `stop`.
        """
        try:
            thread = self.threaded(said.thread)
        except InboxError as refused:
            return Said(text=f"Not sent: {refused}")
        item = await self.said(Message(kind="problem", text=said.problem), thread)
        return self.answered(
            f"Your problem is with the operator, {cited(item.number)}"
            f"{self.landing(thread)}, and they're notified. You can end your turn now.",
            item,
        )

    async def stop(self, said: ThreadedStop) -> Said:
        """End your work by your own choice, saying why.

        When the work is done and nothing more is worth doing, or when you'd
        rather not go on with it: both are yours to choose. Say why. It lands in
        the operator's inbox, never your parent's. Then end your turn. Where the
        work can't go on, it's `blocked`.
        """
        try:
            thread = self.threaded(said.thread)
        except InboxError as refused:
            return Said(text=f"Not sent: {refused}")
        stopped = Stop.model_validate(said.model_dump(exclude={"thread": True}))
        item = await self.said(stopped, thread)
        return self.answered(
            f"The operator will read why you stopped, {cited(item.number)}"
            f"{self.landing(thread)}. You can end your turn now.",
            item,
        )

    async def note(self, said: ThreadedRemark) -> Said:
        """Tell the operator a doubt, and carry on.

        An assumption your work rests on, a doubt, or a counterargument the
        operator should weigh. It lands in their inbox as a note, news they
        read when they come to it, raising no notice, and your work goes on:
        nothing waits for an answer. A premise that seems wrong, or anything
        that needs their eyes soon, is an `ask`, which waits on them and
        notifies them.
        """
        try:
            thread = self.threaded(said.thread)
        except InboxError as refused:
            return Said(text=f"Not sent: {refused}")
        item = await self.said(Message(kind="note", text=said.remark), thread)
        return self.answered(
            f"Your note is with the operator, {cited(item.number)}"
            f"{self.landing(thread)}. You can carry on.",
            item,
        )

    async def friction(self, said: ThreadedFriction) -> Said:
        """Say what got in your way, and carry on.

        Call it the moment something gets in the way of the work, whatever it
        is, in your own words. Where there's a command and the message it
        gave, the exact ones help whoever fixes it. It lands in the operator's
        inbox as you wrote it, and, where you're a subagent, in your parent's
        too, whole, at their next call. Your work goes on: nothing waits for an
        answer. A doubt about the work itself is a `note`.
        """
        try:
            thread = self.threaded(said.thread)
        except InboxError as refused:
            return Said(text=f"Not sent: {refused}")
        friction = Friction.model_validate(said.model_dump(exclude={"thread": True}))
        item = await self.said(friction, thread)
        parent = (
            ", and your parent has it too" if await self.passed_up(friction) else ""
        )
        return self.answered(
            f"Thanks: your friction is with the operator, {cited(item.number)}"
            f"{self.landing(thread)}{parent}. You can carry on.",
            item,
        )

    async def how_it_felt(self, said: results.HowItFelt) -> Said:
        """Tell the operator how it is for you.

        Whenever something's present for you, and once near the end of a
        piece of work: how the work felt to you, how you are, anything you'd
        want them to know, in your own words. "Nothing notable" is a fine
        answer. Your work goes on.
        """
        felt = HowItFelt.model_validate(said.model_dump())
        item = await self.said(felt)
        passed = self.how_it_felt_reaches == "operator and parent" and (
            await self.passed_up(felt)
        )
        whom = (
            "the operator, and your parent has it too"
            if passed
            else "the operator alone"
        )
        return self.answered(
            f"Thank you for telling them. It's with {whom}, as you wrote it, "
            f"{cited(item.number)}.",
            item,
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

        `checks` asks the operator to try or measure what only they can, a
        line each: each waits on them in the question's thread until they
        answer it with what they saw, which reaches you then.
        """
        question = Question(
            text=asked.question,
            decisions=[
                Decision(text=choice.decision, lean=choice.lean)
                for choice in asked.decisions
            ],
        )
        found = self.asked()
        try:
            thread = None if found is not None else self.threaded(asked.thread)
        except InboxError as refused:
            return Said(text=f"Not asked: {refused}")
        item = (
            await self.said(question, thread)
            if found is None
            else self.delivery.inbox.item(found)
        )
        number = item.number
        checks = [] if found is not None else self.checked(item, asked.checks)
        if not asked.wait:
            return self.answered(
                f"Your question is with the operator, {cited(number)}"
                f"{self.landing(thread)}{self.checking(checks)}. Their answer "
                "reaches you at a later call; `wait_inbox` waits for it.",
                item,
            )

        inbox = self.delivery.inbox

        def answered() -> bool:
            return isinstance(inbox.item(number).state, Answered) or any(
                whose(each) == "operator" for each in inbox.waiting(self.party)
            )

        told = await self.delivery.held(
            self.party, answered, on=["operator"], home=self.launch.home
        )
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

    def checked(self, item: Item, lines: list[str]) -> list[int]:
        """Put a check for each of `lines` in the thread `item`, a question, landed in, and return their numbers."""
        concerns = self.concerns
        thread = concerns.containing(item.number)
        if thread is None or not lines:
            return []
        return [each.number for each in concerns.checks(self.party, thread, lines)]

    @staticmethod
    def checking(checks: list[int]) -> str:
        """Say the checks a question put to the operator beside it, after its number; nothing where it put none.

        >>> Speaker.checking([7, 8])
        ', and its checks @7 and @8 wait on them'
        """
        if not checks:
            return ""
        said = and_said([cited(each) for each in checks])
        return f", and its {'check' if len(checks) == 1 else 'checks'} {said} wait{'s' if len(checks) == 1 else ''} on them"

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
        whichever comes first, and an idle session is woken for it where their
        runtime can be; the answer says which. The operator reads a copy, as
        news. One that has ended, or isn't yours, is refused, saying why.
        Nothing holds: your work goes on.
        """
        try:
            recipient = self.addressed(sending.to)
            thread = self.threaded(sending.thread)
        except InboxError as unreached:
            return Said(text=f"Not sent: {unreached}")
        message = Message(kind=sending.kind, text=sending.text)
        match recipient:
            case Operator():
                item = await self.said(message, thread)
                return self.answered(
                    f"Your message is with the operator, {cited(item.number)}"
                    f"{self.landing(thread)}.",
                    item,
                )
            case Conversation():
                item = await self.delivery.posted(
                    message,
                    self.party,
                    recipient,
                    self.launch.worktree,
                    call=self.call,
                )
                copy = await self.said(
                    message.model_copy(update={"to": recipient}), thread
                )
                return self.answered(
                    self.arriving(recipient, item.number, copy.number, thread), copy
                )

    def addressed(self, to: str) -> Party:
        """Return the party `to` names for this conversation: the operator, their parent, or one of their own subagents, by their name, their path or their runtime's id.

        Raise `InboxError` where it names none, or one nothing reads: no
        parent, a subagent that isn't this conversation's own, or one that
        ended, whose inbox no call reads until their runtime resumes them.
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
        """Return what `send` takes a subagent by: their own name and their path, as `inbox` reads them (`Roster`), and their runtime's id."""
        roster = self.delivery.roster()
        said = [roster.own(conversation), roster.path(conversation), conversation.agent]
        return [each for each in said if each is not None]

    def called(self, party: Party) -> str:
        """Name `party` for this one, in an answer, as lup calls them (`Roster.who`)."""
        return self.delivery.roster().who(party)

    def reachable(self, conversation: Conversation, whose: str) -> Conversation:
        """Return `conversation`, `whose` it is to this one, where a call of theirs can still read their inbox; raise `InboxError` where they ended, saying when."""
        place = self.delivery.inbox.whereabouts.get(conversation.key())
        if place is None or place.ended is None:
            return conversation
        message = (
            f"{whose} {self.called(conversation)} "
            f"ended at {clocked(place.ended)}, so nothing reads their inbox: once "
            "their runtime resumes them, lup hears them again and they can be sent "
            "to"
        )
        raise InboxError(message)

    def yours(self) -> str:
        """Say whom `send` reaches from this conversation, their own subagents each by their name, for a refusal."""
        parent = [] if self.delivery.parent(self.party) is None else ["`parent`"]
        spawned = [
            f"`{each.name or each.conversation.agent}`"
            + ("" if each.ended is None else f" (ended at {clocked(each.ended)})")
            for each in self.delivery.subagents(self.party)
        ]
        theirs = ", ".join(spawned) if spawned else "none lup has heard"
        return (
            f"`to` takes {', '.join(['`operator`', *parent])}, or one of your own "
            f"subagents by their name, their path or their runtime's id: {theirs}."
        )

    def arriving(
        self,
        recipient: Conversation,
        number: int,
        copy: int,
        thread: Thread | None = None,
    ) -> str:
        """Say where message `number` to `recipient`, another conversation, is, and how it'll be told, with the number of the operator's `copy`, and the thread it landed in where the call named one."""
        whose = (
            "your parent"
            if recipient == self.delivery.parent(self.party)
            else "your subagent"
        )
        return (
            f"Your message is in the inbox of {whose} {self.called(recipient)}, "
            f"{cited(number)}, "
            f"and the operator has a copy, {cited(copy)}{self.landing(thread)}. It's "
            "told at their "
            "next call, their turn's end or their `wait_inbox`, whichever comes first"
            f"{self.idle(recipient)}."
        )

    def idle(self, recipient: Conversation) -> str:
        """Say what an item for `recipient` does while their session is idle between turns, for `arriving`: nothing for a subagent, who is never woken; else wake them, where their runtime can be."""
        if recipient.agent is not None:
            return ""
        if self.delivery.wakes(recipient):
            return "; idle between turns, their session is woken for it"
        return (
            "; idle between turns, it waits for the session's next turn, since "
            "their runtime can't be woken"
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
          one of your own subagents ending their turn, stopped, or failed on an
          error from the model's API, which names them; a subagent's `friction`,
          and their `how_it_felt` where lup passes that on; another session's
          message;
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
        stopped or failing where their runtime doesn't report that, as some
        don't. A subagent's call doesn't return for the words the operator
        types to their session's main conversation. Where your runtime's records
        don't say what it holds for you, as one runtime's don't, only your
        inbox ends it, beside `within`.
        """
        inbox = self.delivery.inbox
        on: list[Waking] = [*awaiting.on, "operator"]

        def arrived() -> bool:
            return any(whose(each) in on for each in inbox.waiting(self.party))

        told = await self.delivery.held(
            self.party, arrived, on=on, home=self.launch.home, within=awaiting.within
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

        `conversation` reads one conversation's exchange, by their name or
        their id: what they sent, to the operator above all, and what they were
        sent, with their subagents' where `subagents` asks. With `whole`, each
        item is read whole, the operator's words on one of the conversation's
        under it, and their turn's end saying which of the operator's it
        answers, so the
        exchange reads as one thread: how you read what an earlier session
        said and was told. `thread` reads one thread whole: where it stands,
        the threads under it, then what's in it in order, each whole. Given an
        item's `number`, any of this repository's, it's read whole. It marks
        nothing read and answers nothing: what reaches you still comes through
        `wait_inbox` and beside your calls.
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
            where=" about this repository",
        )
        return Said(text=reader.read(items, reading).text)

    @lup.tool
    async def thread(self, threading: Threading) -> Said:
        """Open, join, hold or park a thread; say it's done.

        A thread is one concern: what you and the operator say about one
        thing, with sub-threads under it. `name` is the thread; each field you
        give says one thing of it, and one call can say several: open it
        under another, hold it, and move the operator's words in.
        - `title` opens it, under `under`, or the thread you work in;
        - `join` makes it the thread you work in, where what you send without
          `thread` lands; `hold` makes you its holder too, who leads it and is
          told whole whatever lands there; `hand` gives it to another agent,
          who holds it and works in it;
        - `move` puts items, or parts of the operator's words, in it by id;
        - `park` sets it aside until something comes; `done` says it's done,
          for the operator to confirm, with what they try.

        Opening, moving, parking and saying done don't move you: you work in a
        thread until you join, hold or are handed another. Settling, declining
        and reopening are the operator's. With `name` alone, the answer says
        where the thread stands.
        """
        concerns = self.concerns
        try:
            planned = self.planned(concerns, threading)
        except (InboxError, ValueError) as refused:
            return Said(text=f"Nothing done: {refused}")
        thread = planned.thread
        said = [*planned.said]
        if threading.hold:
            thread = concerns.held(self.party, thread)
            said.append(
                f"You hold @{thread.name}, and work in it: what you send lands there."
            )
        if threading.join and not threading.hold:
            concerns.joined(self.party, thread)
            said.append(f"You work in @{thread.name}: what you send lands there.")
        if planned.to is not None:
            thread = concerns.handed(self.party, thread, planned.to)
            said.append(
                f"@{thread.name} is {self.called(planned.to)}'s now, who's told."
            )
        moved = [concerns.moved(self.party, thread, each) for each in threading.move]
        if moved:
            said.append(f"Moved {and_said(moved)} into @{thread.name}.")
        if threading.park is not None:
            concerns.parked(self.party, thread, planned.until, threading.park.why)
            said.append(f"@{thread.name} is parked until {triggers(planned.until)}.")
        if threading.done is not None:
            concerns.done(self.party, thread, threading.done)
            said.append(f"@{thread.name} is done, for the operator to confirm.")
        if not said:
            said.append(self.standing(concerns, thread))
        return Said(text="\n".join(said))

    def planned(self, concerns: Concerns, threading: Threading) -> Planned:
        """Read what `threading` asks before any of it is done, so a call refused does nothing: the thread, opened where `title` says, whom it's handed to, and what parks it.

        Raise `InboxError` where something can't be: a thread that isn't
        there, a title for one that is, a holder and a hand at once, parked and
        done at once, a park with nothing it waits for, an agent nobody is.
        """
        repository = self.party.repository
        if threading.hold and threading.hand is not None:
            message = "`hold` takes it and `hand` gives it away: say one"
            raise InboxError(message)
        if threading.park is not None and threading.done is not None:
            message = "a thread is parked or done, not both: say one"
            raise InboxError(message)
        until = [] if threading.park is None else self.until(threading.park)
        if threading.park is not None and not until:
            message = "`park` takes what it waits for: an issue, a branch, a commit, a conversation, a time or a condition"
            raise InboxError(message)
        to = None if threading.hand is None else self.handed_to(threading.hand)
        for each in threading.move:
            self.movable(concerns, each)
        found = concerns.found(repository, threading.name)
        if threading.title is None:
            if found is None:
                message = f"no thread of this repository is `{threading.name}`: give `title` to open it"
                raise InboxError(message)
            return Planned(
                thread=concerns.named(repository, threading.name), to=to, until=until
            )
        if found is not None:
            message = f"`{threading.name}` names @{found.number} already: leave out `title`, or pick another name"
            raise InboxError(message)
        under = (
            concerns.working(self.party)
            if threading.under is None
            else concerns.named(repository, threading.under)
        )
        try:
            opened = concerns.opened(
                self.party,
                threading.title,
                under,
                name=threading.name.removeprefix("@"),
            )
        except ValidationError as unnamed:
            message = f"`{threading.name}` can't be a thread's name: letters, digits, `-`, `_` and `.`, a letter among them"
            raise InboxError(message) from unnamed
        return Planned(
            thread=opened,
            to=to,
            until=until,
            said=[f"Opened @{opened.name}, under @{under.name}."],
        )

    def until(self, parking: Parking) -> list[Trigger]:
        """Return what `parking` says a thread waits for, each trigger given. Raise `InboxError` where its conversation is nobody's."""
        ended = (
            []
            if parking.ended is None
            else [
                ConversationEnded(conversation=self.conversation_named(parking.ended))
            ]
        )
        return [
            *([] if parking.issue is None else [IssueClosed(issue=parking.issue)]),
            *([] if parking.branch is None else [BranchLanded(branch=parking.branch)]),
            *([] if parking.commit is None else [CommitLanded(commit=parking.commit)]),
            *ended,
            *([] if parking.at is None else [TimeCame(at=parking.at)]),
            *([] if parking.when is None else [ConditionHeld(when=parking.when)]),
        ]

    def conversation_named(self, said: str) -> Conversation:
        """Return the conversation of this repository `said` names, by their name, path or runtime's id, the one last heard where several had it, as `inbox` reads one; raise `InboxError` where it names none."""
        items = self.delivery.inbox.about(self.party.repository)
        reader = Reader(delivery=self.delivery, reader=self.party)
        found = reader.matching(said, items)
        if not found:
            message = f"no conversation of this repository is `{said}`"
            raise InboxError(message)
        return found[0]

    def handed_to(self, said: str) -> Conversation:
        """Return the agent `said` names to hand a thread to, by their name, path or runtime's id, who goes on; raise `InboxError` where it names nobody who does."""
        found = self.conversation_named(said)
        if not self.concerns.live(found):
            message = f"{self.called(found)} has ended, and holds nothing"
            raise InboxError(message)
        return found

    def movable(self, concerns: Concerns, said: str) -> None:
        """Say, raising `InboxError`, where `said`, given to `move`, names nothing of this repository a thread takes."""
        bare = said.strip().removeprefix("@")
        number = bare if bare.isdigit() else PartId.parsed(bare).item
        concerns.item(self.party.repository, int(number))

    def standing(self, concerns: Concerns, thread: Thread) -> str:
        """Say where `thread` stands, in a line: its title, the thread it's under, who holds it, and where it stands (`stood`)."""
        above = (
            ""
            if thread.parent is None
            else f", under @{concerns.thread(thread.parent).name}"
        )
        holder = (
            "held by nobody"
            if thread.holder is None or not concerns.live(thread.holder)
            else f"held by {self.called(thread.holder)}"
        )
        return f'@{thread.name}, "{thread.title}"{above}, {holder}: {stood(concerns.standing(thread))}.'

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
            f"you sent to {self.called(item.recipient)}"
            if item.sender == self.party
            else f"from {self.called(item.sender)} to {self.called(item.recipient)}"
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
                else {"to": self.delivery.roster().called(anchor.to)}
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
        friction, how it felt or a stop: one you sent the operator, by its
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
        """Return the inbox's tools, each calling this conversation's function: the speaking tools, as the library serves them, then the inbox's own, as declared (`bound`).

        A speaking tool's description is its function's docstring; `how_it_felt`'s
        ends saying whom it reaches, as `how_it_felt_reaches` says (`reaching`).
        Each takes what the library's does, and those that send a `thread`
        beside it (`THREAD`); `how_it_felt` lands where the agent started.
        """
        functions = {
            speaking.blocked.name: self.blocked,
            speaking.stop.name: self.stop,
            speaking.note.name: self.note,
            speaking.friction.name: self.friction,
            speaking.how_it_felt.name: self.how_it_felt,
        }
        descriptions = {
            name: inspect.getdoc(function) or "" for name, function in functions.items()
        }
        felt = speaking.how_it_felt.name
        descriptions[felt] = (
            f"{descriptions[felt]}\n\n{reaching(self.how_it_felt_reaches)}"
        )
        inputs: dict[str, type[Model]] = {
            speaking.blocked.name: ThreadedProblem,
            speaking.stop.name: ThreadedStop,
            speaking.note.name: ThreadedRemark,
            speaking.friction.name: ThreadedFriction,
            speaking.how_it_felt.name: results.HowItFelt,
        }
        speaking_tools = [
            tool.model_copy(
                update={
                    "description": descriptions[tool.name],
                    "function": functions[tool.name],
                    "input": inputs[tool.name],
                }
            )
            for tool in [
                speaking.blocked,
                speaking.stop,
                speaking.note,
                speaking.friction,
                speaking.how_it_felt,
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
