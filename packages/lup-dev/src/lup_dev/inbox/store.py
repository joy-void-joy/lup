"""lup's inbox: its items and its parties, kept one JSON file each in lup's state.

`docs/inbox.md`, *Parties and items*. Every party has an inbox: the
operator, and each conversation of each session, their main one or one of their
subagents. A conversation is keyed by their runtime, their session's id and their
own, within a repository, rather than by the launch they run in, so a session
resumed in a launch of their own finds what waited for them there.

An item has a number, one sequence per user, cited `@12` wherever it's named
(`cited`), so the operator answers `@12`, or `12`; a reason (a message with its
kind, a question with its numbered decisions, an answer, an approval asked yes
or no; a friction, how it felt, or a stop by choice, each as the
agent's tool took it; a change held, or a write that landed flagged, as the
judge put it), whose kind ranks it (`ranked`); a sender and a recipient; when
it was made; and its state: waiting, told (when, and how), answered, done, or
for an approval decided. An item for a conversation that has ended goes to their
session's main conversation, saying whose it was. A subagent's end, and a copy
of what they say of their work, go to the conversation that spawned them, which
their whereabouts keep: quiet items, told at a call and never holding a turn's end.
A message one conversation sends another, their parent or one of their own
subagents, is that other's, and the operator reads a copy (`Message.to`).

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

from pydantic import Field, JsonValue, ValidationError, computed_field, model_validator

from lup.sessions import results
from lup.tools import speaking
from lup.types import Model, MutableModel
from lup_dev.host.protocol import HostError
from lup_dev.host.watch import Changes, Touched
from lup_dev.inbox.parts import PartId
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
    """A conversation of a session, within a repository: the session's main one, or one of their subagents."""

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
    where they read it (`lup-dev inbox answer`), in the
    conversation's order: told before its words, each quoted with their reply."""
    ending: bool = False
    """Whether lup made it at a session's turn's end rather than the agent
    sending it: their last words, or, where their turn ended on an error from
    the model's API, that error in lup's words. The conversation already shows
    either among its steps, the error as the runtime's text for it."""
    to: Conversation | None = None
    """The conversation it was sent to, where it's the operator's copy of a
    message one conversation sent another (`send`), which they read as news
    whatever its kind; none where its recipient is whom it was sent to."""
    answers: list[int] = []
    """For a turn's last words, the operator's items told to the conversation
    since their last such words, which these words answer: a review, a message, an
    answer. The dashboard shows their words above the agent's (`docs/inbox.md`,
    *A turn's last message*)."""


def labelled(opening: str, parts: dict[str, str]) -> str:
    """Return `opening`, then each of `parts` that says something, after its label, a line each.

    >>> print(labelled("The gate hung.", {"Trying": "check", "Would change": ""}))
    The gate hung.
    Trying: check
    """
    said = [f"{label}: {text}" for label, text in parts.items() if text.strip()]
    return "\n".join([opening, *said] if opening.strip() else said)


class Labelled(Model):
    """A friction or how it felt as the inbox kept it before each was one text in the agent's own words: each part in a field of its own, which the operator read after its label.

    Items kept then still read: each is read as the one text it was shown as
    (`Friction.unlabelled`, `HowItFelt.unlabelled`).
    """

    got_in_the_way: str = ""
    trying: str = ""
    smooth: str = ""
    would_change: str = ""
    felt: str = ""

    def friction(self) -> str:
        """Say a friction as the operator read it: what got in the way, then what the agent was trying and would change, where they said."""
        parts = {"Trying": self.trying, "Would change": self.would_change}
        return labelled(self.got_in_the_way, parts)

    def how_it_felt(self) -> str:
        """Say how it felt as the operator read it: each part the agent filled, after its label; "Nothing notable." where they filled none."""
        parts = {
            "Got in the way": self.got_in_the_way,
            "Smooth": self.smooth,
            "Would change": self.would_change,
            "Felt": self.felt,
        }
        return labelled("", parts) or "Nothing notable."


