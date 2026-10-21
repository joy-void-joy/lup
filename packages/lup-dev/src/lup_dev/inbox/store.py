"""lup's inbox: its items and its parties, kept one JSON file each in lup's state.

`docs/inbox.md`, *Parties and items*. Every party has an inbox: the
operator, and each conversation of each session, its main one or one of its
subagents. A conversation is keyed by its runtime, its session's id and its own,
within a repository, rather than by the launch it runs in, so a session resumed
in a launch of its own finds what waited for it there.

An item has a number, one sequence per user, so the operator answers `12`; a
reason (a message with its kind, a question with its numbered decisions, an
answer, an approval asked yes or no; a friction, how a piece of work went, or a
stop by choice, each as the agent's tool took it; a change held, or a write that
landed flagged, as the judge put it), whose kind ranks it (`ranked`); a sender
and a recipient; when it was made; and its state: waiting, told (when, and
how), answered, done, or for an approval decided. An item for a conversation
that has ended goes to its session's main conversation, saying whose it was.

An approval is trust on launch's: the launch's own question, put to the
operator's inbox and answered at the launching terminal or any other, whichever
comes first. It's from the operator's own launch to the operator, and its answer
is its state, since no party's inbox waits for it: the launches waiting on it
read it there. Its whole diff, which can run to megabytes, is kept beside it in a
file of its own, and each file it changes, whole, in another, as a held change's
and a flagged write's are; each is read only when asked for, so listing the
inbox never carries them.

The host service is the only writer, on its event loop, and nothing mounts the
store into a room: the first lup's sessions approved their own questions by
writing the log they could reach. Each item and each conversation's whereabouts
is a file of its own, written whole (`stored.py`), rather than one log folded at
every read. Items are kept once told or answered; clearing old ones goes with
lup's cleanup.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, computed_field

from lup.sessions import results
from lup.tools import speaking
from lup.types import Model, MutableModel
from lup_dev.host.protocol import HostError
from lup_dev.host.watch import Changes
from lup_dev.layout import InboxLayout
from lup_dev.stored import read_model, write_model


class InboxError(HostError):
    """An item that isn't there, or can't take what's asked of it, which the host service refuses; or a stored one that doesn't read."""


type Verdict = Literal["leaning", "undecided", "leave open"]
"""The operator's answer to one numbered decision: going with the agent's lean,
not decided, or left for later."""

type Kind = Literal["note", "problem", "disagreement", "question"]
"""What a message is: a remark, a problem that stops the work, a disagreement,
or a question that asks for no answer waited on."""

type How = Literal["call", "start", "turn's start", "turn's end", "held call", "wake"]
"""How an item was told: beside a call, as its session started, beside the
prompt its turn started on, as the reason its turn's end was held, as a held
call's result, or pushed to its idle session, starting a turn."""


class Operator(Model):
    """The operator, whose inbox `lup-dev inbox` shows."""

    party: Literal["operator"] = "operator"


class Conversation(Model):
    """A conversation of a session, within a repository: the session's main one, or one of its subagents."""

    party: Literal["conversation"] = "conversation"
    repository: Path
    """The repository's git directory, as the launch registered it."""
    runtime: str
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent; none for the session's main conversation."""

    def key(self) -> str:
        """Name the conversation as a file name, from what keys it."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def main(self) -> Conversation:
        """Return its session's main conversation."""
        return self.model_copy(update={"agent": None})


type Party = Annotated[Operator | Conversation, Field(discriminator="party")]
"""Who an item is from, or for."""


class Decision(Model):
    """One decision a question asks, with the agent's lean."""

    text: str
    lean: str


class Passage(Model):
    """A passage of a conversation's own words the operator quoted where they read it, with their reply to it."""

    quote: str
    text: str


class Message(Model):
    """A message, of its kind; the operator's reply to a conversation's item says which."""

    reason: Literal["message"] = "message"
    kind: Kind
    text: str
    """Its words; for the operator's message from where they read a
    conversation, their message on it whole, empty where they wrote none."""
    of: int | None = None
    """The item it replies to, where it's the operator's reply to one of a
    conversation's messages (`lup-dev inbox answer`)."""
    passages: list[Passage] = []
    """The passages of the conversation's words the operator replied to, from
    where they read it (`docs/dashboard.md`, *The conversation*), in the
    conversation's order: told before its words, each quoted with their reply."""
    ending: bool = False
    """Whether it's a session's last words of a turn, made a note by lup rather
    than sent by the agent: the conversation already shows them as its words."""


