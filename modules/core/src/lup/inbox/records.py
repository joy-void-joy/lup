"""What the inbox keeps in the store: parties, concerns, items, and the edges between them.

Every party is a node, named and never numbered, so making one never moves the
numbers the operator reads: the operator, each agent, each pile. Concerns and
items are numbered, cited `@12`. Where each is, what it answers and what's been
done with it are edges, so where something stands is read from them, never
stored (`README.md` here, *What's kept*).
"""

from typing import ClassVar, Literal

from lup.store.records import Edge, Kinds, Name, Node
from lup.types import Model

# Parties


class Party(Node):
    """Someone or something that holds concerns and is sent to: the operator, an agent, or a pile.

    Named, its name unique in its repository and what `@` takes; never numbered.
    Where it sits among the repository's parties is an `Under` edge from it.
    """

    kind: str = "inbox:party"


class OperatorParty(Party):
    """The operator, as a party of a repository: whom what asks them is for."""

    kind: str = "inbox:operator"
    name: Name | None = "operator"


class AgentParty(Party):
    """An agent: a session's own conversation, or one they spawned or started as a subagent.

    Known to lup's doors by `id` (`lup.Agent.id`), which stays put as they're
    renamed; named by their path, `port-plan/promise-door`. Whether they've
    ended is an `Ended` edge said of them, never a field.
    """

    kind: str = "inbox:agent"
    id: str
    """lup's id for the agent, which the doors hand a method as `by: Agent`."""


class Pile(Party):
    """A party that holds concerns and does nothing else: made by the operator as they think, or by a friction sent to a path not there yet."""

    kind: str = "inbox:pile"


# Concerns


class Concern(Node):
    """Something to keep an eye on: a feature to build, a problem met, a direction to think about.

    Held by one party, or under another concern, by an `Under` edge from it,
    the latest drawn saying where it is. Its body is what whoever answers for
    it understands of it, rewritten whole as a later version.
    """

    kind: str = "inbox:concern"
    numbered: ClassVar[bool] = True
    title: str
    """A few words naming it, which the list of parties shows."""
    body: str = ""
    """What whoever answers for it understands of it, rewritten whole."""


class Friction(Concern):
    """What got in an agent's way, in their own words: feedback, held as a concern is, and shown as a friction."""

    kind: str = "inbox:friction"


# Items


class Item(Node):
    """One thing a party said, to one or more others: numbered, kept whole, never cut.

    Who it's from is `by`; who it's for is `to`, by their keys. Whether it
    waits on whom it's for until they answer is its kind's (`waits`).
    """

    kind: str = "inbox:item"
    numbered: ClassVar[bool] = True
    to: list[int]
    """The keys of the parties it's for."""
    text: str
    """What was said, as written: Markdown, its blocks its parts, cited `@12.3`."""

    def waits(self) -> bool:
        """Say whether it waits on whom it's for until they answer it. The base never waits."""
        return False


type Tone = Literal["note", "problem", "disagreement", "question"]
"""What a message is: news, or one of the three that want their reader's answer."""


class Message(Item):
    """A message of a tone, from one party to others: what `send` and `note` say, and a party's words in a concern."""

    kind: str = "inbox:message"
    tone: Tone = "note"

    def waits(self) -> bool:
        """Say whether it wants its reader's answer: a problem, a disagreement or a question does, a note is news."""
        return self.tone != "note"


class Decision(Model):
    """One decision a question asks, with the asker's lean."""

    decision: str
    lean: str


class Question(Item):
    """A question for the operator, with numbered decisions, each with the asker's lean, or answered in words."""

    kind: str = "inbox:question"
    decisions: list[Decision] = []

    def waits(self) -> bool:
        """Say that a question waits until it's answered."""
        return True


type Verdict = Literal["leaning", "undecided", "leave open"]
"""What the operator says to one decision: go with the lean, not yet, or leave it open."""


class Ruling(Model):
    """The operator's word on one decision of a question, by its number from 1."""

    number: int
    verdict: Verdict | None = None
    comment: str = ""


class Answer(Item):
    """The operator's answer to a question: a ruling on each decision, and their words."""

    kind: str = "inbox:answer"
    rulings: list[Ruling] = []


class Felt(Item):
    """How it is for an agent, in their own words: for the operator, news."""

    kind: str = "inbox:how-it-felt"