class Friction(results.Friction):
    """What got in a conversation's way, which they told the operator at the moment it did (`friction`), in their own words: news to read, never a question."""

    reason: Literal["friction"] = "friction"

    @model_validator(mode="before")
    @classmethod
    def unlabelled(cls, stored: JsonValue) -> JsonValue:
        """Read a friction kept before it was one text, its parts each in a field of its own, as the one text the operator read (`Labelled.friction`).

        >>> kept = {"got_in_the_way": "The gate hung.", "trying": "check"}
        >>> print(Friction.model_validate(kept).text)
        The gate hung.
        Trying: check
        """
        match stored:
            case {"got_in_the_way": str()} if "text" not in stored:
                return {"text": Labelled.model_validate(stored).friction()}
            case _:
                return stored


class HowItFelt(results.HowItFelt):
    """How it is for a conversation's agent, as they told the operator (`how_it_felt`), whenever something was present for them or near the end of a piece of work, in their own words: news to read."""

    reason: Literal["how it felt"] = "how it felt"

    @model_validator(mode="before")
    @classmethod
    def unlabelled(cls, stored: JsonValue) -> JsonValue:
        """Read one kept before how it felt was one text, its parts each in a field of its own, as the one text the operator read (`Labelled.how_it_felt`).

        >>> HowItFelt.model_validate({"got_in_the_way": "", "felt": "Calm."}).text
        'Felt: Calm.'
        """
        match stored:
            case {"got_in_the_way": str()} if "text" not in stored:
                return {"text": Labelled.model_validate(stored).how_it_felt()}
            case _:
                return stored


class Stop(speaking.Stop):
    """A conversation ending their work by their own choice, saying why (`stop`): news to read, where being blocked is a problem."""

    reason: Literal["stop"] = "stop"

    @property
    def text(self) -> str:
        """Say it as the operator reads it: why the agent stopped."""
        return self.why


class Ended(Model):
    """A subagent's end, for the conversation that spawned them: their name, whether they ended their turn, were stopped or failed, their last message where their runtime doesn't hand that to their parent itself, and what they said at each end lup held, which no runtime hands on."""

    reason: Literal["ended"] = "ended"
    name: str
    """How lup calls them: their own name, or their kind and their runtime's id."""
    stopped: bool = False
    """Whether they were stopped before they ended their turn, rather than ending it."""
    failed: str | None = None
    """Where their turn ended on an error from the model's API, the error's kind
    in their runtime's word (`rate_limit`), which says whether trying again
    makes sense; none where they ended their turn or were stopped. The error's
    own words are their runtime's to hand on (`handed`), so lup doesn't tell
    them twice."""
    handed: bool = False
    """Whether their runtime hands their last message to their parent itself,
    so lup leaves it out rather than tell it twice."""
    said: str | None = None
    """Their last message, whole, where their runtime doesn't hand it on; none
    where it does, or the subagent left none."""
    held: list[str] = []
    """What they said at each end of their turn lup held to tell them what
    waited, oldest first, whole: their report, often. Each runtime hands a
    parent only the words of the end it lets through, the next one's
    (`docs/field-notes.md`, *A subagent's end*), so lup hands these on whoever
    hands the last."""

    @property
    def kept(self) -> list[str]:
        """Return what they said at each end lup held, as lup hands it on: those saying something."""
        return [each for each in self.held if each.strip()]

    @property
    def earlier(self) -> str | None:
        """Say what comes before what they said at each end lup held, where it held one that said something; none where it held none.

        >>> Ended(name="parser", held=["Done."]).earlier
        'Before that, lup held an end of their turn to tell them what waited, and no runtime hands you what they said there:'
        """
        if not self.kept:
            return None
        ends = "an end" if len(self.kept) == 1 else "ends"
        return (
            f"Before that, lup held {ends} of their turn to tell them what waited, "
            "and no runtime hands you what they said there:"
        )

    @property
    def passed(self) -> str | None:
        """Return their last message as lup hands it on; none where they were stopped or failed, their runtime hands it on, or they left none."""
        if self.stopped or self.failed is not None or self.handed:
            return None
        if self.said is None or not self.said.strip():
            return None
        return self.said

    @property
    def heading(self) -> str:
        """Say how they ended, in lup's words, and where their last message is.

        >>> Ended(name="parser", failed="rate_limit", handed=True).heading
        "They failed on an error from the model's API (rate_limit). Your runtime's notice of their end says more."
        """
        if self.failed is not None:
            failed = f"They failed on an error from the model's API ({self.failed})."
            told = (
                " Your runtime's notice of their end says more." if self.handed else ""
            )
            return failed + told
        if self.stopped:
            return "They were stopped before they ended their turn."
        if self.handed:
            return "They ended their turn. Their last message reaches you from your runtime."
        if self.passed is None:
            return "They ended their turn, with no last message."
        return "They ended their turn. Their last message:"

    @property
    def text(self) -> str:
        """Say it as lup tells the parent: how they ended, their last message where lup hands that on, then what they said at each end lup held.

        >>> print(Ended(name="parser", said="Done: three call sites.").text)
        They ended their turn. Their last message:
        Done: three call sites.
        >>> print(Ended(name="parser", handed=True, said="Done.").text)
        They ended their turn. Their last message reaches you from your runtime.
        >>> print(Ended(name="parser", handed=True, said="Done.", held=["Parsed."]).text)
        They ended their turn. Their last message reaches you from your runtime.
        Before that, lup held an end of their turn to tell them what waited, and no runtime hands you what they said there:
        Parsed.
        """
        last = [] if self.passed is None else [self.passed]
        held = [] if self.earlier is None else [self.earlier, *self.kept]
        return "\n".join([self.heading, *last, *held])