def labelled(opening: str, parts: dict[str, str]) -> str:
    """Return `opening`, then each of `parts` that says something, after its label, a line each.

    >>> print(labelled("The gate hung.", {"Trying": "check", "Would change": ""}))
    The gate hung.
    Trying: check
    """
    said = [f"{label}: {text}" for label, text in parts.items() if text.strip()]
    return "\n".join([opening, *said] if opening.strip() else said)


class Friction(results.Friction):
    """What got in a conversation's way, which it told the operator at the moment it did (`friction`): news to read, never a question."""

    reason: Literal["friction"] = "friction"

    @property
    def text(self) -> str:
        """Say it as the operator reads it: what got in the way, then what the agent was trying and would change, where it said."""
        parts = {"Trying": self.trying, "Would change": self.would_change}
        return labelled(self.got_in_the_way, parts)


class HowItWent(results.HowItWent):
    """How a piece of work went as a whole, as a conversation told the operator once near its end (`how_it_went`): news to read."""

    reason: Literal["how it went"] = "how it went"

    @property
    def text(self) -> str:
        """Say it as the operator reads it: each part the agent filled, after its label; "Nothing notable." where it filled none."""
        parts = {
            "Got in the way": self.got_in_the_way,
            "Smooth": self.smooth,
            "Would change": self.would_change,
            "Felt": self.felt,
        }
        return labelled("", parts) or "Nothing notable."


class Stop(speaking.Stop):
    """A conversation ending its work by its own choice, saying why (`stop`): news to read, where being blocked is a problem."""

    reason: Literal["stop"] = "stop"

    @property
    def text(self) -> str:
        """Say it as the operator reads it: why the agent stopped."""
        return self.why


class Question(Model):
    """A question for the operator: its numbered decisions, each with the agent's lean; or none, answered in words."""

    reason: Literal["question"] = "question"
    text: str
    decisions: list[Decision] = []
    """Numbered from 1, in this order."""


class Ruling(Model):
    """The operator's answer to one numbered decision: a verdict, with what they add; or their answer in words alone."""

    decision: int
    """The decision's number, from 1."""
    verdict: Verdict | None = None
    """None where the operator answered in words, the comment."""
    comment: str = ""


class Answer(Model):
    """The operator's answer to a question: a verdict on each decision, and a comment on the whole, or a plain question's answer."""

    reason: Literal["answer"] = "answer"
    question: int
    """The question's item number."""
    rulings: list[Ruling] = []
    comment: str = ""


class Approval(Model):
    """An approval the operator is asked, yes or no: its question, what they read first, and what it's of.

    Trust on launch's (`lup_dev.launch.trust`): a repository's host zone, the
    whole diff and each file changed kept beside the item (`Inbox.diff`,
    `Inbox.files`), shown on request.
    """

    reason: Literal["approval"] = "approval"
    text: str
    """The question, answered yes or no."""
    summary: str
    """What the operator reads first, coloured as git prints it."""
    repository: Path
    """The git directory of the repository whose host zone it is."""
    fingerprint: str
    """The zone's fingerprint: a launch asking about the same zone joins the
    approval waiting for it."""
    pushed_by: Conversation | None = None
    """The main conversation of the session whose push to the integration branch
    asked it, which the operator's comment on their answer is told to; none for
    one a launch asked at its terminal."""
    typing: bool = False
    """Whether the judge is reading the change's types in the background, its
    files carrying the reading of their parse alone until it's done
    (`docs/trust.md`); once it is, their whole reading
    replaces it, or the summary's last line says why it couldn't."""


class HeldChange(Model):
    """A change held for the operator's answer, yes or no: what's held and why, its diff and each file held kept beside the item (`Inbox.diff`, `Inbox.files`).

    The judge's (`lup_dev.policy.holds`): a write that asks waits for the
    answer inside its hook, or, for what a move of `HEAD` brought, is asked
    after the fact, no agent waiting.
    """

    reason: Literal["held"] = "held"
    text: str
    """The question, answered yes or no: let the change land?"""
    summary: str
    """Each file held, and what it asks."""
    worktree: Path
    key: str
    """The hold's key in the worktree's store, which the answer is written to."""
    commit: str | None = None
    """The commit a move of `HEAD` reached, where it's asked after the fact; none
    where an agent waits on it."""


