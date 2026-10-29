"""Reading the inbox a line an item, or each whole, narrowed to one conversation's exchange where asked: the agents' `inbox` tool and `lup-dev inbox` read it alike.

`docs/inbox.md`, *Reading an exchange*. What's listed is narrowed as every list
lup answers is (`lup_dev.listing`: when each was made, the latest up to a limit,
what's left out said with what reads it), and further:
- **one conversation's exchange** (`conversation`): the items they sent and
  were sent, and with `subagents` those of each subagent below them. They're
  named by their path (`flow-review/explore-auth`), their own name, or their
  runtime's id or the id's start (`Reader.matching`). A session's name is their
  launch's as lup last kept it (`SessionNames`), a subagent's as their
  whereabouts last heard it, or, from before whereabouts kept it, as it was told
  to their parent when they ended. Names repeat
  over time, a branch's above all, so a name several conversations had reads
  the one last heard, and the answer names the others by id;
- **the kinds** of item (`kinds`), as a tag's `kind` names them;
- **whole** (`whole`): each item as its sender wrote it, or as it was told to
  whom it was for. The operator's words on a conversation's item are told under
  it, with any reply copies before kept on them, and a turn's end says which of
  their items it answers, so an exchange reads as one thread; their item says
  so where it's listed too, and a review's context, the operator's words to
  others, is left out.

Waiting items alone are listed unless `every` is asked, and what that leaves out
is counted too, with the parameter that reads it.

**A conversation's flagged writes are one entry** (`Flags`, `by_agent`), placed
at its latest, rather than a line a file: what it changed is the operator's to
read in its agent's drawer (`docs/dashboard.md`, *The drawers*), and ten files
of one branch listed a line each buried what waits on them. Each stays an item
of its own underneath, which a landing waits on, read whole by its number; an
entry counts as one against a `limit`, and says how many files, on which
branches, and where they stand; read whole, each under it names its file.
"""

from typing import TYPE_CHECKING

from pydantic import Field, PositiveInt