class Place(Model):
    """A passage of the operator's words: the part of their item it's in, where in that part's text, and the passage itself."""

    part: PartId
    start: int
    """Where it starts in the part's text, counted in characters."""
    end: int
    """Where it ends, after its last character."""
    text: str


class Citation(Model):
    """A citation of the operator's words in an item a conversation sent: where it's written, what it names, and the passage it found, or the places it might mean where it found none or several (`inbox/citations.py`).

    Written `@820.9[first words … last words]`, `@820[…]` for any part of item
    820, or `@820.9` for the part whole (`docs/inbox.md`, *Citing the
    operator's words*).
    """

    said: str
    """The citation as it's written: `@820.9[first words … last words]`."""
    start: int
    """Where it's written in the item's text, its `@`, counted in characters."""
    end: int
    """Where it ends there, after its `]`, or its id's last digit."""
    item: int
    part: int | None = None
    """The part named; none where it names the item alone."""
    words: str | None = None
    """What's between its brackets, as written; none for an id alone."""
    found: Place | None = None
    """The passage it names, where it names one; none where it names none, or
    several."""
    candidates: list[Place] = []
    """Where it found none, the places of the operator's words its words read
    elsewhere; where it found several, each of them."""


class Unresolved(Model):
    """lup's word to a conversation that citations in an item they sent the operator named no passage, or several: told at once, holding their turn's end once, so they can fix them with `edit` (`docs/inbox.md`, *Citing the operator's words*)."""

    reason: Literal["unresolved"] = "unresolved"
    of: int
    """The item the citations are in."""
    citations: list[Citation]
    """Those that named no passage, or several, each with the places it might
    mean, as the item kept them then."""


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
    first: bool = False
    """Whether it's the zone's first approval, which trusts the repository as it
    is, its files read by their roles alone: the review folds each under its
    header (`docs/dashboard.md`, *The review*)."""


class AtLanding(Model):
    """What a hold at landing waits on: one file the landing changes, flagged on a branch it lands and not yet approved, and the landing it holds (`lup_dev.policy.landing`)."""

    onto: str
    """The gated branch the landing moves, by its full name: `refs/heads/dev`."""
    tip: str
    """The commit the landing puts there."""
    path: Path
    """The file, from the repository's root."""
    branches: list[str]
    """The branches landed whose flags on the file it covers."""
    flags: list[int]
    """The flagged writes it covers, each approved with it."""
    since: int | None = None
    """The item whose version of the file its diff starts from: the latest the
    operator saw of it on those branches, a flagged write or a hold at landing
    they approved, read or commented on, so what changed in answer to a comment
    is what they read; none where they saw none, or last saw it marking it
    reviewed (`reviewed`), and it starts from the file at the gated branch's
    tip where they saw none."""
    reviewed: datetime | None = None
    """When the operator marked the version its diff starts from reviewed in
    its agent's drawer, where that's the latest they saw of it
    (`lup_dev.policy.reviewed`); none else."""