class Flagged(Model):
    """A write that landed flagged for the operator's review, holding no one: what the file's whole change since the item was made flags, its diff and the file kept beside the item (`Inbox.diff`, `Inbox.files`).

    The judge's (`lup_dev.policy.flags`). A later write to the same file by the
    same conversation, flagged or not, joins the item while it gathers them
    (`Inbox.gathering`), the file kept whole since the first and as it stands.
    """

    reason: Literal["flagged"] = "flagged"
    text: str
    """What landed, in a line."""
    summary: str
    """What the file's whole change flags, a line each, naming the file from
    the worktree's root where it names it."""
    worktree: Path
    path: Path
    """The file, from the worktree's root."""
    commit: str | None = None
    """The commit a move of `HEAD` reached, where the write came with it; none
    where a conversation's call made it."""
    writes: int = 1
    """How many writes it gathers, the flagged one that made it and each by the
    same conversation to the file since: the page reads its file again as it
    grows."""


class Quote(Model):
    """A passage of an item the operator commented on: the text they selected, and where it is in the item as the page shows it."""

    text: str
    start: int
    """Where it starts in the item's text as the page shows it, which the page
    places the comment by; the host keeps it, and reads only `text`."""
    end: int


class Comment(Model):
    """A comment of the operator's on an item: on a passage of it, one of its decisions among them, or on it whole."""

    item: int
    quote: Quote | None = None
    """The passage it's on; none for a comment on the item whole."""
    text: str


class Letter(Model):
    """The operator's message to one conversation, written under its agent's banner in the review and sent with the rest of the reply."""

    to: Conversation
    text: str


class Review(Model):
    """The operator's reply, as they wrote it while reading: their comments on the items it covers, and their messages to agents.

    Every conversation it's sent to gets all of it, reading its own message
    and items first and the rest as context (`docs/dashboard.md`, *The
    review*).
    """

    reason: Literal["review"] = "review"
    covers: list[int]
    """The items it answers, in order; none where it only carries messages."""
    comments: list[Comment] = []
    letters: list[Letter] = []
    """The messages it carries, each to its conversation."""


type Reason = Annotated[
    Message
    | Friction
    | HowItWent
    | Stop
    | Question
    | Answer
    | Approval
    | HeldChange
    | Flagged
    | Review,
    Field(discriminator="reason"),
]
"""Why an item is there."""


class Diff(Model):
    """An approval's whole diff, coloured, kept beside its item and read only on request."""

    text: str


class Text(Model):
    """A file's content, as text."""

    kind: Literal["text"] = "text"
    text: str


class Binary(Model):
    """A file's content that isn't text, which isn't shown: its size alone."""

    kind: Literal["binary"] = "binary"
    size: int
    """In bytes."""


type Content = Annotated[Text | Binary, Field(discriminator="kind")]
"""What a file holds, as the operator is shown it."""


def content(data: bytes) -> Content:
    r"""Return a file's bytes as they're shown: text where they're UTF-8 with no NUL byte, as git takes a file for text; else binary.

    >>> content(b"a = 1\n")
    Text(kind='text', text='a = 1\n')
    >>> content(b"\x89PNG\x00")
    Binary(kind='binary', size=5)
    """
    if b"\0" in data:
        return Binary(size=len(data))
    try:
        return Text(text=data.decode())
    except UnicodeDecodeError:
        return Binary(size=len(data))


type ApiKind = Literal[
    "export-added", "export-removed", "class-added", "signature-changed"
]
"""How a change touches what other code can depend on, as the judge finds it
(`lup_dev.policy.surface`) and the review says it."""

type Held = Literal["held", "flagged"]
"""How the declaration takes what a change asks: held for the operator's answer,
or flagged for their review (`Project.held`, `Project.flagged`)."""

type Taken = Held | Literal["told"]
"""How the declaration takes a finding of lup's on a line a change touches: held
or flagged where it names the finding's rule, else told to the agent alone."""


class ApiChanged(Model):
    """One change to a file's public API: its kind, and the name it changes."""

    kind: ApiKind
    name: str
    """Dotted inside the module: `Delivery`, `Delivery.withdrawn`."""