from lup.types import Model
from lup_dev.inbox.concerns import Concerns, triggers
from lup_dev.inbox.delivery import (
    Delivery,
    clocked,
    remarked,
    standing,
)
from lup_dev.inbox.parts import PartId
from lup_dev.inbox.roster import Roster, ids
from lup_dev.inbox.store import (
    Answer,
    Decided,
    Done,
    Flagged,
    Item,
    ItemNode,
    Message,
    Review,
    Waiting,
    cited,
)
from lup_dev.inbox.tags import Tag
from lup_dev.inbox.texts import (
    ItemKind,
    kind,
    opening,
    what,
    written,
)
from lup_dev.inbox.threads import Anchor, addressed_to, anchors, cue, spoken
from lup_dev.listing import Span, latest, many, unlisted
from lup_ledger import threads as ledger
from lup_ledger.parties import Conversation, Lup, Operator, Party, Writer
from lup_ledger.threads import (
    Answered,
    Check,
    Member,
    Moved,
    Parked,
    Standing,
    Thread,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


class Narrowing(Span):
    """What of the inbox to list, and how: when each was made, whose, of what kinds, in what state, how many, and whether each whole."""

    conversation: str | None = Field(
        default=None,
        description=(
            "Only one conversation's exchange: the items they sent and were sent. "
            "A session by their name (`flow-review`), a subagent by their path "
            "(`flow-review/explore-auth`) or their own name, or either by their "
            "runtime's id or the id's start. Where a name was several "
            "conversations', the one last heard is read, and the answer names "
            "the others by id. Left out, every conversation's."
        ),
    )
    subagents: bool = Field(
        default=False,
        description=(
            "With `conversation`, their subagents' items too, and theirs' below "
            "them; left out, their own alone."
        ),
    )
    kinds: list[ItemKind] | None = Field(
        default=None,
        description=(
            "Only items of these kinds, as a tag's `kind` names them: `turn's end` "
            "for a session's last words of a turn, lup's note of them. Left out, "
            "every kind."
        ),
    )
    whole: bool = Field(
        default=False,
        description=(
            "Each item whole, rather than a line: as its sender wrote it, or as it "
            "was told to whom it was for. The operator's words on a "
            "conversation's item come under it, and a turn's end says which of "
            "their items it answers, so an exchange reads as one thread; a "
            "review's words to other agents are left out."
        ),
    )
    every: bool = Field(
        default=False,
        description=(
            "List every item, those answered, done or told too; left out, those "
            "still waiting alone, the rest counted."
        ),
    )
    limit: PositiveInt | None = Field(
        default=None,
        description=(
            "How many items to list at most, the latest: left out, 50 a line each, "
            "or 10 whole. Those left out are counted."
        ),
    )
    thread: str | None = Field(
        default=None,
        description=(
            "Only one thread, by its name (`dashboard-lag`) or number, read whole: "
            "where it stands, the threads under it, then what's in it in the order "
            "it came, each whole, the operator's words on an agent's item under it, "
            "every state; `since`, `until` and `limit` narrow it."
        ),
    )

    def most(self, lines: int = 50, wholes: int = 10) -> int:
        """Return how many items to list at most: the call's `limit`; else `lines` a line each, or `wholes` whole, since an item whole can run to pages."""
        if self.limit is not None:
            return self.limit
        return wholes if self.whole else lines


class Spelling(Model):
    """How an answer names what reads what it left out: the tool's fields, or the command's options (`command`)."""

    until: str = "until"
    limit: str = "limit"
    every: str = "every"
    conversation: str = "conversation"

    @classmethod
    def command(cls) -> Spelling:
        """Return the command line's spelling: each field as `lup-dev inbox`'s option."""
        return cls(
            until="--until",
            limit="--limit",
            every="--every",
            conversation="--conversation",
        )


class Read(Model):
    """What a reading says, and how many items it found before its limit cut them: none where it found no conversation of that name."""

    text: str
    found: int = 0


class Flags(Model):
    """One conversation's flagged writes, listed as one entry rather than a line a file: each an item of its own underneath, one file's on one branch, which a landing waits on (`lup_dev.policy.landing`)."""

    items: list[Item]
    """Oldest first, all from one sender, each a flagged write."""

    @property
    def sender(self) -> Party:
        """Who made them: the conversation whose writes they are."""
        return self.items[0].sender

    @property
    def made(self) -> datetime:
        """When the latest was made, where the entry is listed."""
        return max(item.made for item in self.items)

    def flagged(self) -> list[Flagged]:
        """Return what each flagged, in order."""
        return [item.reason for item in self.items if isinstance(item.reason, Flagged)]

    def cited(self, between: str = " ") -> str:
        """Cite each item, in order, `between` each: `@59 @61`."""
        return between.join(cited(item.number) for item in self.items)

    def standing(self) -> str:
        """Say where they stand: `waiting`, or each state counted, `2 waiting, 1 approved`."""

        def state(item: Item) -> str:
            match item.state:
                case Waiting():
                    return "waiting"
                case Decided(approved=True):
                    return "approved"
                case Decided():
                    return "declined"
                case Done():
                    return "read"
                case _:
                    return "settled"

        states = [state(item) for item in self.items]
        counted = list(dict.fromkeys(states))
        if len(counted) == 1:
            return counted[0]
        return ", ".join(f"{states.count(each)} {each}" for each in counted)

    def said(self) -> str:
        """Say what they flag: how many files, one on two branches counting twice, as each branch's landing waits on it; and on which branches. Each, read whole, names its file."""
        files = list(dict.fromkeys((each.branch, each.path) for each in self.flagged()))
        branches = list(dict.fromkeys(each.branch for each in self.flagged()))
        on = and_said([f"`{each}`" for each in branches if each is not None])
        where = (
            f"on {on}"
            if None not in branches
            else f"on {on} and on no branch"
            if on
            else "on no branch"
        )
        return f"{many(len(files), 'file')} {where}"


def and_said(words: Sequence[str]) -> str:
    """Say `words` as a list in prose: `a`, `a and b`, `a, b and c`; nothing for none.

    >>> and_said(["a"]), and_said(["a", "b", "c"])
    ('a', 'a, b and c')
    """
    *first, last = words or [""]
    return f"{', '.join(first)} and {last}" if first else last


def landed(landings: list[str | None]) -> str:
    """Say what waits on a conversation's flagged writes, each landing waiting on one of them, as `Delivery.landing` names it, after their line: nothing where none waits.

    >>> landed([None, "`feat` on `dev`", "`feat` on `dev`"])
    '; the landing of `feat` on `dev` waits on them, in "since you approved"'
    >>> landed([None])
    ''
    """
    named = list(dict.fromkeys(each for each in landings if each is not None))
    if not named:
        return ""
    return f'; the landing of {and_said(named)} waits on them, in "since you approved"'


def by_agent(items: list[Item]) -> list[Item | Flags]:
    """Return `items`, oldest first, with each conversation's flagged writes as one entry (`Flags`), placed at its latest, and the rest as they are."""
    flagged = [item for item in items if isinstance(item.reason, Flagged)]
    senders = list(dict.fromkeys(item.sender for item in flagged))
    entries: list[Item | Flags] = [
        *(item for item in items if not isinstance(item.reason, Flagged)),
        *(
            Flags(items=[item for item in flagged if item.sender == sender])
            for sender in senders
        ),
    ]
    return sorted(entries, key=lambda each: each.made)


def counted(entries: list[Item | Flags]) -> int:
    """Count the items `entries` hold, each entry of flagged writes as many as it gathers."""
    return sum(len(each.items) if isinstance(each, Flags) else 1 for each in entries)


class Reader(Model, arbitrary_types_allowed=True):
    """The inbox as one party reads it, the agent's conversation or the operator: what's listed, and how each party is named to them."""

    delivery: Delivery
    reader: Party
    """Who reads, named "you" where an item is theirs."""
    where: str = ""
    """What the items read are, said after "Nothing" where none is listed, as
    " about this repository" for a repository's items alone; nothing for the
    whole inbox."""
    mine: bool = False
    """Whether what's read is the reader's own exchange, the items they sent or
    were sent, those waiting for them alone unless `every`: the operator's, at
    `lup-dev inbox`. An agent's `inbox` reads every party's, waiting for
    whomever it's for."""
    spelling: Spelling = Spelling()

    @property
    def roster(self) -> Roster:
        """The conversations the inbox knows, each by the name lup calls them (`Delivery.roster`)."""
        return self.delivery.roster()

    def read(self, items: list[Item], wanted: Narrowing) -> Read:
        """Return `items`, oldest first, as `wanted` narrows them: a line each, or each whole, then what was left out and what reads it; or one thread of theirs, whole (`threaded`)."""
        if wanted.thread is not None:
            return self.threaded(items, wanted.thread, wanted)
        conversation = wanted.conversation
        readable = [
            item
            for item in items
            if not self.mine or self.reader in [item.sender, item.recipient]
        ]
        if conversation is None:
            return self.listed(readable, wanted, None)
        matched = self.matching(conversation, items)
        if not matched:
            return Read(
                text=(
                    f"No conversation{self.where} is `{conversation}`: "
                    f"`{self.spelling.conversation}` takes a session's name, a "
                    "subagent's path or their own name, or the runtime's id for "
                    "either, or the id's start, as `inbox` lines name them."
                )
            )
        found, *others = matched
        below = self.below(found, items) if wanted.subagents else []
        group = [found, *below]
        pool = [
            item
            for item in readable
            if any(
                each in group for each in [item.sender, item.recipient, item.addressed]
            )
        ]
        heading = "\n".join(
            [
                *self.alike(conversation, found, others, items),
                self.heading(found, below, wanted),
            ]
        )
        return self.listed(pool, wanted, heading)

    def listed(
        self,
        pool: list[Item],
        wanted: Narrowing,
        heading: str | None,
    ) -> Read:
        """Return the items of `pool` that `wanted` narrows to, under `heading` where one names the exchange: a line each or each whole, then what was left out."""
        window = wanted.window(self.delivery.clock.now())
        kinds = wanted.kinds
        timely = [
            item
            for item in pool
            if window.covers(item.made) and (kinds is None or kind(item) in kinds)
        ]
        chosen = [item for item in timely if wanted.every or self.waits(item)]
        left_waiting = many(len(timely) - len(chosen), "item")
        unwaited = "not waiting for you" if self.mine else "no longer waiting"
        settled = (
            [
                (
                    f"Not listed: {left_waiting} {unwaited}, which "
                    f"`{self.spelling.every}` lists."
                )
            ]
            if len(timely) > len(chosen)
            else []
        )
        head = [] if heading is None else [heading]
        if not chosen:
            of = "" if kinds is None else " of those kinds"
            where = "" if heading is not None else self.where
            waits = (
                "is in the inbox"
                if wanted.every
                else "waits for you"
                if self.mine
                else "waits in the inbox"
            )
            nothing = f"Nothing{of}{where} {waits}{window.said()}."
            return Read(text="\n".join([*head, nothing, *settled]))
        entries = by_agent(chosen)
        shown = latest(entries, lambda each: each.made, wanted.most())
        if wanted.whole:
            placed = [
                item.number
                for each in shown
                for item in (each.items if isinstance(each, Flags) else [each])
            ]
            said = "\n\n".join(self.whole(each, placed) for each in shown)
        else:
            said = "\n".join(self.line(each) for each in shown)
        left = unlisted(
            len(chosen) - counted(shown),
            "earlier item",
            shown[0].made,
            len(entries),
            until=self.spelling.until,
            limit=self.spelling.limit,
        )
        gap = [""] if wanted.whole and (left or settled) else []
        return Read(
            text="\n".join([*head, said, *gap, *left, *settled]), found=len(chosen)
        )

    def threaded(self, items: list[Item], said: str, wanted: Narrowing) -> Read:
        """Return the thread of `items`' repositories `said` names, whole: where it stands, the threads under it, the items of other threads that name it, then what's in it, oldest first, each whole, the latest `wanted` lets through."""
        concerns = self.delivery.concerns()
        repositories = list(
            dict.fromkeys(
                each.repository
                for item in items
                for each in [item.sender, item.recipient, item.addressed]
                if isinstance(each, Conversation)
            )
        )
        found = [
            each
            for each in (
                concerns.found(repository, said) for repository in repositories
            )
            if isinstance(each, Thread)
        ]
        threads = list({each.number: each for each in found}.values())
        if not threads:
            return Read(
                text=(
                    f"No thread{self.where} is `{said}`: `thread` takes a thread's "
                    "name or number."
                )
            )
        if len(threads) > 1:
            numbers = and_said([f"@{each.number}" for each in threads])
            return Read(
                text=f"`{said}` names threads of several repositories, {numbers}: read one by its number."
            )
        [thread] = threads
        members = concerns.threads.members(thread.number)
        window = wanted.window(self.delivery.clock.now())
        timely = [each for each in members if window.covers(made_of(each))]
        shown = latest(
            timely, made_of, wanted.model_copy(update={"whole": True}).most()
        )
        placed = [each.node.number for each in shown if each.part is None]
        said_whole = [self.member(each, thread, placed) for each in shown]
        left = (
            unlisted(
                len(timely) - len(shown),
                "earlier entry",
                made_of(shown[0]),
                len(timely),
                until=self.spelling.until,
                limit=self.spelling.limit,
            )
            if shown
            else []
        )
        nothing = [] if timely else [f"Nothing is in it{window.said()}."]
        return Read(
            text="\n\n".join(
                [
                    "\n".join(self.heading_of(concerns, thread)),
                    *said_whole,
                    *nothing,
                    *left,
                ]
            ),
            found=len(timely),
        )

    def heading_of(self, concerns: Concerns, thread: Thread) -> list[str]:
        """Say where `thread` stands, the threads right under it, and the items of other threads that name it, a line each."""
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
        under = [
            f'- @{each.name}, "{each.title}": {stood(concerns.standing(each))}'
            for each in concerns.threads.under(thread.number)
        ]
        refers = [
            f"- {self.line(item)}"
            for each in concerns.threads.references(thread.number)
            if (item := self.delivery.inbox.items.get(each.source)) is not None
        ]
        return [
            (
                f'Thread @{thread.name} (@{thread.number}), "{thread.title}"{above}, '
                f"{holder}: {stood(concerns.standing(thread))}."
            ),
            *(["Under it:", *under] if under else []),
            *(["Elsewhere, naming it:", *refers] if refers else []),
        ]

    def member(self, member: Member, thread: Thread, placed: list[int]) -> str:
        """Say what's in `thread` whole under a heading: an item as `whole` does, the operator's words on it under it; a part of their words moved in, with who moved it; a check, and their answer to it where they gave one."""
        node = member.node
        if member.part is not None:
            part = PartId(item=node.number, part=member.part)
            item = self.delivery.inbox.items.get(node.number)
            anchor = (
                None
                if item is None
                else next((each for each in spoken(item) if each.id == part), None)
            )
            moved = next(
                (
                    each
                    for each in self.delivery.inbox.ledger.drawn_to(
                        thread.number, Moved
                    )
                    if each.source == node.number and each.part == member.part
                ),
                None,
            )
            by = "" if moved is None else f", moved here by {self.wrote(moved.by)}"
            return (
                f"{part.cited()}  {clocked(made_of(member))}  the operator's words{by}:\n"
                + Tag(
                    name="part",
                    attributes={"id": part.said()},
                    parts=["" if anchor is None else anchor.text],
                ).written()
            )
        if isinstance(node, Check):
            answers = [each for each in member.drawn if isinstance(each, Answered)]
            stands = (
                "waiting on the operator"
                if not answers
                else f"answered at {clocked(answers[-1].at)}"
            )
            answer = [
                Tag(
                    name="answered",
                    attributes={"from": "operator"},
                    parts=[each.text or "Ticked."],
                )
                for each in answers
            ]
            return (
                f"@{node.number}  {clocked(node.at)}  a check from {self.wrote(node.by)}, {stands}:\n"
                + Tag(
                    name="check",
                    attributes={"item": str(node.number)},
                    parts=[node.text, *answer],
                ).written()
            )
        item = self.delivery.inbox.items.get(node.number)
        if item is None:
            return f"@{node.number}  {clocked(node.at)}  a `{node.kind}`."
        return self.whole(item, placed)

    def waits(self, item: Item) -> bool:
        """Say whether `item` still waits, as the reader lists what waits: for them alone, where they read their own exchange; else for whomever it's for."""
        waiting = isinstance(item.state, Waiting)
        return waiting and (not self.mine or item.recipient == self.reader)

    def line(self, entry: Item | Flags) -> str:
        """Say an item in a line: its number, when it was made, what it is, from whom to whom, where it stands, and its first line; a conversation's flagged writes, the files they flag, and each landing waiting on them."""
        if isinstance(entry, Flags):
            held = landed([self.delivery.landing(item.number) for item in entry.items])
            return f"{self.headed(entry)}: {entry.said()}{held}"
        return f"{self.headed(entry)}: {opening(entry)}"

    def headed(self, entry: Item | Flags) -> str:
        """Say an item's heading: its number, when it was made, what it is, from whom to whom, and where it stands; each conversation by their name (`called`), and the operator's copy of a message between conversations to whom it was sent. A conversation's flagged writes are headed as one: each number, the latest's time, and how many."""
        if isinstance(entry, Flags):
            latest = entry.items[-1]
            return (
                f"{entry.cited()}  {clocked(entry.made)}  "
                f"{many(len(entry.items), 'flagged write')} from "
                f"{self.called(entry.sender)} to "
                f"{self.called(latest.recipient)}, "
                f"{entry.standing()}"
            )
        item = entry
        match item.reason:
            case Message(to=Conversation() as to):
                recipient = f"{self.called(to)}, the operator's copy"
            case _:
                recipient = self.called(item.recipient)
        return (
            f"{cited_at(item)}  {what(item)} from "
            f"{self.called(item.sender)} to {recipient}, "
            f"{standing(item)}"
        )

    def whole(self, entry: Item | Flags, placed: list[int]) -> str:
        """Say an item whole under its heading: a conversation's as they wrote it, saying which of the operator's items a turn's end answers, the operator's words on it under it, with any reply copies before kept on them; any other's as it was told to whom it was for, what it says on the items `placed` told under them, and a review's context left out. A conversation's flagged writes under one heading, each whole."""
        heading = self.headed(entry)
        each = entry.items if isinstance(entry, Flags) else [entry]
        tags = [self.tagged(item, placed) for item in each]
        return f"{heading}:\n" + "\n".join(tags)

    def tagged(self, item: Item, placed: list[int]) -> str:
        """Say an item whole, as `whole` does under its heading."""
        match item.sender:
            case Conversation() as sender:
                answering = (
                    {"answers": " ".join(str(each) for each in item.reason.answers)}
                    if isinstance(item.reason, Message) and item.reason.answers
                    else {}
                )
                tag = Tag(
                    name="item",
                    attributes={
                        "item": str(item.number),
                        "kind": kind(item),
                        "from": self.attributed(sender),
                        **answering,
                    },
                    parts=[
                        written(item),
                        *self.thread(item, sender),
                    ],
                )
            case Operator():
                tag = self.delivery.tagged(item, under=placed, context=False)
        return tag.written()

    def thread(self, item: Item, sender: Conversation) -> list[Tag | str]:
        """Return the operator's words on `item`, `sender`'s, in the order they came: under each of their items addressed to `sender` that's on it, what it says there, then each reply `sender` made to it."""
        inbox = self.delivery.inbox
        ordered = [inbox.items[number] for number in sorted(inbox.items)]
        return [
            self.said_on(each, item, sender, on)
            for each in ordered
            if addressed_to(each, sender)
            and (
                on := [anchor for anchor in anchors(each) if anchor.item == item.number]
            )
        ]

    def said_on(
        self,
        theirs: Item,
        item: Item,
        sender: Conversation,
        on: list[Anchor],
    ) -> Tag:
        """Tag what the operator's item `theirs` says on `item`, its parts `on`, as it told them to `sender`, each with its id; then each reply of `sender`'s to them copies before kept."""
        match theirs.reason:
            case Review(comments=comments):
                parts: list[Tag | str] = [
                    part
                    for comment, anchor in zip(comments, anchors(theirs), strict=True)
                    if comment.item == item.number
                    for part in remarked(item, comment, anchor)
                ]
                name = "review"
            case Answer() as answer:
                _, *parts = self.delivery.answered(answer, anchors(theirs))
                name = "answer"
            case Message(text=text):
                parts = [
                    Tag(
                        name="comment",
                        attributes={"id": anchor.id.said()},
                        parts=[text],
                    )
                    for anchor in on
                ]
                name = "message"
            case _:
                parts = []
                name = "item"
        parted = [anchor.id for anchor in on]
        replies = [
            Tag(
                name="reply",
                attributes={
                    "id": PartId(item=theirs.number, part=reply.number).said(),
                    "to": reply.to.said(),
                    "from": self.attributed(sender),
                },
                parts=[reply.text],
            )
            for reply in theirs.replies
            if reply.to in parted
        ]
        return Tag(
            name=name,
            attributes={
                "item": str(theirs.number),
                "from": "operator",
                "made": clocked(theirs.made),
            },
            parts=[*parts, *replies],
        )

    def heading(
        self,
        found: Conversation,
        below: list[Conversation],
        wanted: Narrowing,
    ) -> str:
        """Say whose exchange is read, the conversation by their path and their runtime's ids, and what of it."""
        subagents = f" and their {many(len(below), 'subagent')}" if below else ""
        state = "every item" if wanted.every else "what still waits"
        window = wanted.window(self.delivery.clock.now()).said()
        return f"The exchange of {self.titled(found)}{subagents}: {state}{window}, oldest first."

    def titled(self, conversation: Conversation) -> str:
        """Name a conversation by their path, where lup knows it, then by their runtime's ids, which read them whatever they're named since."""
        path = self.roster.path(conversation)
        return ids(conversation) if path is None else f"`{path}` ({ids(conversation)})"

    def alike(
        self,
        wanted: str,
        found: Conversation,
        others: list[Conversation],
        items: list[Item],
    ) -> list[str]:
        """Say, first, that `wanted` names several conversations: that this reads `found`, the one last heard, and the others, each by their runtime's ids and when they were last heard, which `conversation` reads by id; nothing where it names one.

        Said before what's read, since a reader who never reaches an answer's
        last line would take one session for another.
        """
        if not others:
            return []
        each = "; ".join(
            f"{ids(other)}, last heard {clocked(self.heard(other, items))}"
            for other in others
        )
        return [
            (
                f"`{wanted}` names {len(others) + 1} conversations; this reads the "
                f"one last heard, {ids(found)}, at "
                f"{clocked(self.heard(found, items))}. The others, which "
                f"`{self.spelling.conversation}` reads by id: {each}."
            )
        ]

    def called(self, party: Party) -> str:
        """Name a party for the reader: "you" for the reader, else as lup calls them (`Roster.who`): the operator, or a conversation by their name, with their runtime's ids where another shares it or they have none."""
        if party == self.reader:
            return "you"
        return self.roster.who(party)

    def wrote(self, writer: Writer) -> str:
        """Name who wrote a record for the reader: lup, or a party as `called` names them."""
        match writer:
            case Lup():
                return "lup"
            case _:
                return self.called(writer)

    def attributed(self, party: Conversation) -> str:
        """Name a conversation as a tag's attribute says it (`Roster.called`)."""
        return self.roster.called(party)

    def conversations(self, items: list[Item]) -> list[Conversation]:
        """Return each conversation `items` are from, to or for, and each whose whereabouts the inbox keeps among them, once each."""
        parties = [
            each
            for item in items
            for each in [item.sender, item.recipient, item.addressed]
            if isinstance(each, Conversation)
        ]
        repositories = list(dict.fromkeys(each.repository for each in parties))
        placed = [
            place.conversation
            for place in self.delivery.inbox.whereabouts.values()
            if place.conversation.repository in repositories
        ]
        return list(dict.fromkeys([*parties, *placed]))

    def matching(self, wanted: str, items: list[Item]) -> list[Conversation]:
        """Return the conversations `wanted` names, the one last heard first: by their path or their own name, or by the runtime's id for them, or the id's start."""

        def named(conversation: Conversation) -> bool:
            own = (
                conversation.session
                if conversation.agent is None
                else conversation.agent
            )
            return wanted in [
                self.roster.path(conversation),
                self.roster.own(conversation),
            ] or own.startswith(wanted)

        found = [each for each in self.conversations(items) if named(each)]
        return sorted(found, key=lambda each: self.heard(each, items), reverse=True)

    def below(
        self, conversation: Conversation, items: list[Item]
    ) -> list[Conversation]:
        """Return the subagents below `conversation` among those of `items`: for a session's own, every subagent of their session; for a subagent, each they spawned, and theirs."""
        known = self.conversations(items)
        if conversation.agent is None:
            return [
                each
                for each in known
                if each.agent is not None and each.main() == conversation
            ]
        children = [each for each in known if self.roster.parent(each) == conversation]
        return [
            found for child in children for found in [child, *self.below(child, items)]
        ]

    def heard(self, conversation: Conversation, items: list[Item]) -> datetime:
        """Return when `conversation` was last heard of: their latest item, or when their whereabouts were first kept where they have none."""
        made = [
            item.made
            for item in items
            if conversation in [item.sender, item.recipient, item.addressed]
        ]
        place = self.delivery.inbox.whereabouts.get(conversation.key())
        since = [] if place is None else [place.since]
        return max([*made, *since])


def stood(standing: Standing) -> str:
    """Say where a thread stands, in a few words: its state, what a parked one waits for or what to try on one done, and what in it waits on the operator, counted by what each is.

    >>> stood(Standing(state="working"))
    'working'
    """

    def named(member: Member) -> str:
        match member.node:
            case Check():
                return "check"
            case ItemNode() as node if member.part is None:
                return kind(node.item(Waiting()))
            case _:
                return "part of the operator's words"

    match standing.status:
        case Parked(until=until):
            state = f"parked until {triggers(until)}"
        case ledger.Done(to_try=to_try):
            state = f"done to confirm, to try: {cue(to_try)}"
        case _:
            state = standing.state
    kinds = [named(each) for each in standing.waiting]
    counted = ", ".join(many(kinds.count(each), each) for each in dict.fromkeys(kinds))
    if not kinds:
        return state
    if standing.state == "waiting on the operator":
        return f"{state}: {counted}"
    return f"{state}; waiting on the operator: {counted}"


def made_of(member: Member) -> datetime:
    """Return when what's in a thread was made: an item when it was made, any other node when its version was written."""
    match member.node:
        case ItemNode(made=made):
            return made
        case node:
            return node.at


def cited_at(item: Item) -> str:
    """Say an item's number as it's cited, and when it was made."""
    return f"@{item.number}  {clocked(item.made)}"
