"""Telling each conversation what waits in its inbox, once: at its hooks, by a held call, and by starting a turn of its idle session.

`docs/inbox.md`, *How an agent is told*. Every item waiting for a
conversation is told together, oldest first, by whichever comes first:
- **its next call,** beside it, as the hook's context (`telling`, which the host
  service asks at every hook, the `Post` it's handed); but not at the start of a
  call to lup's own tools (`Heard.served`), whose result tells it: told beside
  `wait_inbox`, an item would reach the model only once the call returned, and
  the call would wait for the next;
- **its turn's end,** where some are still waiting: the end is held once, the
  items its reason, so they never hold an end again (`inbox/ends.py`);
- **`wait_inbox`,** or `ask` with `wait`, a call held until something arrives,
  whose result is the items (`held`). It ends too on what the conversation's
  runtime holds for it, which it hands the agent once the call returns, where
  its records say (`Queues`): what the operator typed in its terminal, a task
  it runs in the background, a subagent's end, each by whose news it is
  (`Waking`), as the call's `on` asks; `within` limits how long it holds;
- **its session's start or resumption,** in the start's answer;
- **its turn's start,** beside the prompt it starts on (`turn-started`);
- **its idle session starting a turn,** for an item the operator's own act made,
  or a message one of its subagents sent it (`send`), to an idle session: one
  whose turn ended, one just started, or one the
  service hasn't heard since it started. A session in its turn is told at its
  next call, or its turn's end, instead. Where its runtime takes a push (the
  waker's `pushed`), the items themselves are pushed through lup's tool
  server on the session's own connection (`pushed`, `Pushes`), held back from
  every other way while the push is pending (`tellable`); its turn's start
  carrying the push's token takes it, counting them told (`taken`), and where
  none does within `patience`, they're told as anything waiting is, said once,
  its launch woken through its messaging socket from then on (`unless_taken`). Through the
  socket (the waker's `woken`, `rung`) what's written is a doorbell, what
  waits and that `wait_inbox` reads it (`doorbell`), never the items: the
  socket takes any local session's message, and the runtime says so of each.
  An idle session starts a turn with either; one the service misjudged as idle
  takes it at its next boundary. It wakes once until the session's next hook.
  Where a runtime has no way, the item waits for the session's next turn, a
  gap its adapter declares.

**Told once.** An item is told when it's written into a hook's answer or a held
call's result, or when a push carrying it is taken, and never again:
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

**As tags.** Each item is told as one element (`tagged`, `inbox/tags.py`),
named for what it is (`message`, `answer`, `review`), its attributes saying its
number, whom it's from, whom it was for where it was passed on, and what it
answers. What the operator said on an agent's item is `<on item kind>`: a
passage they quoted as `<quote part>`, cut to its first line where the part's
id finds the rest (`inbox/threads.py`), with their `<reply id>` under it; a
comment on the whole item as `<comment id>` after the item's first line as
`<opening>`; their message to the agent and their remarks in its drawers each
with its id too, which a citation of their words names (`inbox/citations.py`).
Items only marked read are one `<read items>`. A review's words on other
agents' items and to other agents sit in its `<context>`, each other item named
and never repeated. The doorbell, an announcement and lup's word on citations
that didn't resolve (`<unresolved>`) are tags too. The dashboard shows what's
inside an item's tag (`words`), as its agent reads it.

**A turn's end** (`concluded`, `ended_saying`) is the agent's answer: its last
words, put before the operator with the operator's items told to it since its
last turn's end (`answering`), which the dashboard shows above them; a
subagent's too where the operator's words reached it, since its last words are
otherwise its parent's alone (`subagent_answered`). Its citations of the
operator's words are read as any of an agent's words to them are (`cited`);
where one names no passage, the conversation is told so, an item that holds its
turn's end once, so it can `edit` what it sent (`edited`).

**An item for a conversation that has ended** goes to its session's main
conversation, saying whose it was: one made for it then (`Inbox.made`), and
those still waiting when it ends.

**A message between conversations** (`send`, from a subagent to the
conversation that spawned it, or to one of its own subagents) is an item for
its recipient, told as the operator's are: at its next call, its turn's end,
by `wait_inbox`, or waking its idle session where it's a main conversation.
The operator reads a copy, news whatever its kind (`Message.to`), from its
sender, which a review's comment answers as any message's.

**A subagent's end, and what it says of its work,** reach the conversation that
spawned it (`Whereabouts.parent`): which subagent ended and how, with its last
message where its runtime doesn't hand that on (`ended`); a copy of each
`friction` and `how_it_felt`. Each is quiet (`Item.quiet`): told at the
parent's next call, its turn's or session's start, or by `wait_inbox`, but never
holding a turn's end nor waking an idle session, since its runtime wakes an idle
parent for its subagent's end already, and each end would otherwise cost the
parent a turn of its own. Told beside another item that holds an end or wakes
the session, it goes with it.

The operator hears of each item that reaches them waiting on them through the
desktop's notices; news and flags never raise one (`ranked`).

**A write that landed flagged** (the judge's) holds no one: it joins the item
gathering its conversation's flagged writes to the file while the operator
hasn't read it (`Inbox.gathering`), or is an item of its own (`flagged`). It's
reviewed as a message is: a comment on it reaches its agent with the review,
and marking it read tells the agent nothing.

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
import difflib
import secrets
import textwrap
from collections.abc import Callable, Generator
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, override

from pydantic import TypeAdapter

from lup.events import (
    CallFinished,
    CallStarted,
    ConversationEnded,
    SessionStarted,
    TurnEnded,
    TurnStarted,
    WorktreeAsked,
)
from lup.types import Model, MutableModel
from lup_dev.clock import Clock
from lup_dev.host.courier import Failure, Heard, Post, Posted, Waker
from lup_dev.host.names import Names
from lup_dev.host.pushes import Pushes
from lup_dev.host.records import Queued, Queues, Queuing
from lup_dev.inbox.citations import failing, plainly, resolved, unresolved
from lup_dev.inbox.edits import replaced
from lup_dev.inbox.ends import holding
from lup_dev.inbox.notices import Notices
from lup_dev.inbox.store import (
    Answer,
    Answered,
    Approval,
    AtLanding,
    ChangedFile,
    Comment,
    Conversation,
    Decided,
    Done,
    Draft,
    Edit,
    Ended,
    Flagged,
    Friction,
    HeldChange,
    How,
    HowItFelt,
    Inbox,
    InboxError,
    Item,
    Message,
    Operator,
    Party,
    Passage,
    Question,
    Quoted,
    Reason,
    Remark,
    Review,
    Ruling,
    Stop,
    Superseded,
    Told,
    Unresolved,
    Verdict,
    Waiting,
    Whereabouts,
    Withdrawn,
    cited,
)
from lup_dev.inbox.tags import Tag, inside
from lup_dev.inbox.threads import (
    Anchor,
    addressed_to,
    anchors,
    cue,
    located,
    parts_of,
    spoken,
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
        case Message(ending=True):
            return "the end of a turn"
        case Message(kind="question"):
            return "a question, as a message"
        case Message(kind=kind):
            return f"a {kind}"
        case Friction():
            return "a friction"
        case HowItFelt():
            return "how it felt"
        case Stop():
            return "a stop by choice"
        case Ended(stopped=True):
            return "a subagent stopped"
        case Ended():
            return "the end of a subagent's turn"
        case Unresolved():
            return "lup's word on citations that didn't resolve"
        case Question():
            return "a question"
        case Answer():
            return "an answer"
        case Approval():
            return "an approval"
        case HeldChange():
            return "a held change"
        case Flagged():
            return "a flagged write"
        case Review():
            return "a review"


def opening(item: Item) -> str:
    """Return an item's first line: its text's, a message with no words of its own its first reply's, an answer's comment's, or a review's first message's or comment's."""
    match item.reason:
        case Message(text="", passages=[first, *_]):
            said = first.text
        case (
            Message(text=text)
            | Friction(text=text)
            | HowItFelt(text=text)
            | Stop(text=text)
            | Ended(text=text)
            | Question(text=text)
            | Approval(text=text)
            | HeldChange(text=text)
            | Flagged(text=text)
        ):
            said = text
        case Unresolved(of=of, citations=citations):
            said = plainly(citations, of)
        case Answer(comment=comment):
            said = comment
        case Review(letters=letters, comments=comments):
            said = next((each.text for each in [*letters, *comments]), "")
    return next(iter(said.splitlines()), "")


def body(item: Item) -> str:
    """Return an item's text whole, as its sender wrote it: a question's with each decision numbered, its lean on the line under it, as the dashboard lays it out (`page/src/review.ts`), so a passage quoted there is found here by its offsets (`located`); a review's messages, then its comments."""
    match item.reason:
        case Question(text=text, decisions=decisions):
            numbered = [
                f"{at}. {each.text}\n   lean: {each.lean}"
                for at, each in enumerate(decisions, start=1)
            ]
            return "\n".join([text, *numbered])
        case (
            Message(text=text)
            | Friction(text=text)
            | HowItFelt(text=text)
            | Stop(text=text)
            | Ended(text=text)
            | Approval(text=text)
            | HeldChange(text=text)
            | Flagged(text=text)
        ):
            return text
        case Unresolved(of=of, citations=citations):
            return plainly(citations, of)
        case Answer(comment=comment):
            return comment
        case Review(letters=letters, comments=comments):
            return "\n".join(each.text for each in [*letters, *comments])


def written(item: Item) -> str:
    """Return the text of an item a conversation sent, whole: as it wrote it, a question with its decisions and leans; a change held from it, with what's held and why, or one that landed flagged, with what's flagged."""
    match item.reason:
        case (
            HeldChange(text=text, summary=summary) | Flagged(text=text, summary=summary)
        ):
            return f"{text}\n{summary}"
        case _:
            return body(item)