class Asked(Model):
    """One thing a file of a change asks the operator, as the judge read it: by the name the declaration holds or flags it by, and where it is in the file."""

    name: str
    """`protected`, `operator`, `new-file`, `whole-file`, `public-api` or `ignore`."""
    taken: Held
    line: int | None = None
    """The line it's on, counted from 1: an `ignore` added, or the name a
    public-API change changes; none for what's about the file whole, or a name
    the engine didn't place."""
    side: Literal["before", "after"] = "after"
    """Which version of the file `line` is in: what it becomes, or, for a name
    the change takes out of a package's root, what it was."""
    api: ApiChanged | None = None
    """What it changes of the public API, for `public-api`; none for any other."""


class Found(Model):
    """One of lup's findings on the lines a change touches, as the declaration takes its rule."""

    rule: str
    message: str
    """What's wrong there, whole, as the agent is told it."""
    steer: str = ""
    start: int
    """Its first line, counted from 1, in what the file becomes."""
    end: int
    """Its last line."""
    taken: Taken


class Reading(Model):
    """The judge's reading of one file a change touches, which the review opens it by: its role, what it asks the operator, and the lines that matter (`docs/dashboard.md`, *The review*)."""

    role: str
    """The path's role, as the judge names it (`Roles.role`): `production`,
    `test`, `docs`…"""
    asks: list[Asked] = []
    """What it asks, held or flagged, in the judge's order: about the file whole,
    each change to the public API, each `ignore` added. A rule the declaration
    holds or flags asks through its findings (`findings`)."""
    findings: list[Found] = []
    """lup's findings on the lines the change touches, each taken as the
    declaration takes its rule."""


class ChangedFile(Model):
    """One file a change touches, whole on each side: what it was, and what it becomes, with the judge's reading of it."""

    path: Path
    """From the root of the worktree it's in, or of the repository."""
    before: Content | None
    """What it held; none for a file the change creates."""
    after: Content | None
    """What it holds once changed; none for a file the change deletes."""
    reading: Reading | None = None
    """The judge's reading of the change to it, which the review opens it by;
    none where it wasn't judged."""

    @classmethod
    def of(
        cls,
        path: Path,
        before: bytes | None,
        after: bytes | None,
        reading: Reading | None = None,
    ) -> ChangedFile:
        """Return the file at `path` from its bytes on each side, none where it isn't there, with the judge's `reading` of it where it was judged."""
        return cls(
            path=path,
            before=None if before is None else content(before),
            after=None if after is None else content(after),
            reading=reading,
        )


class ChangedFiles(Model):
    """The files an approval or a held change touches, each whole, kept beside its item and read only on request."""

    files: list[ChangedFile]


class Waiting(Model):
    """Waiting for its recipient: told at the conversation's next chance, or shown in the operator's inbox."""

    state: Literal["waiting"] = "waiting"
    announced: datetime | None = None
    """When it was announced as too long for a hook, waiting for `wait_inbox` to
    return it whole; none where it wasn't."""


class Told(Model):
    """Told to the conversation it's for, once."""

    state: Literal["told"] = "told"
    at: datetime
    how: How


class Answered(Model):
    """A question the operator answered."""

    state: Literal["answered"] = "answered"
    at: datetime
    answer: int
    """The answer's item number."""


class Done(Model):
    """A message the operator read, off their list."""

    state: Literal["done"] = "done"
    at: datetime


class Decided(Model):
    """An approval or a held change the operator answered, wherever they answered it: yes or no, and what they add."""

    state: Literal["decided"] = "decided"
    at: datetime
    approved: bool
    comment: str = ""


class Superseded(Model):
    """An approval of a host zone a later approval of the same repository replaced, the integration branch's tip having moved."""

    state: Literal["superseded"] = "superseded"
    at: datetime
    by: int
    """The approval replacing it."""


class Withdrawn(Model):
    """A message or a question its sender took back while it waited for the operator, who needn't read or answer it."""

    state: Literal["withdrawn"] = "withdrawn"
    at: datetime
    why: str
    """The sender's reason, in a line."""


type State = Annotated[
    Waiting | Told | Answered | Done | Decided | Superseded | Withdrawn,
    Field(discriminator="state"),
]
"""Where an item stands."""


