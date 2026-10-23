"""Reading the inbox a line an item, or each whole, narrowed to one conversation's exchange where asked: the agents' `inbox` tool and `lup-dev inbox` read it alike.

`docs/inbox.md`, *Reading an exchange*. What's listed is narrowed as every list
lup answers is (`lup_dev.listing`: when each was made, the latest up to a limit,
what's left out said with what reads it), and further:
- **one conversation's exchange** (`conversation`): the items it sent and was
  sent, and with `subagents` those of each subagent below it. It's named by its
  path (`flow-review/explore-auth`), its own name, or its runtime's id or the
  id's start (`Reader.matching`). A session's name is its launch's as lup last
  kept it (`SessionNames`), a subagent's as its whereabouts last heard it, or,
  from before they kept it, as its end was told to its parent. Names repeat
  over time, a branch's above all, so a name several conversations had reads
  the one last heard, and the answer names the others by id;
- **the kinds** of item (`kinds`), as a tag's `kind` names them;
- **whole** (`whole`): each item as its sender wrote it, or as it was told to
  whom it was for. The operator's words on a conversation's item are told under
  it, each with the conversation's replies to them, so an exchange reads as one
  thread, and their item says so where it's listed too; a review's context, the
  operator's words to others, is left out.

Waiting items alone are listed unless `every` is asked, and what that leaves out
is counted too, with the parameter that reads it.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import Field, PositiveInt

from lup.types import Model
from lup_dev.inbox.delivery import (
    Delivery,
    ItemKind,
    clocked,
    kind,
    opening,
    remarked,
    standing,
    what,
    who,
    written,
)
from lup_dev.inbox.parts import PartId
from lup_dev.inbox.store import (
    Answer,
    Conversation,
    Ended,
    Item,
    Message,
    Operator,
    Party,
    Review,
    Waiting,
)
from lup_dev.inbox.tags import Tag
from lup_dev.inbox.threads import Anchor, addressed_to, anchors
from lup_dev.listing import Span, latest, many, unlisted

if TYPE_CHECKING:
    from datetime import datetime


type Naming = Literal["ids", "paths", "paths and ids"]
"""How a reading names conversations: by their runtime's ids alone, as `inbox`
lists every party's items; by their paths, under a heading saying the ids of
the one whose exchange is read; or by both, as the operator's own exchange is
listed, where names repeat over time."""


class Narrowing(Span):
    """What of the inbox to list, and how: when each was made, whose, of what kinds, in what state, how many, and whether each whole."""

    conversation: str | None = Field(
        default=None,
        description=(
            "Only one conversation's exchange: the items it sent and was sent. A "
            "session by its name (`flow-review`), a subagent by its path "
            "(`flow-review/explore-auth`) or its own name, or either by its "
            "runtime's id or the id's start. Where a name was several "
            "conversations', the one last heard is read, and the answer names "
            "the others by id. Left out, every conversation's."
        ),
    )
    subagents: bool = Field(
        default=False,
        description=(
            "With `conversation`, its subagents' items too, and theirs' below "
            "them; left out, its own alone."
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
            "conversation's item come under it, each with the conversation's "
            "replies to them, so an exchange reads as one thread; a review's "
            "words to other agents are left out."
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


class Reader(Model, arbitrary_types_allowed=True):
    """The inbox as one party reads it, the agent's conversation or the operator: what's listed, and how each party is named to them."""

    delivery: Delivery
    reader: Party
    """Who reads, named "you" where an item is theirs."""
    names: dict[str, str]
    """Each session's name, by its runtime's id for it: its launch's, as lup
    last kept it (`Names.all`)."""
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

    def read(self, items: list[Item], wanted: Narrowing) -> Read:
        """Return `items`, oldest first, as `wanted` narrows them: a line each, or each whole, then what was left out and what reads it."""
        conversation = wanted.conversation
        readable = [
            item
            for item in items
            if not self.mine or self.reader in [item.sender, item.recipient]
        ]
        if conversation is None:
            return self.listed(readable, items, wanted, None)
        matched = self.matching(conversation, items)
        if not matched:
            return Read(
                text=(
                    f"No conversation{self.where} is `{conversation}`: "
                    f"`{self.spelling.conversation}` takes a session's name, a "
                    "subagent's path or its own name, or the runtime's id for "
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
                self.heading(found, below, wanted, items),
            ]
        )
        return self.listed(pool, items, wanted, heading)

    def listed(
        self,
        pool: list[Item],
        items: list[Item],
        wanted: Narrowing,
        heading: str | None,
    ) -> Read:
        """Return the items of `pool` that `wanted` narrows to, under `heading` where one names the exchange: a line each or each whole, then what was left out; `items` are those the reader may read, which name its conversations."""
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
        shown = latest(chosen, lambda item: item.made, wanted.most())
        naming: Naming = (
            "paths" if heading is not None else "paths and ids" if self.mine else "ids"
        )
        if wanted.whole:
            placed = [item.number for item in shown]
            said = "\n\n".join(
                self.whole(item, placed, items, naming=naming) for item in shown
            )
        else:
            said = "\n".join(self.line(item, items, naming=naming) for item in shown)
        left = unlisted(
            len(chosen) - len(shown),
            "earlier item",
            shown[0].made,
            len(chosen),
            until=self.spelling.until,
            limit=self.spelling.limit,
        )
        gap = [""] if wanted.whole and (left or settled) else []
        return Read(
            text="\n".join([*head, said, *gap, *left, *settled]), found=len(chosen)
        )

    def waits(self, item: Item) -> bool:
        """Say whether `item` still waits, as the reader lists what waits: for them alone, where they read their own exchange; else for whomever it's for."""
        waiting = isinstance(item.state, Waiting)
        return waiting and (not self.mine or item.recipient == self.reader)

    def line(self, item: Item, items: list[Item], *, naming: Naming) -> str:
        """Say an item in a line: its number, when it was made, what it is, from whom to whom, where it stands, and its first line."""
        return f"{self.headed(item, items, naming=naming)}: {opening(item)}"

    def headed(self, item: Item, items: list[Item], *, naming: Naming) -> str:
        """Say an item's heading: its number, when it was made, what it is, from whom to whom, and where it stands; each conversation as `naming` says."""
        return (
            f"{cited_at(item)}  {what(item)} from "
            f"{self.called(item.sender, items, naming=naming)} to "
            f"{self.called(item.recipient, items, naming=naming)}, {standing(item)}"
        )

    def whole(
        self, item: Item, placed: list[int], items: list[Item], *, naming: Naming
    ) -> str:
        """Say an item whole under its heading: a conversation's as it wrote it, the operator's words on it and its replies to them under it; any other's as it was told to whom it was for, what it says on the items `placed` told under them, and a review's context left out."""
        heading = self.headed(item, items, naming=naming)
        match item.sender:
            case Conversation() as sender:
                tag = Tag(
                    name="item",
                    attributes={
                        "item": str(item.number),
                        "kind": kind(item),
                        "from": self.attributed(sender, items, naming=naming),
                    },
                    parts=[
                        written(item),
                        *self.thread(item, sender, items, naming=naming),
                    ],
                )
            case Operator():
                tag = self.delivery.tagged(item, under=placed, context=False)
        return f"{heading}:\n{tag.written()}"

    def thread(
        self, item: Item, sender: Conversation, items: list[Item], *, naming: Naming
    ) -> list[Tag | str]:
        """Return the operator's words on `item`, `sender`'s, in the order they came: under each of their items addressed to `sender` that's on it, what it says there, then each reply `sender` made to it."""
        inbox = self.delivery.inbox
        ordered = [inbox.items[number] for number in sorted(inbox.items)]
        return [
            self.said_on(each, item, sender, on, items, naming=naming)
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
        items: list[Item],
        *,
        naming: Naming,
    ) -> Tag:
        """Tag what the operator's item `theirs` says on `item`, its parts `on`, as it told them to `sender`, each with its id; then each of `sender`'s replies to them."""
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
        ids = [anchor.id for anchor in on]
        replies = [
            Tag(
                name="reply",
                attributes={
                    "id": PartId(item=theirs.number, part=reply.number).said(),
                    "to": reply.to.said(),
                    "from": self.attributed(sender, items, naming=naming),
                },
                parts=[reply.text],
            )
            for reply in theirs.replies
            if reply.to in ids
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
        items: list[Item],
    ) -> str:
        """Say whose exchange is read, the conversation by its path and its runtime's ids, and what of it."""
        subagents = f" and its {many(len(below), 'subagent')}" if below else ""
        state = "every item" if wanted.every else "what still waits"
        window = wanted.window(self.delivery.clock.now()).said()
        return f"The exchange of {self.titled(found, items)}{subagents}: {state}{window}, oldest first."

    def titled(self, conversation: Conversation, items: list[Item]) -> str:
        """Name a conversation by its path, where lup knows it, then by its runtime's ids."""
        path = self.path(conversation, items)
        return who(conversation) if path is None else f"`{path}` ({who(conversation)})"

    def alike(
        self,
        wanted: str,
        found: Conversation,
        others: list[Conversation],
        items: list[Item],
    ) -> list[str]:
        """Say, first, that `wanted` names several conversations: that this reads `found`, the one last heard, and the others, each by its runtime's ids and when it was last heard, which `conversation` reads by id; nothing where it names one.

        Said before what's read, since a reader who never reaches an answer's
        last line would take one session for another.
        """
        if not others:
            return []
        each = "; ".join(
            f"{who(other)}, last heard {clocked(self.heard(other, items))}"
            for other in others
        )
        return [
            (
                f"`{wanted}` names {len(others) + 1} conversations; this reads the "
                f"one last heard, {who(found)}, at "
                f"{clocked(self.heard(found, items))}. The others, which "
                f"`{self.spelling.conversation}` reads by id: {each}."
            )
        ]

    def called(self, party: Party, items: list[Item], *, naming: Naming) -> str:
        """Name a party for the reader: "you" for the reader, the operator, or a conversation as `naming` says, by its runtime's ids where lup knows no path for it."""
        if party == self.reader:
            return "you"
        match party:
            case Operator():
                return "the operator"
            case Conversation():
                path = None if naming == "ids" else self.path(party, items)
                if path is None:
                    return who(party)
                if naming == "paths":
                    return f"`{path}`"
                return f"`{path}` ({who(party)})"

    def attributed(
        self, party: Conversation, items: list[Item], *, naming: Naming
    ) -> str:
        """Name a conversation as a tag's attribute says it: by its path where `naming` names paths and lup knows it, else by its runtime's ids, which the item's heading says."""
        path = None if naming == "ids" else self.path(party, items)
        return who(party) if path is None else path

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
        """Return the conversations `wanted` names, the one last heard first: by its path or its own name, or by the runtime's id for it, or the id's start."""

        def named(conversation: Conversation) -> bool:
            own = (
                conversation.session
                if conversation.agent is None
                else conversation.agent
            )
            return wanted in [
                self.path(conversation, items),
                self.own(conversation, items),
            ] or own.startswith(wanted)

        found = [each for each in self.conversations(items) if named(each)]
        return sorted(found, key=lambda each: self.heard(each, items), reverse=True)

    def below(
        self, conversation: Conversation, items: list[Item]
    ) -> list[Conversation]:
        """Return the subagents below `conversation` among those of `items`: for a session's own, every subagent of its session; for a subagent, each it spawned, and theirs."""
        known = self.conversations(items)
        if conversation.agent is None:
            return [
                each
                for each in known
                if each.agent is not None and each.main() == conversation
            ]
        children = [each for each in known if self.parent(each) == conversation]
        return [
            found for child in children for found in [child, *self.below(child, items)]
        ]

    def heard(self, conversation: Conversation, items: list[Item]) -> datetime:
        """Return when `conversation` was last heard of: its latest item, or when its whereabouts were first kept where it has none."""
        made = [
            item.made
            for item in items
            if conversation in [item.sender, item.recipient, item.addressed]
        ]
        place = self.delivery.inbox.whereabouts.get(conversation.key())
        since = [] if place is None else [place.since]
        return max([*made, *since])

    def parent(self, conversation: Conversation) -> Conversation | None:
        """Return the conversation that spawned a subagent, as its whereabouts keep it; none for a session's own, or one whose parent isn't known."""
        place = self.delivery.inbox.whereabouts.get(conversation.key())
        return None if place is None else place.parent

    def own(self, conversation: Conversation, items: list[Item]) -> str | None:
        """Return a conversation's own name: a session's as lup last kept it; a subagent's as its whereabouts last heard it, or else as its end was told; none where lup knows none."""
        if conversation.agent is None:
            return self.names.get(conversation.session)
        place = self.delivery.inbox.whereabouts.get(conversation.key())
        if place is not None and place.name is not None:
            return place.name
        ended = [
            item.reason.name
            for item in items
            if item.sender == conversation and isinstance(item.reason, Ended)
        ]
        return ended[-1] if ended else None

    def path(
        self, conversation: Conversation, items: list[Item], depth: int = 0
    ) -> str | None:
        """Return a conversation's path as lup's commands call it: its session's name, then each subagent's name down to it, an unnamed one by its runtime's id; none where its session's name isn't known."""
        if conversation.agent is None:
            return self.own(conversation, items)
        above = self.parent(conversation) or conversation.main()
        if depth > len(self.delivery.inbox.whereabouts):
            return None
        root = self.path(above, items, depth + 1)
        if root is None:
            return None
        return f"{root}/{self.own(conversation, items) or conversation.agent}"


def cited_at(item: Item) -> str:
    """Say an item's number as it's cited, and when it was made."""
    return f"@{item.number}  {clocked(item.made)}"