def spelled(duration: timedelta) -> str:
    """Spell a duration as a call gives one, in ISO 8601.

    >>> spelled(timedelta(minutes=10))
    'PT10M'
    """
    return TypeAdapter[timedelta](timedelta).dump_python(duration, mode="json")


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
            return f"answered at {clocked(at)}, {cited(answer)}"
        case Done(at=at):
            return f"done at {clocked(at)}"
        case Decided(at=at, approved=approved):
            return f"{'approved' if approved else 'declined'} at {clocked(at)}"
        case Superseded(at=at, by=by):
            return f"superseded at {clocked(at)} by {cited(by)}"
        case Withdrawn(at=at, why=why) if isinstance(item.reason, Flagged):
            return f"withdrawn at {clocked(at)} by lup: {why}"
        case Withdrawn(at=at, why=why):
            return f"withdrawn at {clocked(at)} by its sender: {why}"


def named(party: Party) -> str:
    """Name a party as a tag's attribute says it: `operator`, or a conversation as `who` names it.

    >>> named(Operator())
    'operator'
    """
    match party:
        case Operator():
            return "operator"
        case Conversation():
            return who(party)


type ItemKind = Literal[
    "turn's end",
    "note",
    "problem",
    "disagreement",
    "question as a message",
    "friction",
    "how it felt",
    "stop",
    "ended",
    "unresolved",
    "question",
    "answer",
    "approval",
    "held change",
    "flagged write",
    "review",
]
"""An item's kind as a tag's `kind` names it (`kind`), and as `inbox` narrows
to: a message by its own kind, a turn's last words told apart from a note,
else what the item is."""


def kind(item: Item) -> ItemKind:
    """Name an item's kind as a tag's `kind` says it: a message's own kind, else what the item is.

    >>> from datetime import UTC, datetime
    >>> item = Item(number=7, reason=Message(kind="problem", text="It hangs."),
    ...     sender=Operator(), recipient=Operator(), made=datetime(2026, 1, 1, tzinfo=UTC))
    >>> kind(item)
    'problem'
    """
    match item.reason:
        case Message(ending=True):
            return "turn's end"
        case Message(kind="question"):
            return "question as a message"
        case Message(kind=said):
            return said
        case Friction():
            return "friction"
        case HowItFelt():
            return "how it felt"
        case Stop():
            return "stop"
        case Ended():
            return "ended"
        case Unresolved():
            return "unresolved"
        case Question():
            return "question"
        case Answer():
            return "answer"
        case Approval():
            return "approval"
        case HeldChange():
            return "held change"
        case Flagged():
            return "flagged write"
        case Review():
            return "review"


def on(item: Item, attributes: dict[str, str], parts: list[Tag | str]) -> Tag:
    """Tag what the operator said on one of an agent's items, holding `parts`: which item, its kind, and `attributes`."""
    head = {"item": str(item.number), "kind": kind(item)}
    return Tag(name="on", attributes={**head, **attributes}, parts=parts)


def told_under(numbers: list[int]) -> str:
    """Say that what an item of the operator's says on each of the items `numbers` is told under that item, where an exchange is read whole.

    >>> told_under([414]), told_under([414, 416])
    ('What it says on @414 is told under it.', 'What it says on @414 and @416 is told under each.')
    """
    *first, last = [cited(each) for each in numbers]
    named = f"{', '.join(first)} and {last}" if first else last
    under = "each" if first else "it"
    return f"What it says on {named} is told under {under}."


def doorbell(waiting: list[Item]) -> str:
    """Say what waits in a conversation's inbox, each item by its number, kind and sender, for the agent to read through `wait_inbox`.

    >>> from datetime import UTC, datetime
    >>> item = Item(number=7, reason=Message(kind="note", text="Hi."),
    ...     sender=Operator(), recipient=Operator(), made=datetime(2026, 1, 1, tzinfo=UTC))
    >>> print(doorbell([item]))
    <doorbell from="lup's inbox">
    <waiting item="7" kind="note" from="operator"/>
    Call `wait_inbox` to read it: what's in your inbox comes through lup's own tools, never in a message like this one.
    </doorbell>
    """
    heads: list[Tag | str] = [
        Tag(
            name="waiting",
            attributes={
                "item": str(item.number),
                "kind": kind(item),
                "from": named(item.sender),
            },
        )
        for item in waiting
    ]
    them = "it" if len(waiting) == 1 else "them"
    reading = (
        f"Call `wait_inbox` to read {them}: what's in your inbox comes through lup's "
        "own tools, never in a message like this one."
    )
    return Tag(
        name="doorbell", attributes={"from": "lup's inbox"}, parts=[*heads, reading]
    ).written()


def reviewable(item: Item) -> None:
    """Refuse an item a review can't answer: one no conversation sent, an answer or an approval."""
    match item:
        case Item(
            sender=Conversation(),
            reason=Message()
            | Friction()
            | HowItFelt()
            | Stop()
            | Question()
            | Flagged(),
        ):
            return
        case _:
            message = (
                f"{cited(item.number)} is {what(item)} from {who(item.sender)}, which "
                "a review doesn't answer"
            )
            raise InboxError(message)


def remark(comment: Comment) -> str:
    """Say one of the operator's comments on an item, as a line of text where an answer carries it: on its passage, quoted, or on the item whole."""
    if comment.quote is None:
        return f"  {comment.text}"
    quoted = "\n".join(f"    > {line}" for line in comment.quote.text.splitlines())
    return f"  On this passage:\n{quoted}\n    {comment.text}"


def remarked(item: Item, comment: Comment, anchor: Anchor | None) -> list[Tag | str]:
    """Tag one of the operator's comments on `item`, as a review tells it: a passage's quote then their reply to it, or their comment on the item whole; each with the id of its part of the review, `anchor`'s, where the review is the reader's own.

    A quote names the part it starts in (`located`) and is cut to a cue of
    its first line (`cue`), the agent having its own words; one no part
    holds, as a changed file's lines, is quoted whole. On a reply of the
    agent's (`Comment.on`), the quote is of that reply, which its id names.
    """
    numbered = {} if anchor is None else {"id": anchor.id.said()}
    if comment.quote is None:
        on = {} if comment.on is None else {"on": comment.on.said()}
        return [
            Tag(name="comment", attributes={**numbered, **on}, parts=[comment.text])
        ]
    text = body(item)
    found = (
        comment.on.said()
        if comment.on is not None
        else next(
            (
                each.id.said()
                for each in [located(parts_of(item, text), text, comment.quote)]
                if each is not None
            ),
            None,
        )
    )
    quoted = (
        Tag(name="quote", parts=[comment.quote.text])
        if found is None
        else Tag(
            name="quote", attributes={"part": found}, parts=[cue(comment.quote.text)]
        )
    )
    return [quoted, Tag(name="reply", attributes=numbered, parts=[comment.text])]


def changed_since(code: Quoted) -> str | None:
    """Say which of the lines `code` quotes have changed since the comment was written on them, as the file stands in its worktree: their numbers in the version quoted, `all` where the file is gone or isn't text; none where each is still there.

    A quoted line is still there where the file holds it in the same order as
    the others quoted, wherever lines added or taken away around it moved it.

    >>> from pathlib import Path
    >>> quoted = Quoted(worktree=Path("/w"), path=Path("a.py"), version="v", first=3, lines=["x = 1", "y = 2"])
    >>> changed_since(quoted)
    'all'
    """
    try:
        text = (code.worktree / code.path).read_text()
    except OSError, UnicodeDecodeError:
        return "all"
    matcher = difflib.SequenceMatcher(
        None, text.splitlines(), code.lines, autojunk=False
    )
    # Where each quoted line still there is in the file as it stands, by its place in the quote.
    found = {
        at: block.a + (at - block.b)
        for block in matcher.get_matching_blocks()
        for at in range(block.b, block.b + block.size)
    }
    gone = [code.first + at for at in range(len(code.lines)) if at not in found]
    return " ".join(str(number) for number in gone) if gone else None


def remarking(remark: Remark, attributes: dict[str, str]) -> Tag:
    """Tag one of the operator's remarks in an agent's drawer, as a review tells it: its passage's quote, saying on code which quoted lines have changed since (`changed_since`), then their reply; `attributes` say whose it is where it's told as context, or its id where it's the reader's own."""
    since = None if remark.code is None else changed_since(remark.code)
    changed = {} if since is None else {"changed": since}
    return Tag(
        name="remark",
        attributes=attributes,
        parts=[
            Tag(name="quote", attributes=changed, parts=[remark.quote.text]),
            Tag(name="reply", parts=[remark.text]),
        ],
    )


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
    The operator declined @7, the approval your push asked ("Approve the host zone at abc?"), and commented:
    Split the reader out first.
    """
    answer = (
        "approved"
        if isinstance(item.state, Decided) and item.state.approved
        else "declined"
    )
    return (
        f"The operator {answer} {cited(item.number)}, the approval your push asked "
        f'("{opening(item)}"), and commented:\n{comment}'
    )


def unanswered(item: Item, comments: str) -> str:
    """Say the operator's comments on an approval a push asked, which they haven't answered, for the session that pushed.

    >>> from datetime import UTC, datetime
    >>> from pathlib import Path
    >>> asked = Approval(text="Approve the host zone at abc?", summary="",
    ...     repository=Path("/r.git"), fingerprint="f")
    >>> item = Item(number=7, reason=asked, sender=Operator(), recipient=Operator(),
    ...     made=datetime(2026, 1, 1, tzinfo=UTC))
    >>> print(unanswered(item, "  Split the reader out first."))
    The operator commented on @7, the approval your push asked ("Approve the host zone at abc?"), and hasn't answered it:
      Split the reader out first.
    """
    return (
        f"The operator commented on {cited(item.number)}, the approval your push "
        f'asked ("{opening(item)}"), and hasn\'t answered it:\n{comments}'
    )


def landing_held(item: Item) -> AtLanding:
    """Return what hold at landing `item` holds, or say it isn't one."""
    match item.reason:
        case HeldChange(landing=AtLanding() as landing):
            return landing
        case _:
            message = f"{cited(item.number)} is {what(item)}, not a hold at landing"
            raise InboxError(message)