class Rank(Model):
    """What an item's kind is to the operator: where the review shows it among the rest, and whether it raises a desktop notice as it reaches them (`ranked`)."""

    name: Literal["waiting on you", "news", "flag"]
    order: int
    """Where its items come in the review, the lowest first."""
    notifies: bool


def ranked(reason: Reason) -> Rank:
    """Return the rank of an item of `reason`'s kind: the one place each kind's is said, which the review orders by (`page/src/review.ts`) and the desktop notices read (`Delivery.noticed`).

    | Rank | Kinds | Order | Notice |
    |---|---|---|---|
    | waiting on you | a question, a held change, an approval, a problem (`blocked`), a disagreement, a question sent as a message | first | yes |
    | news | a note, a turn's last words among them, a friction, how the work went, a stop by choice | next | no |
    | flag | a write that landed flagged | last | no |

    A message ranks by its kind, whichever tool sent it: a note is a remark to
    read, where a doubt that needs the operator soon is a question, asked.
    The operator's own items, an answer and a review, go to agents, so neither
    the review nor a notice reads theirs.

    >>> ranked(Stop(why="Done."))
    Rank(name='news', order=1, notifies=False)
    >>> ranked(Message(kind="note", text="It rests on the cache.")).name
    'news'
    """
    match reason:
        case Message(kind="note") | Friction() | HowItWent() | Stop():
            return Rank(name="news", order=1, notifies=False)
        case Flagged():
            return Rank(name="flag", order=2, notifies=False)
        case Message() | Question() | Approval() | HeldChange() | Answer() | Review():
            return Rank(name="waiting on you", order=0, notifies=True)


class Item(Model):
    """One item in a party's inbox."""

    number: int
    reason: Reason
    sender: Party
    recipient: Party
    """Whose inbox it's in, who's told it."""
    addressed: Conversation | None = None
    """Whom it was for, where it was passed on from a conversation that had
    ended; none where it wasn't."""
    worktree: Path | None = None
    """The worktree of the launch it was made in; none for the operator's own."""
    call: str | None = None
    """The runtime's id for the tool call that made it, its moment in its
    sender's record; none where no agent's call did (`ShowContext`)."""
    made: datetime
    state: State = Waiting()

    @computed_field
    @property
    def rank(self) -> Rank:
        """Its kind's rank (`ranked`), carried with it to the dashboard's page, whose review orders by it."""
        return ranked(self.reason)

    def of(self, repository: Path) -> bool:
        """Say whether it's of the repository whose git directory is `repository` alone: each conversation it's from, to or for is of it, and an approval is about it; one between the operator and themselves alone is of none."""
        parties = [self.sender, self.recipient, self.addressed]
        about = [self.reason.repository] if isinstance(self.reason, Approval) else []
        found = [
            *(each.repository for each in parties if isinstance(each, Conversation)),
            *about,
        ]
        return bool(found) and all(each == repository for each in found)


class Whereabouts(Model):
    """Where a conversation was last heard: the launch its session runs in, and whether it has ended."""

    conversation: Conversation
    launch: str
    worktree: Path
    since: datetime
    """When it was first heard in that launch."""
    ended: datetime | None = None
    """When its conversation ended, at its `conversation-ended` hook; none while
    it goes on."""


def read[M: Model](path: Path, model: type[M]) -> M:
    """Read a stored file of the inbox as `model`, naming it where it doesn't read."""
    try:
        found = read_model(path, model)
    except (OSError, ValidationError) as unread:
        message = f"the inbox's {path} doesn't read: {unread}"
        raise InboxError(message) from unread
    if found is None:
        message = f"the inbox's {path} is gone"
        raise InboxError(message)
    return found


class TalkComment(Model):
    """A comment of the operator's on a conversation they read: on a line or a passage of what the agent said at one step, or, at none, their message on the conversation whole."""

    step: int | None
    quote: Quote | None = None
    text: str


class Sent(Model):
    """A message the operator sent a conversation from where they read it: the item it made, what it said, how many steps the conversation had then, and when."""

    number: int
    text: str
    after: int
    at: datetime


class Talk(Model):
    """What the operator writes on one conversation they read, until it's sent, and the messages they sent it from there."""

    comments: list[TalkComment] = []
    sent: list[Sent] = []