class Blocked(Item):
    """An agent's word that the work can't go on, and what's wrong: it waits on the operator."""

    kind: str = "inbox:blocked"

    def waits(self) -> bool:
        """Say that a block waits until the operator answers it."""
        return True


class Stopped(Item):
    """An agent's word that they ended their work by their own choice, and why: news."""

    kind: str = "inbox:stop"


class TurnEnd(Item):
    """An agent's last words of a turn: their answer to what the operator said since their last turn's end."""

    kind: str = "inbox:turn-end"


class Comment(Item):
    """The operator's words on something said, or on a part of it, or to a party: what a reply is made of.

    One on an item reaches whoever wrote it, and each party it was for where
    an agent wrote it to another; one to a party alone reaches that party.
    """

    kind: str = "inbox:comment"
    on: int | None = None
    """The key of the item it's on; none for words to a party alone."""
    part: int | None = None
    """The part of that item it's on, from 1; none for the item whole."""
    quote: str = ""
    """The passage it's on, as the operator selected it."""


# Edges


class Under(Edge):
    """Where a concern or a party is: held by a party, or under a concern or another party. The latest drawn from a node is where it is."""

    kind: str = "inbox:under"

    def replaces(self, earlier: Edge) -> bool:
        """Say that a later place takes the earlier one's: a node is in one place."""
        return isinstance(earlier, Under)


class In(Edge):
    """An item said in a concern: where it was said, or moved to. The latest drawn from an item is where it is."""

    kind: str = "inbox:in"

    def replaces(self, earlier: Edge) -> bool:
        """Say that a later concern takes the earlier one's: an item is in one concern."""
        return isinstance(earlier, In)


class WorksIn(Edge):
    """The concern an agent works in, from the agent: where what they say lands, until they work in another."""

    kind: str = "inbox:works-in"

    def replaces(self, earlier: Edge) -> bool:
        """Say that working in a concern ends working in the one before."""
        return isinstance(earlier, WorksIn)


class Answers(Edge):
    """An item answering another, or a part of it: a reply, an answer, a turn's end answering what was told since the last."""

    kind: str = "inbox:answers"
    part: int | None = None
    """The part answered, from 1; none for the item whole."""


class Told(Edge):
    """An item told to a party, from the party: told once, never again."""

    kind: str = "inbox:told"


class Shown(Edge):
    """Something that's been on the operator's screen, said of it: it isn't new to them after it."""

    kind: str = "inbox:shown"


class Cleared(Edge):
    """The operator clearing something, said of it: an item, a concern, or a party's buffer whole. It stays cleared until something new happens in it."""

    kind: str = "inbox:cleared"
    newest: int = 0
    """The key of the newest item in what it cleared, as it was cleared: an item newer than it brings what it cleared back."""


class Declined(Edge):
    """The operator declining a concern, said of it, and why: nothing more will be done about it."""

    kind: str = "inbox:declined"
    why: str = ""


class Done(Edge):
    """An agent saying a concern is done, from the agent: what's done, what isn't, and what to try, for the operator to clear."""

    kind: str = "inbox:done"
    said: str
    newest: int = 0
    """The key of the newest item in the concern as they said it: an item newer than it says the concern isn't done after all."""


class Withdrawn(Edge):
    """An agent taking back what they sent the operator, said of it, and why: it waits on nobody after it."""

    kind: str = "inbox:withdrawn"
    why: str


class Ended(Edge):
    """An agent's session ending, said of the agent: what they held reads as in `No agent`, each saying who left it, until they start again."""

    kind: str = "inbox:ended"


class Started(Edge):
    """An agent starting again after they ended, said of the agent: what they held is theirs again."""

    kind: str = "inbox:started"


NODES: list[type[Node]] = [
    Party,
    OperatorParty,
    AgentParty,
    Pile,
    Concern,
    Friction,
    Item,
    Message,
    Question,
    Answer,
    Felt,
    Blocked,
    Stopped,
    TurnEnd,
    Comment,
]
"""The inbox's kinds of node."""

EDGES: list[type[Edge]] = [
    Under,
    In,
    WorksIn,
    Answers,
    Told,
    Shown,
    Cleared,
    Declined,
    Done,
    Withdrawn,
    Ended,
    Started,
]
"""The inbox's kinds of edge."""

KINDS = Kinds(nodes=NODES, edges=EDGES)
"""The classes the store reads the inbox's records as."""