def answered_hold(item: Item, did: str, comment: str) -> str:
    """Say the operator's answer to hold at landing `item`, for the conversation landing: what they `did`, then their comment, where they gave one.

    >>> from datetime import UTC, datetime
    >>> from pathlib import Path
    >>> held = HeldChange(text="Land src/a.py on dev?", summary="", worktree=Path("/w"),
    ...     landing=AtLanding(onto="refs/heads/dev", tip="1a2b3c4d5e6f7a8b", path=Path("src/a.py"),
    ...     branches=["feat"], flags=[3]))
    >>> item = Item(number=7, reason=held, sender=Operator(), recipient=Operator(),
    ...     made=datetime(2026, 1, 1, tzinfo=UTC))
    >>> print(answered_hold(item, "commented on it without approving it", "Name it Chamber."))
    The operator commented on it without approving it: @7, the hold on `src/a.py` at the landing of 1a2b3c4d5e6f7a8b on `dev`. Their comment:
    Name it Chamber.
    """
    landing = landing_held(item)
    onto = landing.onto.removeprefix("refs/heads/")
    said = (
        f"The operator {did}: {cited(item.number)}, the hold on `{landing.path}` at "
        f"the landing of {landing.tip} on `{onto}`."
    )
    return f"{said} Their comment:\n{comment}" if comment.strip() else said


def editable(item: Item, party: Conversation) -> str:
    """Return the text of `item` its sender `party` may edit (`Delivery.edited`): its own words to the operator, a message's, a question's, a friction's, how it felt's or a stop's; refuse any other, saying why."""
    match item:
        case Item(sender=sender) if sender != party:
            message = f"{cited(item.number)} is {what(item)} from {who(sender)}: only its sender edits it"
            raise InboxError(message)
        case Item(reason=Message(to=Conversation() as to)):
            message = (
                f"{cited(item.number)} is the operator's copy of your message to "
                f"{who(to)}, which read it as it was: `send` a correction"
            )
            raise InboxError(message)
        case Item(state=Withdrawn()):
            message = f"{cited(item.number)} is withdrawn: send anew what still holds"
            raise InboxError(message)
        case Item(reason=Question(), state=Answered()):
            message = f"{cited(item.number)} is a question the operator answered: `send` what changed"
            raise InboxError(message)
        case Item(
            recipient=Operator(),
            reason=Message(text=text)
            | Question(text=text)
            | Friction(text=text)
            | HowItFelt(text=text)
            | Stop(text=text),
        ):
            return text
        case _:
            message = f"{cited(item.number)} is {what(item)}, which isn't your words to the operator: it isn't edited"
            raise InboxError(message)


def rewritten(reason: Reason, text: str) -> Reason:
    """Return `reason` with `text` for its words, where it's one an edit takes (`editable`); as it is for any other."""
    match reason:
        case Message() | Question() | Friction() | HowItFelt():
            return reason.model_copy(update={"text": text})
        case Stop():
            return reason.model_copy(update={"why": text})
        case _:
            return reason


class Dispatched(Model):
    """What sending the operator's draft did: the reviews it was sent as, the items it took off the list read, what it approved and declined, and what it did with comments on approvals and holds at landing it left unapproved."""

    reviews: list[Item] = []
    """One to each conversation with a comment on its messages or questions, a question among them, or a message to it."""
    read: list[int] = []
    """The messages it took off the list marked read with no comment of their
    own, which tells their senders nothing, by number."""
    approved: list[Item] = []
    """The approvals and held changes it approved: each marked done, with the
    comments under it, each marked read alone, and each held change commented
    on, with the comments, but for a hold at landing."""
    declined: list[Item] = []
    """The approvals and held changes it declined: each marked declined, with
    the comments under it."""
    noted: list[Item] = []
    """The notes it left with each session whose push asked an approval the operator commented on, which stays unanswered, and with each conversation whose landing a hold commented on held back."""
    kept: list[int] = []
    """The approvals commented on whose push no known session made: their comments stay drafted."""


def settled(
    item: Item, review: Item | None, at: datetime, *, commented: bool
) -> Answered | Done | Decided:
    """Return where an item a review covers stands once it's sent: a question answered by `review`, the review its asker gets; a flagged write marked read with nothing to add approved, "looks good"; anything else done, a flagged write `commented` on among it."""
    match item.reason:
        case Question() if review is not None:
            return Answered(at=at, answer=review.number)
        case Flagged() if not commented:
            return Decided(at=at, approved=True)
        case _:
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
    return Tag(
        name="announced",
        attributes={
            "item": str(item.number),
            "kind": kind(item),
            "from": named(item.sender),
            "bytes": f"{size:,}",
        },
        parts=["Too long to tell here: call `wait_inbox` to read it whole."],
    ).written()


type Waking = Literal["operator", "agents", "tasks"]
"""Whose news ends a held call: the operator's, an answer, a review or a message
through lup, or their words typed in the terminal; another agent's, a message
from the conversation's parent or one of its subagents, a subagent's end or
what it said of its work, another session's message; or a task the
conversation started in the background, a command ending or a Monitor's
event."""


def whose(item: Item) -> Waking:
    """Say whose news `item` is, for what ends a held call: another agent's, where a conversation other than the one it's for sent it; else the operator's, lup's own word to the conversation among it.

    >>> from datetime import UTC, datetime
    >>> from pathlib import Path
    >>> me = Conversation(repository=Path("/w/.git"), runtime="r1", session="s1")
    >>> worker = me.model_copy(update={"agent": "a1"})
    >>> made = datetime(2026, 1, 1, tzinfo=UTC)
    >>> note = Message(kind="note", text="Found it.")
    >>> whose(Item(number=7, reason=note, sender=worker, recipient=me, made=made))
    'agents'
    >>> whose(Item(number=8, reason=note, sender=Operator(), recipient=me, made=made))
    'operator'
    """
    match item.sender:
        case Conversation() as sender if (
            sender != item.recipient and sender != item.addressed
        ):
            return "agents"
        case _:
            return "operator"


def waking(kind: Queuing) -> Waking:
    """Say whose news something a runtime holds for a conversation is, for what ends a held call."""
    match kind:
        case "typed":
            return "operator"
        case "task":
            return "tasks"
        case "subagent" | "message":
            return "agents"


def queue(held: list[Queued]) -> str:
    """Say what a conversation's runtime holds for it, which reaches the agent from the runtime as its held call returns: each by what it is, in the runtime's words where it says.

    >>> gate = 'Background command "gate" completed (exit code 0)'
    >>> print(queue([Queued(id="1", kind="typed"), Queued(id="2", kind="task", summary=gate)]))
    <queued from="your runtime">
    <waiting kind="typed" from="operator">Their words, typed in your terminal.</waiting>
    <waiting kind="task">Background command "gate" completed (exit code 0)</waiting>
    Each reaches you from your runtime as this call returns.
    </queued>
    """

    def said(each: Queued) -> Tag:
        match each.kind:
            case "typed":
                attributes = {"kind": "typed", "from": "operator"}
                line = "Their words, typed in your terminal."
            case "task":
                attributes = {"kind": "task"}
                line = each.summary or "A task you started in the background."
            case "subagent":
                attributes = {"kind": "subagent"}
                line = each.summary or "A subagent of yours ended, or reported."
            case "message":
                attributes = {"kind": "message"}
                line = "Another session's message" + (
                    "." if each.summary is None else f", {each.summary}."
                )
        return Tag(name="waiting", attributes=attributes, parts=[line])

    reaches = "It reaches" if len(held) == 1 else "Each reaches"
    return Tag(
        name="queued",
        attributes={"from": "your runtime"},
        parts=[
            *(said(each) for each in held),
            f"{reaches} you from your runtime as this call returns.",
        ],
    ).written()


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
    queued: list[str] = []
    """What its runtime holds for it that a held call told, by each one's id,
    of those it still holds, so none is told twice."""
    pushed: Pushed | None = None
    """What was last pushed to its session, until a turn's start carries its
    token, or its wait runs out."""


class Pushed(Model):
    """What was pushed to an idle session through lup's tool server: the token its turn's prompt carries, and the items it told."""

    token: str
    numbers: list[int]