class HeldChange(Model):
    """A change held for the operator's answer, yes or no: what's held and why, its diff and each file held kept beside the item (`Inbox.diff`, `Inbox.files`).

    The judge's (`lup_dev.policy.holds`): a write that asks waits for the
    answer inside its hook, or, for what a move of `HEAD` brought, is asked
    after the fact, no agent waiting. Or a landing's (`lup_dev.policy.landing`):
    a file flagged on a branch it lands, which the landing waits on, its answer
    the item's own state.
    """

    reason: Literal["held"] = "held"
    text: str
    """The question, answered yes or no: let the change land?"""
    summary: str
    """Each file held, and what it asks."""
    worktree: Path
    key: str | None = None
    """The hold's key in the worktree's store, which the answer is written to;
    none for a hold at landing."""
    commit: str | None = None
    """The commit a move of `HEAD` reached, where it's asked after the fact; none
    where an agent waits on it."""
    landing: AtLanding | None = None
    """What it holds at landing, for a landing's hold; none for the judge's."""


class Flagged(Model):
    """A write that landed flagged for the operator's review, holding no one: what the file's whole change since the item was made flags, its diff and the file kept beside the item (`Inbox.diff`, `Inbox.files`).

    The judge's (`lup_dev.policy.flags`). A later write to the same file by the
    same conversation, flagged or not, joins the item while it gathers them
    (`Inbox.gathering`), the file kept whole since the first and as it stands.
    Marked read with nothing to add, it's approved (`Decided`); commented on or
    replied to, it's read and not approved (`Done`), and the landing of its
    branch waits on it (`lup_dev.policy.landing`). Still waiting once it's left
    nothing to hold, its branch gone or its file left unchanged by its
    branch's landing, a landing takes it back (`Withdrawn`).
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
    branch: str | None = None
    """The branch its worktree had checked out, whose landing waits on it until
    the operator approves it (`lup_dev.policy.landing`); none on a detached
    `HEAD`, and for a flag kept before landings waited on flags, which holds
    none."""
    writes: int = 1
    """How many writes it gathers, the flagged one that made it and each by the
    same conversation to the file since: the page reads its file again as it
    grows."""


class Quote(Model):
    """What a comment of the operator's is on, and where: lines of one block of a view the review showed them, as that block stood when they wrote it, and the passage of those lines as the agent reads it.

    Every comment and remark is anchored so (`docs/dashboard.md`, *The
    review*): the page keeps it under the last line it quotes as the block
    changes, following the block's own lines from one version to the next,
    and says it's outdated where the lines it quotes aren't what stands there.
    One kept from a draft written before quotes named their block, `block`
    empty, has `start` and `end` counted in its item's text whole as the page
    showed it then, its files' lines among it: the page places it once by
    them, and names its block, or, where nothing it shows is there, keeps it
    on its item whole.
    """

    text: str
    """The passage as the agent reads it: the words selected; a changed
    file's lines under its path and their numbers, each marked as a diff
    marks it."""
    block: str = ""
    """The block it's on, by its id: its view instance's and its own
    (`blockId`, `page/src/views.ts`), which the block keeps across layouts."""
    version: str = ""
    """The block's version as it was written on: the block's own where it
    says one, as git names a file's content; else what the page made of its
    lines."""
    line: int = 0
    """The block's first line it's on, counted from 0 in that version."""
    lines: list[str] = []
    """The block's lines it's on, each whole, in order, as that version held
    them: the comment is under the last."""
    start: int
    """Where the passage starts, counted in those lines joined by line
    breaks."""
    end: int
    """Where it ends, counted in those lines joined."""


class Comment(Model):
    """A comment of the operator's on an item: on a passage of it, one of its decisions among them, or on it whole; or, in a thread, on a reply the agent made to an earlier comment."""

    id: str = ""
    """What names it among what's drafted, which the page gives it as it's
    opened and keeps it by; empty for one drafted before what's drafted had
    ids, which the page names as it reads the draft."""
    item: int
    quote: Quote | None = None
    """The passage it's on; none for a comment on the item whole. On a reply
    (`on`), a passage of that reply's text, its offsets counted there."""
    on: PartId | None = None
    """The reply of the agent's it answers, by its id, where it's a comment
    copies before kept on a reply made with `reply` (`Reply`); none for a
    comment on the item's own text, as the dashboard writes every one."""
    text: str


class Letter(Model):
    """The operator's message to one conversation, written under its agent's banner in the review and sent with the rest of the reply."""

    id: str = ""
    """What names it among what's drafted, as a comment's does (`Comment.id`)."""
    to: Conversation
    text: str