class Draft(Model):
    """The operator's reply as they build it while reading: their comments, their messages to agents, the items they took off their list and the ones they parked; kept until it's sent."""

    comments: list[Comment] = []
    letters: list[Letter] = []
    """Messages to agents, each written under its agent's banner, sent with the
    rest of the reply whatever's parked."""
    done: list[int] = []
    """Items read and taken off the list when the draft is sent, with no
    comment of their own."""
    parked: list[int] = []
    """Items left for a later reply: what's drafted on them stays drafted when
    the rest is sent."""

    def written(self) -> list[Letter]:
        """Return the messages that say something, in order: those the draft sends."""
        return [each for each in self.letters if each.text.strip()]

    def covered(self) -> list[int]:
        """Return the items the draft answers, in order: each with a comment or marked done, but for the parked ones."""
        mentioned = [*(each.item for each in self.comments), *self.done]
        wanted = [each for each in mentioned if each not in self.parked]
        return sorted(dict.fromkeys(wanted))

    def kept(self) -> Draft:
        """Return what stays drafted once the draft is sent: what's on the parked items."""
        return Draft(
            comments=[each for each in self.comments if each.item in self.parked],
            parked=self.parked,
        )


class Inbox(MutableModel):
    """Every item and every conversation's whereabouts, as the host service holds them, each change written through to its file."""

    layout: InboxLayout
    items: dict[int, Item] = {}
    """By number."""
    whereabouts: dict[str, Whereabouts] = {}
    """By conversation's key."""
    changes: Changes | None = None
    """Told each time an item is written, so the host service's watches see it
    (`host/watch.py`); none tells nothing."""

    @classmethod
    def opened(cls, layout: InboxLayout, changes: Changes | None = None) -> Inbox:
        """Read the inbox kept at `layout`, telling `changes` of each item written; one never written is empty.

        Raise `InboxError` naming a file that doesn't read.
        """
        items = [read(path, Item) for path in layout.items.glob("*.json")]
        places = [read(path, Whereabouts) for path in layout.parties.glob("*.json")]
        return cls(
            layout=layout,
            items={item.number: item for item in items},
            whereabouts={place.conversation.key(): place for place in places},
            changes=changes,
        )

    def draft(self) -> Draft:
        """Return the operator's draft reply; an empty one where they have none."""
        return read_model(self.layout.draft, Draft) or Draft()

    def drafted(self, draft: Draft) -> Draft:
        """Keep the operator's draft reply, and return it."""
        write_model(self.layout.draft, draft)
        if self.changes is not None:
            self.changes.changed()
        return draft

    def talk(self, conversation: Conversation) -> Talk:
        """Return what the operator wrote on `conversation` where they read it; nothing where they've written nothing."""
        return read_model(self.layout.talk(conversation.key()), Talk) or Talk()

    def talked(self, conversation: Conversation, talk: Talk) -> Talk:
        """Keep what the operator wrote on `conversation`, in place of the last, and return it."""
        write_model(self.layout.talk(conversation.key()), talk)
        return talk

    def kept(self, item: Item) -> Item:
        """Write `item` through to its file, and hold it."""
        write_model(self.layout.item(item.number), item)
        self.items = {**self.items, item.number: item}
        if self.changes is not None:
            self.changes.changed()
        return item

    def made(
        self,
        reason: Reason,
        sender: Party,
        recipient: Party,
        worktree: Path | None,
        at: datetime,
        *,
        call: str | None = None,
    ) -> Item:
        """Make an item, numbered after every other, and keep it; `call` is the runtime's id for the agent's call that made it, where one did.

        One for a conversation that has ended goes to its session's main
        conversation, saying whose it was.
        """
        addressed = self.passed(recipient)
        item = Item(
            number=max(self.items, default=0) + 1,
            reason=reason,
            sender=sender,
            recipient=recipient if addressed is None else addressed.main(),
            addressed=addressed,
            worktree=worktree,
            call=call,
            made=at,
        )
        return self.kept(item)

    def passed(self, recipient: Party) -> Conversation | None:
        """Return `recipient` where it's a conversation that has ended, whose items go to its session's main one; none else."""
        match recipient:
            case Conversation(agent=str()) as conversation:
                place = self.whereabouts.get(conversation.key())
                if place is not None and place.ended is not None:
                    return conversation
                return None
            case _:
                return None

    def item(self, number: int) -> Item:
        """Return item `number`, or say there's none."""
        found = self.items.get(number)
        if found is None:
            message = f"the inbox holds no item {number}"
            raise InboxError(message)
        return found

    def waiting(self, recipient: Party) -> list[Item]:
        """Return the items waiting for `recipient`, oldest first."""
        ordered = [self.items[number] for number in sorted(self.items)]
        return [
            item
            for item in ordered
            if item.recipient == recipient and isinstance(item.state, Waiting)
        ]

    def about(self, repository: Path) -> list[Item]:
        """Return the items about `repository`, oldest first: those a conversation of it sent or was sent, and the approvals of its host zone."""

        def of(party: Party) -> bool:
            return isinstance(party, Conversation) and party.repository == repository

        ordered = [self.items[number] for number in sorted(self.items)]
        return [
            item
            for item in ordered
            if of(item.sender)
            or of(item.recipient)
            or (
                isinstance(item.reason, Approval)
                and item.reason.repository == repository
            )
        ]

    def exchanged(self, conversation: Conversation) -> list[Item]:
        """Return the items `conversation` sent or was sent, oldest first, in every state: those for it passed on to its session's main conversation once it ended among them."""
        ordered = [self.items[number] for number in sorted(self.items)]
        return [
            item
            for item in ordered
            if conversation in (item.sender, item.recipient, item.addressed)
        ]

    def reviewed(self, repository: Path | None = None) -> datetime | None:
        """Return when the operator last settled an item of theirs, read, answered or decided, from the review or a terminal, of `repository` alone where one's given (`Item.of`); none before they first did."""
        return max(
            (
                item.state.at
                for item in self.items.values()
                if item.recipient == Operator()
                and isinstance(item.state, Done | Answered | Decided)
                and (repository is None or item.of(repository))
            ),
            default=None,
        )

    def asking(self, repository: Path, fingerprint: str) -> Item | None:
        """Return the approval waiting for the operator about one zone: the repository's, at `fingerprint`; none where there's none."""
        return next(
            (
                item
                for item in self.waiting(Operator())
                if isinstance(item.reason, Approval)
                and item.reason.repository == repository
                and item.reason.fingerprint == fingerprint
            ),
            None,
        )

    def gathering(
        self, sender: Conversation, worktree: Path, path: Path
    ) -> Item | None:
        """Return the item a write of `sender`'s to `path` in `worktree` that landed flagged joins, rather than making one of its own; none where it makes one.

        One item for each conversation and file while the operator hasn't read
        it: it's read once it's off their list, and while their draft marks it
        read or comments on it, so what they're writing on stays as they read it.
        """
        draft = self.draft()
        read = [*draft.done, *(each.item for each in draft.comments)]
        return next(
            (
                item
                for item in reversed(self.waiting(Operator()))
                if isinstance(item.reason, Flagged)
                and item.sender == sender
                and item.reason.worktree == worktree
                and item.reason.path == path
                and item.number not in read
            ),
            None,
        )

    def attached(self, number: int, diff: str, files: list[ChangedFile]) -> None:
        """Keep approval, held change or flagged write `number`'s whole diff and each file it changes beside it, each in a file of its own, in place of those kept before."""
        write_model(self.layout.diff(number), Diff(text=diff))
        self.filed(number, files)

    def filed(self, number: int, files: list[ChangedFile]) -> None:
        """Keep each file approval, held change or flagged write `number` changes beside it, whole, in place of those kept before: an approval's files once their types are read, a flagged write's as a later one joins it."""
        write_model(self.layout.changed(number), ChangedFiles(files=files))

    def diff(self, number: int) -> str:
        """Return approval, held change or flagged write `number`'s whole diff, or say it isn't kept."""
        return read(self.layout.diff(number), Diff).text

    def files(self, number: int) -> list[ChangedFile]:
        """Return each file approval, held change or flagged write `number` changes, whole, or say they aren't kept."""
        return read(self.layout.changed(number), ChangedFiles).files

    def placed(self, place: Whereabouts) -> Whereabouts:
        """Write a conversation's whereabouts through to its file, and hold them."""
        key = place.conversation.key()
        write_model(self.layout.party(key), place)
        self.whereabouts = {**self.whereabouts, key: place}
        return place