class Delivery(MutableModel, Post, arbitrary_types_allowed=True):
    """Each conversation's inbox, told once; and the operator's, noticed on their desktop."""

    inbox: Inbox
    waker: Waker
    """Spells how an idle session is woken, where its runtime has a way."""
    pushes: Pushes
    """Each launch's open connections to lup's tool server, which a push to its
    session goes through."""
    layout: HostLayout
    """Where each launch's sockets are, its session's messaging socket among them."""
    notices: Notices
    clock: Clock
    say: Callable[[str], None]
    patience: timedelta = timedelta(seconds=30)
    """How long a push waits for the turn's start carrying its token, after
    which what it told is put back and the session's messaging socket rings."""
    queues: dict[str, Queues] = {}
    """What each runtime holds for a conversation while its call runs, by the
    runtime's name, which ends a held call (`held`); a runtime without, a gap
    its adapter declares, ends one on its inbox alone."""
    glance: timedelta = timedelta(seconds=1)
    """How often a held call looks at what its conversation's runtime holds
    for it, and at its time limit: a look at a record that hasn't grown is a
    file's size, and one that has reads only what it gained."""
    unpushed: list[str] = []
    """The launches whose session took no push in time: said once, and woken
    through the messaging socket from then on."""
    waits: list[asyncio.Task[None]] = []
    """Each push's wait to be taken, kept until it's done."""
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

    def tellable(self, party: Conversation) -> list[Item]:
        """Return what waits for `party` that a hook or a held call may tell: all of it but what's pushed to its session and not yet taken."""
        pushed = self.presence(party).pushed
        pending = [] if pushed is None else pushed.numbers
        return [
            item for item in self.inbox.waiting(party) if item.number not in pending
        ]

    @override
    async def telling(
        self,
        launch: Register,
        conversation: Caller,
        parent: Caller | None,
        heard: Heard,
        room: int,
    ) -> Posted:
        """Note where the conversation is heard, and the conversation that spawned it, `parent`; and tell it what waits.

        At its turn's end, what waits holds the end once (`holding`), but for
        quiet items (`Item.quiet`), and a call it holds learns its turn ended;
        an end let through leaves its main conversation idle, and a subagent's
        ended (`ended`), its last words put before the operator first where
        they answer the operator's (`subagent_answered`). A subagent stopped, and a turn that failed on an error
        from the model's API, the session's or a subagent's, are held for
        nothing, since nothing would read it. A turn's start whose prompt
        carries the token of what was pushed to it takes the push. A worktree
        asked for is told nothing: its answer is where the worktree is, and
        carries nothing else.
        """
        party = self.party(launch, conversation)
        self.heard_in(
            party,
            launch,
            None if parent is None else self.party(launch, parent),
            conversation.name,
        )
        presence = self.presence(party)
        presence.woken = False
        match heard.event:
            case TurnEnded() | ConversationEnded():
                ended = isinstance(heard.event, ConversationEnded)
                for each in presence.held:
                    each.ended = True
                if ended:
                    await self.subagent_answered(party, launch, heard)
                fresh = [
                    item
                    for item in self.tellable(party)
                    if not announced(item) and not item.quiet
                ]
                unread = heard.stopped or heard.failed is not None
                if not unread and holding(fresh, [], after_block=heard.after_block):
                    posted = self.told(party, room, heard.fits, "turn's end")
                    if posted.items:
                        return posted
                presence.turning = False
                if ended and party.agent is not None:
                    await self.ended(party, launch, conversation, heard)
                return Posted()
            case SessionStarted():
                presence.turning = False
                return self.told(party, room, heard.fits, "start")
            case TurnStarted():
                presence.turning = True
                taken = presence.pushed
                if taken is not None and taken.token in (heard.prompt or ""):
                    self.taken(party, taken)
                return self.told(party, room, heard.fits, "turn's start")
            case CallStarted() if heard.served:
                presence.turning = True
                return Posted()
            case CallStarted() | CallFinished():
                presence.turning = True
                return self.told(party, room, heard.fits, "call")
            case WorktreeAsked():
                return Posted()

    @override
    async def concluded(
        self, launch: Register, conversation: Caller, heard: Heard
    ) -> None:
        """Put a session's turn's end in the operator's inbox, as a note from it that lup made (`Message.ending`): its last message, so they read what it ended its turn saying there without it sending it again, with the operator's items it answers (`answering`); or where its turn ended on an error from the model's API, that, in lup's words, with the error's kind and its runtime's text for it. One end makes one note at most, and one saying neither makes none.

        An end held to tell what waits makes its note too, as its message
        stands: the turn goes on to another end, with words of its own. A failed
        turn has no words of its own: the conversation shows the runtime's text
        for the error among its steps, and the note says what it is. A reply to
        either reaches the session, which a failure leaves idle, so it's woken.
        """
        match heard:
            case Heard(failed=Failure(kind=kind, said=said)):
                opening = f"Its turn ended on an error from the model's API ({kind})"
                shown = said is not None and bool(said.strip())
                text = f"{opening}:\n{said}" if shown else f"{opening}."
            case Heard(said=str() as said) if said.strip():
                text = said
            case _:
                return
        await self.ended_saying(self.party(launch, conversation), text, launch.worktree)

    async def ended_saying(
        self,
        party: Conversation,
        text: str,
        worktree: Path | None,
        *,
        telling: bool = True,
    ) -> Item:
        """Put `party`'s last words of a turn, `text`, before the operator as its turn's end, with the operator's items it answers (`answering`) and its citations of their words read (`cited`); where some name no passage and `telling` says it can still be told, tell `party` so, which holds its turn's end once (`docs/inbox.md`, *Citing the operator's words*)."""
        answers = self.answering(party)
        note = await self.posted(
            Message(kind="note", text=text, ending=True, answers=answers),
            party,
            Operator(),
            worktree,
        )
        missed = failing(note.citations)
        if missed and telling:
            await self.posted(
                Unresolved(of=note.number, citations=missed), party, party, worktree
            )
        return note

    async def subagent_answered(
        self, party: Conversation, launch: Register, heard: Heard
    ) -> None:
        """Put a subagent's last words before the operator as its turn's end, where the operator's words were told to it since it last did (`answering`): what answers them, which its parent alone would read otherwise. None for a subagent stopped or failing, or one leaving no words.

        Its citations naming no passage are told to it only where its end can
        still be held for them: one let through after a hold ends, and what
        waits for it would go to its session, which can't edit its words.
        """
        said = heard.said
        if party.agent is None or heard.stopped or heard.failed is not None:
            return
        if said is None or not said.strip() or not self.answering(party):
            return
        await self.ended_saying(
            party, said, launch.worktree, telling=not heard.after_block
        )

    def answering(self, party: Conversation) -> list[int]:
        """Return the operator's items told to `party` since its last turn's end that lup put before the operator, and not among those that end answers: what its next turn's end answers, oldest first."""
        ordered = [self.inbox.items[number] for number in sorted(self.inbox.items)]
        last = next(
            (
                each
                for each in reversed(ordered)
                if each.sender == party
                and isinstance(each.reason, Message)
                and each.reason.ending
            ),
            None,
        )
        since = None if last is None else last.made
        before = (
            []
            if last is None or not isinstance(last.reason, Message)
            else last.reason.answers
        )
        return [
            each.number
            for each in ordered
            if addressed_to(each, party)
            and isinstance(each.state, Told)
            and (since is None or each.state.at >= since)
            and each.number not in before
        ]

    def said_to(self, party: Conversation) -> list[Anchor]:
        """Return every part of the operator's words addressed to `party`, oldest first: what its citations of their words are read against (`spoken`)."""
        ordered = [self.inbox.items[number] for number in sorted(self.inbox.items)]
        return [
            anchor
            for item in ordered
            if addressed_to(item, party)
            for anchor in spoken(item)
        ]

    def cited(self, item: Item) -> Item:
        """Read the citations of the operator's words in `item`, where it's in a conversation's own words to the operator, and keep them on it (`inbox/citations.py`); as it is where it's none, or cites nothing."""
        match item:
            case Item(
                sender=Conversation() as sender,
                recipient=Operator(),
                reason=Message() | Friction() | HowItFelt() | Stop() | Question(),
            ):
                citations = resolved(body(item), self.said_to(sender))
                if citations or item.citations:
                    return self.inbox.kept(
                        item.model_copy(update={"citations": citations})
                    )
                return item
            case _:
                return item

    @override
    def returned(self, posted: Posted) -> None:
        for number in posted.numbers:
            item = self.inbox.item(number)
            self.inbox.kept(item.model_copy(update={"state": Waiting()}))

    @staticmethod
    def party(launch: Register, conversation: Caller) -> Conversation:
        """Return the inbox's party for `conversation`, one of `launch`'s."""
        return Conversation(
            repository=launch.repository,
            runtime=launch.runtime,
            session=conversation.session,
            agent=conversation.agent,
        )

    def heard_in(
        self,
        party: Conversation,
        launch: Register,
        parent: Conversation | None,
        name: str | None = None,
    ) -> None:
        """Note that `party` is heard in `launch`: where it runs, that it goes on, the conversation that spawned it, `parent`, and a subagent's own `name`, which `inbox` reads it by once its launch has ended."""
        place = self.inbox.whereabouts.get(party.key())
        if place is not None and place.launch == launch.launch and place.ended is None:
            if place.parent != parent or place.name != name:
                self.inbox.placed(
                    place.model_copy(update={"parent": parent, "name": name})
                )
            return
        self.inbox.placed(
            Whereabouts(
                conversation=party,
                launch=launch.launch,
                worktree=launch.worktree,
                since=self.clock.now(),
                parent=parent,
                name=name,
            )
        )

    def parent(self, party: Conversation) -> Conversation | None:
        """Return the conversation that spawned `party`, where it's a subagent a conversation spawned; none else."""
        place = self.inbox.whereabouts.get(party.key())
        return None if place is None else place.parent

    def subagents(self, party: Conversation) -> list[Whereabouts]:
        """Return where each subagent `party` spawned was last heard, those heard in the launch `party` was last heard in alone, in the order each was first heard there: those that ended among them."""
        place = self.inbox.whereabouts.get(party.key())
        if place is None:
            return []
        spawned = [
            each
            for each in self.inbox.whereabouts.values()
            if each.parent == party and each.launch == place.launch
        ]
        return sorted(spawned, key=lambda each: each.since)

    async def ended(
        self, party: Conversation, launch: Register, conversation: Caller, heard: Heard
    ) -> None:
        """Note that a subagent's conversation ended, pass what waits for it to its session's main conversation, and tell the conversation that spawned it.

        Its parent is told quietly (`Item.quiet`) which subagent it was, whether
        it ended its turn, was stopped, or failed on an error from the model's
        API, and its last message where its runtime doesn't hand that on
        (`Ended`): at the parent's next call, or by
        `wait_inbox`, which returns on it, since the runtime wakes an idle
        parent for its subagent's end already.
        """
        place = self.inbox.whereabouts.get(party.key())
        if place is not None:
            self.inbox.placed(place.model_copy(update={"ended": self.clock.now()}))
        main = party.main()
        for item in self.inbox.waiting(party):
            self.inbox.kept(
                item.model_copy(update={"recipient": main, "addressed": party})
            )
        self.arrive(main)
        if place is None or place.parent is None:
            return
        news = Ended(
            name=conversation.own(launch.name or launch.launch),
            stopped=heard.stopped,
            failed=None if heard.failed is None else heard.failed.kind,
            handed=conversation.handed,
            said=heard.said,
        )
        await self.posted(news, party, place.parent, launch.worktree, quiet=True)

    def said(self, item: Item) -> str:
        """Say `item`, whole, to the conversation it's told to: its tag, written."""
        return self.tagged(item).written()

    def words(self, item: Item) -> str:
        """Return what `item` tells the conversation it's told to, inside its tag: a message's text, a reply on the item it replies to, an answer beside its question, a review said to its recipient."""
        return inside(self.tagged(item).parts)

    def called(self, party: Party) -> str | None:
        """Return the name lup calls `party` by where it's a conversation: a session's own, its launch's as lup last kept it (`SessionNames`); a subagent's own, as its whereabouts last heard it; none for the operator, and where lup knows none."""
        match party:
            case Conversation(agent=None):
                return Names(path=self.layout.names).last(party.session)
            case Conversation():
                place = self.inbox.whereabouts.get(party.key())
                return None if place is None else place.name
            case Operator():
                return None

    def tagged(
        self, item: Item, *, under: list[int] | None = None, context: bool = True
    ) -> Tag:
        """Return `item` as the tag it's told in: named for what it is, saying its number, whom it's from and, for a conversation, the name lup calls it by, whom it was for where it was passed on from a conversation that had ended, and what it answers.

        Where it's read beside the items it's on, as `inbox` reads an exchange
        whole, what it says on each of `under` is told under that item instead,
        and a line says so; and a review's `context` is left out where it's
        asked to be.
        """
        placed = [] if under is None else under
        passed = (
            {}
            if item.addressed is None
            else {"for": f"{who(item.addressed)}, whose conversation had ended"}
        )
        sender = self.called(item.sender)
        name = {} if sender is None else {"name": sender}
        head = {
            "item": str(item.number),
            "from": named(item.sender),
            **name,
            **passed,
        }
        parts = anchors(item)
        match item.reason:
            case Message(kind=said, of=int() as of) if of in placed:
                return Tag(
                    name="message",
                    attributes={**head, "kind": said},
                    parts=[told_under([of])],
                )
            case Answer(question=question) if question in placed:
                return Tag(
                    name="answer",
                    attributes={**head, "question": str(question)},
                    parts=[told_under([question])],
                )
            case Message(kind=said, text=text, of=int() as of):
                original = self.inbox.item(of)
                [anchor] = parts
                replied = on(
                    original,
                    {},
                    [
                        Tag(name="opening", parts=[opening(original)]),
                        Tag(
                            name="comment",
                            attributes={"id": anchor.id.said()},
                            parts=[text],
                        ),
                    ],
                )
                return Tag(
                    name="message", attributes={**head, "kind": said}, parts=[replied]
                )
            case Message(kind=said, text=text, passages=passages):
                replies = [
                    part
                    for each, anchor in zip(passages, parts, strict=True)
                    for part in [
                        Tag(name="quote", parts=[each.quote]),
                        Tag(
                            name="reply",
                            attributes={"id": anchor.id.said()},
                            parts=[each.text],
                        ),
                    ]
                ]
                whole = [text] if text or not passages else []
                return Tag(
                    name="message",
                    attributes={**head, "kind": said},
                    parts=[*replies, *whole],
                )
            case Answer(question=question) as answer:
                return Tag(
                    name="answer",
                    attributes={**head, "question": str(question)},
                    parts=self.answered(answer, parts),
                )
            case Review(covers=covers) as review:
                covering = (
                    {"covers": " ".join(str(each) for each in covers)} if covers else {}
                )
                return Tag(
                    name="review",
                    attributes={**head, **covering},
                    parts=self.reviewing(
                        review,
                        item.addressed or item.recipient,
                        spoken(item),
                        under=placed,
                        context=context,
                    ),
                )
            case Ended(name=name, heading=heading, passed=passed):
                said = [] if passed is None else [Tag(name="said", parts=[passed])]
                return Tag(
                    name="ended",
                    attributes={**head, "name": name},
                    parts=[heading, *said],
                )
            case Unresolved(of=of, citations=citations):
                return Tag(
                    name="unresolved",
                    attributes={"item": str(item.number), "from": "lup", "of": str(of)},
                    parts=unresolved(citations, of),
                )
            case (
                Friction()
                | HowItFelt()
                | Stop()
                | Question()
                | Approval()
                | HeldChange()
                | Flagged()
            ):
                return Tag(
                    name="item",
                    attributes={**head, "kind": kind(item)},
                    parts=[body(item)],
                )

    def reviewing(
        self,
        review: Review,
        recipient: Party,
        parts: list[Anchor],
        *,
        under: list[int] | None = None,
        context: bool = True,
    ) -> list[Tag | str]:
        """Tag a review for the conversation it's for: the operator's message to it, their remarks in its drawers (`remarking`) and its own items they commented on first, each with the id of its part among `parts`, the review's (`spoken`; `remarked`); its items read with nothing to add in one line; then, in its context, the other agents' items they commented on, each named and never repeated, and their messages and remarks to other agents, each saying whom it was for.

        Its comments on each of its own items among `under` are told under that
        item instead, where an exchange is read whole, a line saying so; its
        context is left out where `context` is false.
        """
        under_items = [] if under is None else under
        items = [self.inbox.item(each) for each in review.covers]
        commented = [each.item for each in review.comments]
        addressed = list(dict.fromkeys(each.to for each in review.letters))
        on_items = parts[: len(review.comments)]
        rest = [each.id.said() for each in parts[len(review.comments) :]]

        def numbered(at: int) -> dict[str, str]:
            """Return the id of the review's `at`th message or remark, its messages first, as an attribute; none where `parts` gives it none."""
            return {"id": rest[at]} if at < len(rest) else {}

        def written(to: Conversation) -> str:
            return "\n\n".join(each.text for each in review.letters if each.to == to)

        def mine(to: Conversation) -> list[Tag]:
            return [
                Tag(name="message", attributes=numbered(at), parts=[each.text])
                for at, each in enumerate(review.letters)
                if each.to == to
            ]

        def placed(to: Conversation) -> dict[str, str]:
            place = self.inbox.whereabouts.get(to.key())
            return {} if place is None else {"worktree": str(place.worktree)}

        def elsewhere(to: Conversation) -> Tag:
            return Tag(
                name="message",
                attributes={"to": who(to), **placed(to)},
                parts=[written(to)],
            )

        def remarks_to(to: Conversation) -> list[Tag]:
            theirs = to != recipient
            after = len(review.letters)
            return [
                remarking(
                    each,
                    {"to": who(to), **placed(to)} if theirs else numbered(after + at),
                )
                for at, each in enumerate(review.remarks)
                if each.to == to
            ]

        remarked_to = list(dict.fromkeys(each.to for each in review.remarks))

        def remarks(item: Item, *, own: bool) -> list[Tag | str]:
            return [
                part
                for each, anchor in zip(review.comments, on_items, strict=True)
                if each.item == item.number
                for part in remarked(item, each, anchor if own else None)
            ]

        def yours(item: Item) -> Tag:
            quoted = any(
                each.quote is not None
                for each in review.comments
                if each.item == item.number
            )
            first = [] if quoted else [Tag(name="opening", parts=[opening(item)])]
            return on(item, {}, [*first, *remarks(item, own=True)])

        def theirs(item: Item) -> Tag:
            where = {} if item.worktree is None else {"worktree": str(item.worktree)}
            return on(
                item,
                {"from": named(item.sender), **where},
                remarks(item, own=False),
            )

        read = [
            str(item.number)
            for item in items
            if item.sender == recipient and item.number not in commented
        ]
        own: list[Tag | str] = [
            *(tag for to in addressed if to == recipient for tag in mine(to)),
            *(tag for to in remarked_to if to == recipient for tag in remarks_to(to)),
            *(
                yours(item)
                for item in items
                if item.sender == recipient
                and item.number in commented
                and item.number not in under_items
            ),
            *([Tag(name="read", attributes={"items": " ".join(read)})] if read else []),
        ]
        told = [
            item.number
            for item in items
            if item.sender == recipient
            and item.number in commented
            and item.number in under_items
        ]
        moved = [told_under(told)] if told else []
        others: list[Tag | str] = [
            *(
                theirs(item)
                for item in items
                if item.sender != recipient and item.number in commented
            ),
            *(elsewhere(to) for to in addressed if to != recipient),
            *(tag for to in remarked_to if to != recipient for tag in remarks_to(to)),
        ]
        heading = (
            "What the operator said in the same reply on other agents' items and to "
            "other agents: not yours to act on, unless it says so."
        )
        around = (
            [Tag(name="context", parts=[heading, *others])]
            if others and context
            else []
        )
        return [*own, *moved, *around]

    async def reopened(self, party: Conversation, number: int) -> None:
        """Put item `number` of the agent's back before the operator, where it had left their list: waiting again, with a notice where its kind raises one, saying `party` edited it."""
        item = self.inbox.item(number)
        if item.recipient != Operator() or isinstance(item.state, Waiting):
            return
        reopened = self.inbox.kept(item.model_copy(update={"state": Waiting()}))
        if not reopened.rank.notifies:
            return
        summary = f"lup: {who(party)} edited {cited(number)}, {what(item)}"
        await self.notices.notify(
            summary, f"{opening(item)}\nlup-dev inbox show {number}"
        )

    def drafted(self, draft: Draft) -> Draft:
        """Keep the operator's draft reply, and return it; refused where a message in it is for a conversation lup's inbox has never heard of (`heard`)."""
        self.heard(draft)
        return self.inbox.drafted(draft)

    def heard(self, draft: Draft) -> None:
        """Refuse a draft with a message, or a remark, for a conversation lup's inbox has never heard of, which no reply could reach: it's known once one of its hooks is heard."""
        for to in [
            *(each.to for each in draft.letters),
            *(each.to for each in draft.remarks),
        ]:
            if to.key() not in self.inbox.whereabouts:
                message = (
                    f"the draft writes to {who(to)} of {to.repository}, "
                    "which lup's inbox has never heard of: write to an agent the "
                    "dashboard shows running"
                )
                raise InboxError(message)

    async def reviewed(self) -> Dispatched:
        """Send the operator's draft as one reply: to each conversation with a comment on its messages or questions, a question among them, or a message to it, the whole of it; its items answered or done; each approval and held change it covers answered by its own rule; and the draft left with what's parked.

        Each conversation is told the operator's message to it and its own
        items first, with the comments on them or read with nothing to add,
        then what was said on the others' items and to other agents for
        context (`reviewing`): the operator answers related items together,
        across agents and repositories, and sends what's drafted on moving to
        something unrelated. A question is answered by the reply its asker
        gets, which lets a held `ask` go. A message only marked read tells its
        sender nothing, nor wakes it: it's taken off the list, and told as read
        only to a conversation the reply reaches anyway.

        An approval or a held change marked done is approved, the comments
        under it going with the yes, and one marked declined is declined, with
        them. Unmarked, one only read is approved; a held change commented on
        is approved with the comments, which its agent reads with the answer:
        "yes, but…" rather than a refusal, since a comment never declines; but
        a hold at landing commented on isn't approved, since a comment usually
        asks for a change: it's done, the comments going as a note to the
        conversation landing, whose landing goes no further (`held_back`). An
        approval commented on stays unanswered, the comments going as a note to
        the session whose push asked it, whose next push supersedes it; where
        no known session pushed, they stay drafted (`Dispatched`). The draft's
        other marks stay drafted, for the page to apply (`Draft.kept`). Refused
        where the draft covers no item and writes to no agent, declines what
        isn't an approval or a held change, covers a message or question no
        conversation sent, or writes to a conversation lup's inbox has never
        heard of.
        """
        draft = self.inbox.draft()
        self.heard(draft)
        covered = [self.inbox.item(each) for each in draft.covered()]
        undeclinable = [
            item
            for item in covered
            if item.number in draft.declined
            and not isinstance(item.reason, Approval | HeldChange)
        ]
        if undeclinable:
            named = ", ".join(
                f"{cited(each.number)}, {what(each)}" for each in undeclinable
            )
            message = (
                f"the draft declines {named}: only an approval or a held change is "
                "declined, anything else marked done or commented on"
            )
            raise InboxError(message)
        if not covered and not draft.written() and not draft.remarked():
            message = (
                "the draft answers no item and writes to no agent: comment on an "
                "item, take one off the list, or write to an agent under its banner"
            )
            raise InboxError(message)
        asked = [
            item for item in covered if isinstance(item.reason, Approval | HeldChange)
        ]
        messages = [item for item in covered if item not in asked]
        for item in messages:
            reviewable(item)
        commented = [each.item for each in draft.comments if each.text.strip()]
        dispatched = Dispatched(
            reviews=self.reviews(draft, messages),
            read=[
                item.number
                for item in messages
                if item.number not in commented
                and not isinstance(item.reason, Question)
            ],
        )
        for item in asked:
            dispatched = await self.answered_in(draft, item, dispatched)
        left = draft.kept()
        staying = [each for each in draft.comments if each.item in dispatched.kept]
        self.inbox.drafted(
            left.model_copy(update={"comments": [*left.comments, *staying]})
        )
        for each in dispatched.reviews:
            await self.delivered(each)
        return dispatched

    def reviews(self, draft: Draft, covered: list[Item]) -> list[Item]:
        """Make the reviews `draft` is sent as for the messages and questions it covers, `covered`, its messages to agents and its remarks in their drawers, one to each conversation it reaches, and settle each item; delivering them is the caller's."""
        letters = draft.written()
        remarks = draft.remarked()
        if not covered and not letters and not remarks:
            return []
        at = self.clock.now()
        numbers = [item.number for item in covered]
        review = Review(
            covers=numbers,
            comments=[each for each in draft.comments if each.item in numbers],
            letters=letters,
            remarks=remarks,
        )
        commented = [each.item for each in draft.comments]
        senders = [
            item.sender
            for item in covered
            if item.number in commented or isinstance(item.reason, Question)
        ]
        recipients = list(
            dict.fromkeys(
                [
                    *senders,
                    *(each.to for each in letters),
                    *(each.to for each in remarks),
                ]
            )
        )
        sent = [
            self.inbox.made(review, Operator(), recipient, None, at)
            for recipient in recipients
        ]
        for item in covered:
            answer = next(
                (
                    each
                    for each in sent
                    if (each.addressed or each.recipient) == item.sender
                ),
                None,
            )
            settling = settled(item, answer, at, commented=item.number in commented)
            self.inbox.kept(item.model_copy(update={"state": settling}))
        return sent

    async def answered_in(
        self, draft: Draft, item: Item, dispatched: Dispatched
    ) -> Dispatched:
        """Answer the approval or held change `item` as `draft` has it, and return what the send did with it added (`reviewed`)."""
        comments = textwrap.dedent(
            "\n".join(
                remark(each)
                for each in draft.comments
                if each.item == item.number and each.text.strip()
            )
        )
        if item.number in draft.declined:
            declined = await self.decided(item.number, approved=False, comment=comments)
            return dispatched.model_copy(
                update={"declined": [*dispatched.declined, declined]}
            )
        marked = item.number in draft.done
        match item.reason:
            case HeldChange(landing=AtLanding()) if comments and not marked:
                note = await self.held_back(item, comments)
                return dispatched.model_copy(
                    update={"noted": [*dispatched.noted, note]}
                )
            case HeldChange():
                approved = await self.decided(
                    item.number, approved=True, comment=comments
                )
                return dispatched.model_copy(
                    update={"approved": [*dispatched.approved, approved]}
                )
            case Approval() if marked or not comments:
                approved = await self.decided(
                    item.number, approved=True, comment=comments
                )
                return dispatched.model_copy(
                    update={"approved": [*dispatched.approved, approved]}
                )
            case Approval(pushed_by=Conversation() as pusher):
                note = await self.posted(
                    Message(kind="note", text=unanswered(item, comments)),
                    Operator(),
                    pusher,
                    None,
                )
                return dispatched.model_copy(
                    update={"noted": [*dispatched.noted, note]}
                )
            case _:
                return dispatched.model_copy(
                    update={"kept": [*dispatched.kept, item.number]}
                )

    def answered(self, answer: Answer, parts: list[Anchor]) -> list[Tag | str]:
        """Tag the operator's answer: what was asked, then each decision with its text, the lean it was asked with and their verdict, then their words, a comment on the whole or a plain question's answer; each ruling and the comment with the id of its part among `parts`, the answer's, which a citation of the operator's words names."""
        match self.inbox.item(answer.question).reason:
            case Question(text=text, decisions=decisions):
                pass
            case _:
                message = f"{cited(answer.question)} isn't a question"
                raise InboxError(message)

        def decided(ruling: Ruling, anchor: Anchor) -> Tag:
            decision = decisions[ruling.decision - 1]
            verdict = (
                "answered in words" if ruling.verdict is None else ruled(ruling.verdict)
            )
            words = (
                [Tag(name="comment", parts=[ruling.comment])] if ruling.comment else []
            )
            return Tag(
                name="decision",
                attributes={
                    "number": str(ruling.decision),
                    "lean": decision.lean,
                    "verdict": verdict,
                    "id": anchor.id.said(),
                },
                parts=[decision.text, *words],
            )

        ruled_on = parts[: len(answer.rulings)]
        rulings = [
            decided(ruling, anchor)
            for ruling, anchor in zip(answer.rulings, ruled_on, strict=True)
        ]
        whole: list[Tag | str] = [
            Tag(
                name="comment", attributes={"id": anchor.id.said()}, parts=[anchor.text]
            )
            for anchor in parts[len(answer.rulings) :]
        ]
        return [Tag(name="asked", parts=[text]), *rulings, *whole]

    def told(self, party: Conversation, room: int, fits: int, how: How) -> Posted:
        """Tell `party` what waits for it, oldest first, in `room` bytes at most: each whole where a hook carries it whole (`fits`), else announced.

        One already announced is left for `wait_inbox`. The first that doesn't
        fit in what's left waits, with all after it, for the next hook.
        """

        def chosen() -> Generator[Choice]:
            left = room
            for item in self.tellable(party):
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
        waiting = self.tellable(party)
        told = Told(at=self.clock.now(), how=how)
        for item in waiting:
            self.inbox.kept(item.model_copy(update={"state": told}))
        return SEPARATOR.join(self.said(item) for item in waiting)

    async def held(
        self,
        party: Conversation,
        until: Callable[[], bool],
        *,
        on: list[Waking],
        within: timedelta | None = None,
    ) -> str:
        """Hold a call of `party`'s until `until()`, checked again at each arrival; until its runtime holds for it news of whoever `on` names; or until `within` passes, by the delivery's clock, where it's given. Then tell it everything waiting, and what its runtime holds for it.

        What the runtime holds is looked at each `glance`, and as the call
        returns, and told once: it reaches the agent from the runtime as the
        call returns, so the call says only what it is (`queue`). Where its
        turn ended while the call held, nothing is counted told: it says what
        waits reaches the agent at its next call. A call cancelled while it
        holds, its connection gone, leaves everything waiting.
        """
        presence = self.presence(party)
        holder = Held(arrived=asyncio.Event())
        presence.held = [*presence.held, holder]
        deadline = None if within is None else self.clock.now() + within

        async def glancing() -> None:
            while True:
                await asyncio.sleep(self.glance.total_seconds())
                holder.arrived.set()

        glances = asyncio.create_task(glancing())
        try:
            while not until():
                held = await self.queued(party)
                if any(waking(each.kind) in on for each in held):
                    break
                if deadline is not None and self.clock.now() >= deadline:
                    break
                await holder.arrived.wait()
                holder.arrived.clear()
        finally:
            glances.cancel()
            presence.held = [each for each in presence.held if each is not holder]
        if holder.ended:
            return (
                "Your turn ended while this call waited, so what reached your inbox "
                "reaches you at your next call instead."
            )
        held = await self.queued(party)
        presence.queued = [*presence.queued, *(each.id for each in held)]
        told = [self.whole(party, "held call"), *([queue(held)] if held else [])]
        said = SEPARATOR.join(each for each in told if each)
        if said or within is None:
            return said
        return f"Nothing reached you within {spelled(within)}, this call's `within`."

    async def queued(self, party: Conversation) -> list[Queued]:
        """Return what `party`'s runtime holds for it that no held call told yet, oldest first: none where its runtime's records don't say (`queues`).

        What a call told is kept while the runtime holds it, and forgotten
        once it doesn't, so the list stays as short as the runtime's queue.
        """
        queues = self.queues.get(party.runtime)
        if queues is None:
            return []
        kept = await asyncio.to_thread(queues.queued, party.session, party.agent)
        presence = self.presence(party)
        presence.queued = [each.id for each in kept if each.id in presence.queued]
        return [each for each in kept if each.id not in presence.queued]

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
        quiet: bool = False,
    ) -> Item:
        """Make an item, its citations of the operator's words read where it's a conversation's own words to them (`cited`), and deliver it (`delivered`); `call` is the runtime's id for the agent's call that made it, where one did, and `quiet` says it waits for a call (`Item.quiet`)."""
        made = self.inbox.made(
            reason,
            sender,
            recipient,
            worktree,
            self.clock.now(),
            call=call,
            quiet=quiet,
        )
        item = self.cited(made)
        await self.delivered(item)
        return item

    async def delivered(self, item: Item) -> None:
        """Tell the recipient that `item` reached its inbox: the operator through a desktop notice, a conversation through its held calls, or by waking it where the item isn't quiet: the operator's own, or a message another conversation sent it."""
        match item.recipient:
            case Operator():
                await self.noticed(item)
            case Conversation() as conversation:
                self.arrive(conversation)
                if not item.quiet:
                    await self.wake(conversation)

    def wakes(self, party: Conversation) -> bool:
        """Say whether `party`'s session can be woken idle at all: its runtime spells a push or a line for its messaging socket (`Waker`); not where its adapter declares neither."""
        return (
            self.waker.pushed(party.runtime, "", "") is not None
            or self.waker.woken(party.runtime, party.session, "") is not None
        )

    async def noticed(self, item: Item) -> None:
        """Raise a desktop notice for an item reaching the operator, where its kind's rank raises one (`ranked`): where it's from, what it is, and its first line."""
        if not item.rank.notifies:
            return
        where = "" if item.worktree is None else f" in {item.worktree}"
        summary = f"lup: {what(item)} from {who(item.sender)}{where}"
        body = f"{opening(item)}\nlup-dev inbox show {item.number}"
        await self.notices.notify(summary, body)

    async def wake(self, party: Conversation) -> None:
        """Start a turn of an idle `party`'s session on what waits for it: pushed through lup's tool server, where its runtime takes a push, else its doorbell rung through its messaging socket.

        Only a session's main conversation is woken, only while it's idle, and
        never for quiet items alone (`Item.quiet`), which a wake for another
        carries with it. One in its turn (`Presence.turning`) is told at its
        next call, or its turn's end; a call it holds is given it; a wake since
        its last hook started a turn whose first call tells it; and a runtime
        with no way waits for its next hook. An idle session starts a turn with
        it; one the service took for idle, unknown since the service started
        again or since the operator interrupted it, takes it at its next
        boundary, as measured on the runtime that has a way
        (`docs/field-notes.md`, *Waking a session*, *Channels*).
        """
        presence = self.presence(party)
        place = self.inbox.whereabouts.get(party.key())
        waiting = self.inbox.waiting(party)
        busy = presence.turning or presence.woken or presence.held
        loud = [item for item in waiting if not item.quiet]
        if party.agent is not None or busy or place is None or not loud:
            return
        if self.pushed(party, place, waiting):
            return
        await self.rung(party, place, waiting)

    def pushed(
        self, party: Conversation, place: Whereabouts, waiting: list[Item]
    ) -> bool:
        """Push what waits for idle `party` to its session through lup's tool server, each item whole, and say whether it was pushed.

        What's pushed stays waiting, which no hook or held call tells while the
        push is pending (`tellable`), and is counted told once a turn's start
        carries the push's token (`taken`); where none does within `patience`,
        it's told as anything waiting is (`unless_taken`). The pending push is
        held in memory alone, so a service started again tells what it pushed
        at the next hook, at worst a second time, never not at all. Nothing's
        pushed where the runtime takes no push, the launch has no open
        connection to lup's tool server, or its session took no push before.
        """
        if place.launch in self.unpushed:
            return False
        token = secrets.token_hex(8)
        text = SEPARATOR.join(self.said(item) for item in waiting)
        notice = self.waker.pushed(party.runtime, text, token)
        if notice is None or not self.pushes.push(place.launch, notice):
            return False
        presence = self.presence(party)
        presence.woken = True
        pushed = Pushed(token=token, numbers=[item.number for item in waiting])
        presence.pushed = pushed
        task = asyncio.create_task(self.unless_taken(party, place, pushed))
        self.waits = [*(each for each in self.waits if not each.done()), task]
        numbers = ", ".join(cited(number) for number in pushed.numbers)
        self.say(f"{place.launch}: pushed {numbers} to {who(party)}")
        return True

    def taken(self, party: Conversation, pushed: Pushed) -> None:
        """Count what `pushed` told `party` as told, its session having started a turn on it."""
        self.presence(party).pushed = None
        told = Told(at=self.clock.now(), how="wake")
        for number in pushed.numbers:
            match self.inbox.item(number):
                case Item(state=Waiting()) as item:
                    self.inbox.kept(item.model_copy(update={"state": told}))
                case _:
                    pass

    async def unless_taken(
        self, party: Conversation, place: Whereabouts, pushed: Pushed
    ) -> None:
        """Wait `patience` for `party`'s session to take `pushed`; where it doesn't, leave what it told to be told as anything waiting is, say so once, and wake the session through its messaging socket from then on."""
        await asyncio.sleep(self.patience.total_seconds())
        presence = self.presence(party)
        if presence.pushed != pushed:
            return
        presence.pushed = None
        presence.woken = False
        self.unpushed = [*self.unpushed, place.launch]
        self.say(
            f"{place.launch}: {who(party)} took nothing lup pushed within "
            f"{self.patience.total_seconds():g} seconds, so it's woken through its "
            "messaging socket from now on: its runtime may not have loaded lup's "
            "server to push (docs/inbox.md, *How an agent is told*)"
        )
        await self.wake(party)

    async def rung(
        self, party: Conversation, place: Whereabouts, waiting: list[Item]
    ) -> None:
        """Ring idle `party`'s session's doorbell through its messaging socket: what waits, for `wait_inbox` to read, where its runtime has a way.

        The items stay waiting, told once by whichever reaches the agent first:
        `wait_inbox`, its next call's hook, or its turn's end; where the
        session's messaging socket can't be reached, that's said.
        """
        line = self.waker.woken(party.runtime, party.session, doorbell(waiting))
        if line is None:
            return
        presence = self.presence(party)
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
        numbers = ", ".join(cited(item.number) for item in waiting)
        self.say(f"{place.launch}: woke {who(party)} for {numbers}")

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
            case Item(
                reason=Message() | Friction() | HowItFelt() | Stop() | Flagged(),
                sender=Conversation() as sender,
            ):
                return await self.replied(item, sender, rulings, comment)
            case Item(
                reason=Question(decisions=decisions),
                state=Waiting(),
                sender=Conversation() as asker,
            ):
                pass
            case _:
                message = (
                    f"{cited(number)} is {what(item)} from {who(item.sender)}: neither "
                    "a question waiting for an answer nor a conversation's message to "
                    "reply to"
                )
                raise InboxError(message)
        given = sorted(each.decision for each in rulings)
        if given != list(range(1, len(decisions) + 1)):
            message = (
                f"{cited(number)} asks {len(decisions)} decisions, each taking one "
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
                f"{cited(number)}'s decisions {unsaid} have neither a verdict nor "
                "words: give one"
            )
            raise InboxError(message)
        if not decisions and not comment.strip():
            message = f"{cited(number)} is a question answered in words: give them"
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
                f"{cited(item.number)} is {what(item)}, which takes a reply in words, "
                "not verdicts"
            )
            raise InboxError(message)
        if not comment.strip():
            message = f"{cited(item.number)} is {what(item)}: give your reply in words"
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

    def flag_approved(self, number: int) -> Item:
        """Approve the flagged write item `number`, as marking it good in its agent's drawer does (`lup_dev.policy.since`), whatever its state but approved already, which it keeps; refused where it isn't a flagged write."""
        item = self.inbox.item(number)
        if not isinstance(item.reason, Flagged):
            message = f"{cited(number)} is {what(item)}, not a flagged write"
            raise InboxError(message)
        if isinstance(item.state, Decided) and item.state.approved:
            return item
        approved = Decided(at=self.clock.now(), approved=True)
        self.say(f"{cited(number)}, a flagged write, was approved")
        return self.inbox.kept(item.model_copy(update={"state": approved}))

    def flag_withdrawn(self, number: int, why: str) -> Item | None:
        """Take the flagged write item `number` back off the operator's list for lup, with its reason, a landing having left it nothing to hold; none where it isn't a flagged write still waiting for them, which keeps its state.

        It's left unread: what it kept is no version the operator saw.
        """
        item = self.inbox.items.get(number)
        match item:
            case Item(reason=Flagged(), recipient=Operator(), state=Waiting()):
                taken = Withdrawn(at=self.clock.now(), why=why)
                self.say(f"{cited(number)}, a flagged write, was withdrawn by lup")
                return self.inbox.kept(item.model_copy(update={"state": taken}))
            case _:
                return None

    def done(self, number: int) -> Item:
        """Take the message item `number` off the operator's list: a flagged write approved, read with nothing to add.

        A question is answered instead, and an item that isn't the operator's,
        or isn't waiting, is refused.
        """
        item = self.inbox.item(number)
        match item:
            case Item(reason=Flagged(), recipient=Operator(), state=Waiting()):
                approved = Decided(at=self.clock.now(), approved=True)
                return self.inbox.kept(item.model_copy(update={"state": approved}))
            case Item(
                reason=Message() | Friction() | HowItFelt() | Stop(),
                recipient=Operator(),
                state=Waiting(),
            ):
                done = Done(at=self.clock.now())
                return self.inbox.kept(item.model_copy(update={"state": done}))
            case Item(reason=Question() | Approval() | HeldChange(), state=Waiting()):
                message = (
                    f"{cited(number)} is {what(item)}: answer it, `lup-dev inbox answer "
                    f"{number}`"
                )
                raise InboxError(message)
            case _:
                message = f"{cited(number)} isn't a message waiting in your inbox"
                raise InboxError(message)

    def withdrawn(self, number: int, party: Conversation, why: str) -> Item:
        """Take the message or question item `number` back for `party`, who sent it, off the operator's list, with its reason.

        Another's item, one that isn't waiting for the operator, an approval or a
        held change, which only the operator answers, and a message sent to
        another conversation or the operator's copy of it, which the operator
        sees as agents send each other, are refused.
        """
        item = self.inbox.item(number)
        match item:
            case (
                Item(reason=Message(to=Conversation() as to))
                | Item(recipient=Conversation() as to)
            ) if item.sender == party:
                called = self.called(to)
                whom = who(to) if called is None else f"`{called}`"
                message = (
                    f"{cited(number)} is your message to {whom}, which the operator "
                    "reads a copy of: neither is withdrawn. Where it was wrong, `send` "
                    "a correction"
                )
                raise InboxError(message)
            case Item(
                reason=Message() | Friction() | HowItFelt() | Stop() | Question(),
                recipient=Operator(),
                state=Waiting(),
            ) if item.sender == party:
                taken = Withdrawn(at=self.clock.now(), why=why)
                self.say(f"{cited(number)}, {what(item)}, was withdrawn by its sender")
                return self.inbox.kept(item.model_copy(update={"state": taken}))
            case Item(sender=sender) if sender != party:
                message = (
                    f"{cited(number)} is {what(item)} from {who(sender)}: only its "
                    "sender withdraws it"
                )
                raise InboxError(message)
            case Item(reason=Approval() | HeldChange()):
                message = (
                    f"{cited(number)} is {what(item)}, which the operator answers: it "
                    "isn't withdrawn"
                )
                raise InboxError(message)
            case Item(reason=Flagged()):
                message = (
                    f"{cited(number)} is {what(item)}, which lup put before the "
                    "operator for their review: it isn't withdrawn"
                )
                raise InboxError(message)
            case _:
                message = (
                    f"{cited(number)} no longer waits for the operator: it's "
                    f"{standing(item)}"
                )
                raise InboxError(message)

    async def edited(
        self, number: int, party: Conversation, old: str | None, new: str
    ) -> Item:
        """Edit item `number` for `party`, who sent it the operator: `old`, a passage of its text found there once, replaced by `new`; or, with no `old`, its text whole replaced by `new`. Keep the text before beside it (`Item.edits`), read its citations again (`cited`), take back lup's word on those that didn't resolve where it still waits, and put it back before the operator where it had left their list (`reopened`).

        Refused where it isn't `party`'s words to the operator (another's, lup's
        own, or a copy of a message to a conversation, which that conversation
        read as it was), where it's a question answered or an item withdrawn,
        where `old` isn't in its text once, or the edit changes nothing or
        leaves it empty.
        """
        item = self.inbox.item(number)
        text = editable(item, party)
        after = new if old is None else replaced(text, old, new, number)
        if not after.strip():
            message = f"the edit leaves {cited(number)} empty: `withdraw` it instead"
            raise InboxError(message)
        if after == text:
            message = f"the edit leaves {cited(number)} as it was"
            raise InboxError(message)
        now = self.clock.now()
        changed = self.inbox.kept(
            item.model_copy(
                update={
                    "reason": rewritten(item.reason, after),
                    "edits": [*item.edits, Edit(at=now, before=text)],
                }
            )
        )
        for each in self.inbox.waiting(party):
            if isinstance(each.reason, Unresolved) and each.reason.of == number:
                taken = Superseded(at=now, by=number)
                self.inbox.kept(each.model_copy(update={"state": taken}))
        result = self.cited(changed)
        await self.reopened(party, number)
        self.say(f"{cited(number)}, {what(item)}, was edited by its sender")
        return self.inbox.item(result.number)

    async def sent(
        self,
        launch: str,
        text: str,
        agent: str | None = None,
        passages: list[Passage] | None = None,
    ) -> Item:
        """Send the operator's message to a conversation of the session `launch` runs: its main one, or its subagent `agent`; with the passages of its words they replied to, where they send it from reading it."""
        conversation = self.main_of(launch).model_copy(update={"agent": agent})
        message = Message(kind="note", text=text, passages=passages or [])
        return await self.posted(message, Operator(), conversation, None)

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
            self.say(
                f"{cited(each.number)}, an approval, is superseded by {cited(item.number)}"
            )
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
                f"{cited(number)} isn't an approval or a held change, but {what(item)}"
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
        answer. A hold at landing has no hook: approved, each flagged write it
        covers is approved with it; and its answer reaches the conversation
        landing, a note where it was declined or commented, so it's told even
        where no call waits on it (`landing_decided`). One answered
        already keeps its answer, whichever came first, and is returned as it
        stands.
        """
        item = self.approval(number)
        if not isinstance(item.state, Waiting):
            return item
        if isinstance(item.reason, HeldChange) and item.reason.landing is None:
            if self.settle_hold is None:
                message = (
                    f"{cited(number)} is a held change, which this service can't answer"
                )
                raise InboxError(message)
            self.settle_hold(item.reason, approved, comment)
        decided = Decided(at=self.clock.now(), approved=approved, comment=comment)
        answered = self.inbox.kept(item.model_copy(update={"state": decided}))
        self.settle(number)
        said = "approved" if approved else "declined"
        self.say(f"{cited(number)}, {what(item)}, was {said}")
        match item.reason:
            case Approval(pushed_by=Conversation() as pusher) if comment.strip():
                await self.posted(
                    Message(kind="note", text=commented(answered, comment)),
                    Operator(),
                    pusher,
                    None,
                )
            case HeldChange(landing=AtLanding() as landing):
                await self.landing_decided(
                    answered, landing, approved=approved, comment=comment
                )
            case _:
                pass
        return answered

    async def landing_decided(
        self, item: Item, landing: AtLanding, *, approved: bool, comment: str
    ) -> None:
        """Carry the operator's answer to hold at landing `item` on: each flagged write it covers approved with it, where it's approved; and the answer to the conversation landing, its sender, a note where it was declined or carries a comment, else a wake for its call.

        A flagged write approved already, or taken off the list since, keeps
        its state but for an approval.
        """
        at = self.clock.now()
        if approved:
            for number in landing.flags:
                flag = self.inbox.items.get(number)
                if flag is None or not isinstance(flag.reason, Flagged):
                    continue
                if isinstance(flag.state, Decided) and flag.state.approved:
                    continue
                kept = Decided(at=at, approved=True, comment=comment)
                self.inbox.kept(flag.model_copy(update={"state": kept}))
        lander = item.sender
        if not isinstance(lander, Conversation):
            return
        if approved and not comment.strip():
            self.arrive(lander)
            return
        did = "approved it" if approved else "declined it"
        await self.posted(
            Message(kind="note", text=answered_hold(item, did, comment)),
            Operator(),
            lander,
            None,
        )

    async def held_back(self, item: Item, comments: str) -> Item:
        """Settle hold at landing `item`, which the operator commented on without approving it, as done, and send the comments to the conversation landing as a note; return the note.

        A comment usually asks for a change, so the landing goes no further:
        the conversation answers it and lands again, and the flagged writes the
        hold covers wait for their approval at that landing.
        """
        done = Done(at=self.clock.now())
        self.inbox.kept(item.model_copy(update={"state": done}))
        self.say(f"{cited(item.number)}, a hold at landing, was commented on")
        return await self.posted(
            Message(
                kind="note",
                text=answered_hold(
                    item, "commented on it without approving it", comments
                ),
            ),
            Operator(),
            item.sender,
            None,
        )

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

    async def held_at_landing(
        self,
        change: HeldChange,
        sender: Conversation,
        diff: str,
        files: list[ChangedFile],
        *,
        call: str | None = None,
    ) -> Item:
        """Put a hold at landing in the operator's inbox from the conversation landing, its diff and file kept beside it, anchored to `call`, and raise its notice; return it.

        A hold of the same repository's still waiting on the same file at a
        landing onto the same branch, from an earlier landing whose call may be
        gone, is joined where it holds the same tip and flags, and superseded
        by this one otherwise, waking the call waiting on it.
        """
        landing = change.landing
        if landing is None:
            message = "a hold at landing says what it holds at landing"
            raise InboxError(message)
        earlier = [
            item
            for item in self.inbox.waiting(Operator())
            if isinstance(item.sender, Conversation)
            and item.sender.repository == sender.repository
            and isinstance(item.reason, HeldChange)
            and item.reason.landing is not None
            and item.reason.landing.onto == landing.onto
            and item.reason.landing.path == landing.path
        ]
        same = next(
            (
                item
                for item in earlier
                if isinstance(item.reason, HeldChange)
                and item.reason.landing == landing
                and item.sender == sender
            ),
            None,
        )
        if same is not None:
            return same
        item = self.inbox.made(
            change, sender, Operator(), change.worktree, self.clock.now(), call=call
        )
        self.inbox.attached(item.number, diff, files)
        superseded = Superseded(at=self.clock.now(), by=item.number)
        for each in earlier:
            self.inbox.kept(each.model_copy(update={"state": superseded}))
            if isinstance(each.sender, Conversation):
                self.arrive(each.sender)
            self.say(
                f"{cited(each.number)}, a hold at landing, is superseded by "
                f"{cited(item.number)}"
            )
        await self.noticed(item)
        return item

    async def flagged(
        self,
        flagged: Flagged,
        sender: Conversation,
        diff: str,
        file: ChangedFile,
        *,
        call: str | None = None,
        joining: int | None = None,
        refreshing: bool = False,
    ) -> Item:
        """Put a write that landed flagged in the operator's inbox from the conversation that made it, holding no one, and raising no notice (`ranked`).

        It joins item `joining`, its file whole since that item was made and its
        diff in place of those kept, where that item still gathers the
        conversation's writes to the file (`Inbox.gathering`); else it's an
        item of its own, anchored to `call`, its diff and file kept beside it.
        A write `refreshing` the item it joins, flagging nothing of its own,
        makes none: where the item gathers no more, it's left as it was.
        """
        gathered = self.inbox.gathering(sender, flagged.worktree, flagged.path)
        if (
            gathered is not None
            and gathered.number == joining
            and isinstance(gathered.reason, Flagged)
        ):
            self.inbox.attached(gathered.number, diff, [file])
            writes = gathered.reason.writes + 1
            joined = flagged.model_copy(update={"writes": writes})
            return self.inbox.kept(gathered.model_copy(update={"reason": joined}))
        if refreshing and joining is not None:
            return self.inbox.item(joining)
        item = self.inbox.made(
            flagged, sender, Operator(), flagged.worktree, self.clock.now(), call=call
        )
        self.inbox.attached(item.number, diff, [file])
        await self.delivered(item)
        return item

    def changing(self, number: int) -> Item:
        """Return item `number`, or say it changes no file: an approval, a held change and a flagged write keep theirs beside them."""
        item = self.inbox.item(number)
        if not isinstance(item.reason, Approval | HeldChange | Flagged):
            message = (
                f"{cited(number)} is {what(item)}, which changes no file: an approval, "
                "a held change or a flagged write does"
            )
            raise InboxError(message)
        return item