class Quoted(Model):
    """Lines of a file as a comment quoted them, in the version of the file the comment was written on: so what changed since can be told when it reaches the agent."""

    worktree: Path
    path: Path
    """The file, from the worktree's root."""
    version: str
    """git's id for the file's content as the comment was written on it."""
    first: int
    """The number of the first line quoted, counted from 1 in that version."""
    lines: list[str]
    """The lines quoted, in order, as that version held them."""


class Remark(Model):
    """A comment of the operator's in one of an agent's drawers in the review (`docs/dashboard.md`, *The drawers*): on a passage of the agent's conversation, or on lines of their branch's code since the operator approved it, as the lines stood when it was written."""

    id: str = ""
    """What names it among what's drafted, as a comment's does (`Comment.id`)."""
    to: Conversation
    quote: Quote
    """The passage, and where it is: the block of the drawer's view it's on,
    one of the agent's words or a file."""
    text: str
    step: int | None = None
    """The step of the conversation the passage is of, for a remark on its
    words drafted before quotes named their block (`Quote.block`), which the
    page places it by once; none for any other."""
    code: Quoted | None = None
    """The lines of the file the passage is, and their version, for a comment
    on code; none for one on the conversation's words."""


class Review(Model):
    """The operator's reply, as they wrote it while reading: their comments on the items it covers, their messages to agents, and their remarks in the agents' drawers.

    Every conversation it's sent to gets all of it, reading their own
    message and items first and the rest as context (`docs/dashboard.md`, *The
    review*).
    """

    reason: Literal["review"] = "review"
    covers: list[int]
    """The items it answers, in order; none where it only carries messages."""
    comments: list[Comment] = []
    letters: list[Letter] = []
    """The messages it carries, each to its conversation."""
    remarks: list[Remark] = []
    """The comments it carries from the drawers, each to its conversation."""


type Reason = Annotated[
    Message
    | Friction
    | HowItFelt
    | Stop
    | Ended
    | Unresolved
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
    "export-added",
    "export-removed",
    "class-added",
    "class-removed",
    "function-added",
    "function-removed",
    "signature-changed",
]
"""How a change touches what other code can depend on, as the judge finds it
(`lup_dev.policy.surface`) and the review says it: a package root's name, a
class, or a function or method, added or removed. `signature-changed` is one
the judge doesn't find (`docs/judging-writes.md`, *The public-API ask*): copies
before found it, and the holds and the files beside items they wrote keep it.
Every value a stored model once accepted stays read: dropped, a copy approved
later can't read a store the one before wrote, and `judged` refuses every
call."""

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
    public-API change adds or removes; none for what's about the file whole, or
    a name the engine didn't place."""
    side: Literal["before", "after"] = "after"
    """Which version of the file `line` is in: what it becomes, or, for a name
    the change removes, what it was."""
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
    """From the root of the worktree it's in, or of the repository; absolute
    for a file outside every repository, the person's profiles, which an
    approval carries unread by the judge."""
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
    """An approval or a held change the operator answered, wherever they answered it: yes or no, and what they add; or a flagged write they approved, marking it read with nothing to add."""

    state: Literal["decided"] = "decided"
    at: datetime
    approved: bool
    comment: str = ""


class Superseded(Model):
    """An approval of a host zone a later approval of the same repository replaced, the integration branch's tip having moved; a hold at landing a later landing's hold on the same file replaced; or lup's word on citations that didn't resolve, its item edited before it was told, its citations read again."""

    state: Literal["superseded"] = "superseded"
    at: datetime
    by: int
    """The approval, or the hold, replacing it; the item edited."""


class Withdrawn(Model):
    """A message or a question its sender took back while it waited for the operator, who needn't read or answer it; or a flagged write lup took back at a landing, left nothing to hold (`lup_dev.policy.landing`), unread, so it's no version the operator saw."""

    state: Literal["withdrawn"] = "withdrawn"
    at: datetime
    why: str
    """The sender's reason, or lup's, in a line."""


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
    | news | a note, a turn's last words among them, a friction, how it felt, a stop by choice, a subagent's end, lup's word on citations that didn't resolve, the operator's copy of a message between conversations | next | no |
    | flag | a write that landed flagged | last | no |

    A message to the operator ranks by its kind, whichever tool sent it: a note
    is a remark to read, where a doubt that needs the operator soon is a
    question, asked. A copy of one a conversation sent another is news of any
    kind, since it waits on that other, not on them. The operator's own items,
    an answer and a review, go to agents, so neither the review nor a notice
    reads theirs; nor a subagent's end, which goes to their parent, nor lup's word
    on citations, which goes to the conversation that wrote them.

    >>> ranked(Stop(why="Done."))
    Rank(name='news', order=1, notifies=False)
    >>> ranked(Message(kind="note", text="It rests on the cache.")).name
    'news'
    """
    match reason:
        case (
            Message(kind="note")
            | Message(to=Conversation())
            | Friction()
            | HowItFelt()
            | Stop()
            | Ended()
            | Unresolved()
        ):
            return Rank(name="news", order=1, notifies=False)
        case Flagged():
            return Rank(name="flag", order=2, notifies=False)
        case Message() | Question() | Approval() | HeldChange() | Answer() | Review():
            return Rank(name="waiting on you", order=0, notifies=True)


class Reply(Model):
    """One reply of an agent's to a part of the operator's item, as copies before kept them, when an agent answered the operator's comments one by one with `reply`: still read, and shown as the agent's words under the operator's (`docs/dashboard.md`, *The review*)."""

    number: int
    """Its own place among the item's parts, after the operator's own, so it's
    cited `@546.6`; the operator's words numbered since come after it
    (`inbox/threads.py`, `spoken`)."""
    to: PartId
    """The part of the item it answers: a comment or a reply of the operator's."""
    text: str
    at: datetime


class Edit(Model):
    """One edit its sender made of an item's text (`edit`): the text whole before it, and when."""

    at: datetime
    before: str


class Item(Model):
    """One item in a party's inbox."""

    number: int
    reason: Reason
    sender: Party
    recipient: Party
    """Whose inbox it's in, who's told it."""
    replies: list[Reply] = []
    """The replies its recipient made to its parts, kept from before agents
    answered in their turn's last words: every value a stored model once
    accepted stays read. Only an item of the operator's has any."""
    citations: list[Citation] = []
    """The citations of the operator's words in its text, each with the passage
    it found or the places it might mean, where a conversation sent it the
    operator (`inbox/citations.py`); read again at each edit."""
    edits: list[Edit] = []
    """Each edit its sender made of its text, oldest first (`edit`): the
    dashboard says it was edited and shows what changed."""
    addressed: Conversation | None = None
    """Whom it was for, where it was passed on from a conversation that had
    ended; none where it wasn't."""
    worktree: Path | None = None
    """The worktree of the launch it was made in; none for the operator's own."""
    call: str | None = None
    """The runtime's id for the tool call that made it, its moment in its
    sender's record; none where no agent's call did (`ShowContext`)."""
    quiet: bool = False
    """Whether it waits for a call of its recipient's, never holding a turn's end
    to be told nor waking an idle session: a subagent's news for their parent,
    whom their runtime wakes for the subagent's end already, so that each end
    costs no turn of their own."""
    made: datetime
    state: State = Waiting()

    @model_validator(mode="before")
    @classmethod
    def felt(cls, stored: JsonValue) -> JsonValue:
        """Read an item kept while `how_it_felt` was `how_it_went`, its reason `how it went`, as how it felt: its reason's kind names the model it's read as, before that model reads it.

        >>> from datetime import UTC, datetime
        >>> kept = {"number": 7, "reason": {"reason": "how it went", "text": "Calm."},
        ...     "sender": {"party": "operator"}, "recipient": {"party": "operator"},
        ...     "made": datetime(2026, 1, 1, tzinfo=UTC)}
        >>> Item.model_validate(kept).reason
        HowItFelt(text='Calm.', reason='how it felt')
        """
        match stored:
            case {"reason": {"reason": "how it went", **reason}}:
                return {**stored, "reason": {**reason, "reason": "how it felt"}}
            case _:
                return stored

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


def cited(number: int) -> str:
    """Name item `number` as a reader sees it named: `@270`, which nobody takes for a GitHub issue or pull request's `#270`.

    >>> cited(270)
    '@270'
    """
    return f"@{number}"


def item_number(typed: str) -> int:
    """Read an item's number as the operator types it: as it's cited, `@270`, or bare, `270`; anything else raises `ValueError`, which a command line says is an invalid value.

    >>> item_number(cited(270)), item_number("270")
    (270, 270)
    """
    return int(typed.removeprefix("@"))


class Whereabouts(Model):
    """Where a conversation was last heard: the launch their session runs in, and whether they have ended."""

    conversation: Conversation
    launch: str
    worktree: Path
    since: datetime
    """When they were first heard in that launch."""
    ended: datetime | None = None
    """When the conversation ended, at their `conversation-ended` hook; none
    while they go on."""
    parent: Conversation | None = None
    """The conversation that spawned them, for a subagent a conversation
    spawned, who hears of their end and of what they say of their work; none for
    a session's own. The runtime's own agents never reach the inbox (`Spawned.internal`)."""
    held: list[str] = []
    """What they said at each end of their turn lup held to tell them what
    waited, since they were heard there, oldest first: handed to their parent
    with their end (`Ended.held`), since their runtime hands on only the end it
    lets through. Kept here rather than in memory, so a restart of the service
    between the two ends loses none."""
    words: list[str] = []
    """lup's own words left for them, oldest first: told beside their next call
    or at their next turn's or session's start, and never holding their turn's
    end (`Delivery.left`). Kept here, so a restart of the service loses none."""
    felt_asked: bool = False
    """Whether a landing of a branch they worked on has invited them to say how
    the work felt (`Lander.invited`): one does once, whatever launch they're
    heard in."""
    name: str | None = None
    """A subagent's own name as their latest hook was heard, kept once their
    launch has ended, so `inbox` reads them by their name then, and `send`
    reaches them by it; none while they have none, and for a session's own
    conversation, named as their launch (`SessionNames`, `host/names.py`)."""


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
    """What the operator writes on one conversation they read, until it's sent, and the messages they sent the conversation from there."""

    comments: list[TalkComment] = []
    sent: list[Sent] = []


class Marked(Model):
    """What the operator marked in their draft beyond the inbox's own items, applied as the draft is sent: what a block offered (`lup.Offer`), by its action and what it's given, the verb that marked it, and the block it's shown on.

    `docs/dashboard.md`, *The review*. A file of "since you approved" marked
    reviewed, an agent's flagged writes held: each is shown on what it marks,
    undone with `u` as any change to the draft is, and applied by Ctrl+Enter.
    """

    id: str
    """What names it among the draft's marks, as the page gave it."""
    action: str
    """The action, by its name, as the block offered it: for a view the page
    lays out itself until its module serves it, the request the page sends
    (`policy-review-since`)."""
    argument: dict[str, JsonValue] = {}
    verb: str
    """The verb whose key marked it, by its name (`lup.Verb`): `done`, `hold`."""
    says: str
    """What it does, as the line of keys said it: `mark it reviewed`."""
    block: str
    """The id of the block it's shown on, as the page keeps it."""
    version: str | None = None
    """The version of what it marked, where the block says one: a file's, as
    git names its content."""


class Draft(Model):
    """The operator's reply as they build it while reading: their comments, their messages to agents, the items they marked done, declined, or parked, and what else they marked; kept until it's sent."""

    comments: list[Comment] = []
    letters: list[Letter] = []
    """Messages to agents, each written under its agent's banner, sent with the
    rest of the reply whatever's parked."""
    remarks: list[Remark] = []
    """Comments written in the agents' drawers, each to its agent, sent with
    the rest of the reply whatever's parked."""
    done: list[int] = []
    """Items marked done, taken off the list when the draft is sent: read, for
    news; approved, for an approval or a held change, the comments under it
    going with the yes."""
    declined: list[int] = []
    """Approvals and held changes marked declined, answered no when the draft
    is sent, the comments under each going with the no."""
    parked: list[int] = []
    """Items left for a later reply: what's drafted on them stays drafted when
    the rest is sent."""
    marks: list[Marked] = []
    """What else is marked, each applied as the draft is sent, by the page
    (`docs/dashboard.md`, *The review*): kept drafted once the inbox's part is
    sent, until each is applied."""

    def written(self) -> list[Letter]:
        """Return the messages that say something, in order: those the draft sends."""
        return [each for each in self.letters if each.text.strip()]

    def remarked(self) -> list[Remark]:
        """Return the remarks that say something, in order: those the draft sends."""
        return [each for each in self.remarks if each.text.strip()]

    def covered(self) -> list[int]:
        """Return the items the draft answers, in order: each with a comment, marked done or declined, but for the parked ones."""
        mentioned = [
            *(each.item for each in self.comments),
            *self.done,
            *self.declined,
        ]
        wanted = [each for each in mentioned if each not in self.parked]
        return sorted(dict.fromkeys(wanted))

    def kept(self) -> Draft:
        """Return what stays drafted once the inbox's part of the draft is sent: what's on the parked items, and the marks, which the page applies after."""
        return Draft(
            comments=[each for each in self.comments if each.item in self.parked],
            parked=self.parked,
            marks=self.marks,
        )


class Order(Model):
    """Where the dashboard's review lays out its groups, in order, as the operator has seen them: kept on the host, so a page reloaded, or the operator's other page, lays each where it was (`docs/dashboard.md`, *The review*)."""

    places: list[str] = []
    """Each group's place, as the page names it (`Group.place`, `page/src/review.ts`)."""

    def laid(self, places: list[str], gone: list[str]) -> Order:
        """Return the order once a page laid out the groups at `places`, in its order, those at `gone` gone from it.

        Each place kept stays where it is, whatever order the page laid it
        in, so a page that missed a moment, as a phone's asleep, never
        reorders what the others laid out; those it didn't hold come after
        them, in the page's order; and one another page laid out, which this
        one doesn't, stays. Each gone is dropped, but where the page lays it
        out too, so a group that comes back comes after the others, as a new
        one does, and the order holds no more than the groups laid out.
        """
        laid = dict.fromkeys(places)
        kept = [each for each in self.places if each in laid or each not in gone]
        return Order(places=[*kept, *(each for each in laid if each not in kept)])


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
    version: int = 0
    """How many items and whereabouts it has written since it was opened: what's
    made of it in memory, the roster naming its conversations among it
    (`Delivery.roster`), is made again once it changes."""

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

    def order(self) -> Order:
        """Return where the dashboard's review lays out its groups; none where no page has laid any out."""
        return read_model(self.layout.order, Order) or Order()

    def ordered(self, places: list[str], gone: list[str]) -> Order:
        """Keep where the dashboard's review lays out its groups once a page laid them out at `places`, those at `gone` gone from it (`Order.laid`), and return it."""
        order = self.order().laid(places, gone)
        write_model(self.layout.order, order)
        return order

    def talk(self, conversation: Conversation) -> Talk:
        """Return what the operator wrote on `conversation` where they read it; nothing where they've written nothing."""
        return read_model(self.layout.talk(conversation.key()), Talk) or Talk()

    def talked(self, conversation: Conversation, talk: Talk) -> Talk:
        """Keep what the operator wrote on `conversation`, in place of the last, and return it."""
        write_model(self.layout.talk(conversation.key()), talk)
        return talk

    def kept(self, item: Item) -> Item:
        """Write `item` through to its file, and hold it, telling `changes` of each conversation it's from, for, or was addressed to."""
        write_model(self.layout.item(item.number), item)
        self.items = {**self.items, item.number: item}
        self.version += 1
        if self.changes is not None:
            self.changes.changed(
                Touched(
                    repository=each.repository,
                    runtime=each.runtime,
                    session=each.session,
                    agent=each.agent,
                    by="item",
                )
                for each in [item.sender, item.recipient, item.addressed]
                if isinstance(each, Conversation)
            )
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
        quiet: bool = False,
    ) -> Item:
        """Make an item, numbered after every other, and keep it; `call` is the runtime's id for the agent's call that made it, where one did, and `quiet` says it waits for a call (`Item.quiet`).

        One for a conversation that has ended goes to their session's main
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
            quiet=quiet,
            made=at,
        )
        return self.kept(item)

    def passed(self, recipient: Party) -> Conversation | None:
        """Return `recipient` where they're a conversation that has ended, whose items go to their session's main one; none else."""
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
            message = f"the inbox holds no {cited(number)}"
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
        """Return the items `conversation` sent or was sent, oldest first, in every state, including those for them passed on to their session's main conversation once they ended."""
        ordered = [self.items[number] for number in sorted(self.items)]
        return [
            item
            for item in ordered
            if conversation in (item.sender, item.recipient, item.addressed)
        ]

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
        self.version += 1
        return place
