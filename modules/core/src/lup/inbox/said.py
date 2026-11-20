"""What a party says or does through the inbox's doors: each tool's, service's and command's model.

An agent's tool takes what they say (`ConcernSaid`, `SendSaid`…), which their
project's part hands `Inboxes` as `Spoken`, with who they are; the
operator's commands take what they do (`Answering`, `Clearing`…).
"""

from typing import Annotated, Literal

from annotated_types import Ge, Lt
from pydantic import BaseModel, JsonValue

from lup.doors.parties import Agent, Party
from lup.inbox.records import FRICTIONS, Decision, Item, Ruling, Tone
from lup.types import Model

type Cited = Annotated[int, Ge(1), Lt(2**63)]
"""A number something is cited by, `@12`: from 1, and within what the store keeps a number as. Its bounds are annotated-types', which pydantic checks and hypothesis draws within, wherever the number sits."""

# What agents say


class Spoken[S: Model](Model):
    """What an agent said through one of their tools, for `Inboxes` to keep: the agent, as the doors handed them to the tool, and what they said."""

    agent: Agent
    said: S


class ConcernSaid(Model):
    """What an agent says of a concern: one to open, or one there already."""

    name: str | None = None
    """The concern: an existing one's name or number, or a name for one opened. Left out, what's opened is named after its title."""
    text: str | None = None
    """Their words: with no `name`, or a `name` that isn't there, they open a concern; with one there, they go into it."""
    title: str = ""
    """A few words naming a concern opened. Left out, the first line of `text`."""
    under: str | None = None
    """Where one opened goes: a party by its name, or a concern. Left out, the concern they work in, else themselves."""
    body: str | None = None
    """Its body, rewritten whole: what they understand of it."""
    join: bool = False
    """Work in it from now on: what they say without naming another lands there."""
    hold: bool = False
    """Take it, and work in it."""
    hand: str | None = None
    """Pass it on to another agent, by their name: it's theirs after."""
    move: list[Cited] = []
    """Items to put in it, by their numbers."""
    done: str | None = None
    """Say it's done, for the operator to clear: what's done, what isn't, and what to try."""


class FrictionSaid(Model):
    """What got in an agent's way, at the moment it did, in their own words."""

    text: str
    title: str = ""
    """A few words naming it. Left out, its first line."""
    under: str = FRICTIONS
    """Where it goes: a pile by its path, made where it isn't there yet, or an agent by their name."""
    repository: str | None = None
    """Another repository it goes to, by the name lup knows it by, as a friction about lup met in a project's session goes to lup's. Left out, the agent's own."""


class NoteSaid(Model):
    """An assumption, a doubt or a counterargument for the operator to weigh."""

    remark: str
    thread: str | None = None
    """The concern it lands in. Left out, the one they work in."""


class SendSaid(Model):
    """A message of a tone to a party: the operator, an agent, or a pile, where it opens a concern."""

    to: str
    """The party, by its name: `operator`, an agent's name, or a pile's path."""
    repository: str | None = None
    """Another repository the party is of, by the name lup knows it by. Left out, the agent's own."""
    tone: Tone = "note"
    text: str
    thread: str | None = None
    """The concern it lands in. Left out, the one they work in."""


class AskSaid(Model):
    """A question for the operator, with numbered decisions, each with the asker's lean."""

    question: str
    decisions: list[Decision] = []
    thread: str | None = None
    """The concern it lands in. Left out, the one they work in."""


class Words(Model):
    """An agent's words, whole: how it felt, why the work can't go on, why they stop."""

    text: str


class WithdrawSaid(Model):
    """An item an agent sent the operator, taken back, and why."""

    item: Cited
    why: str


class Reading(Model):
    """What of the inbox to read: one item or concern whole, by its number, or what stands."""

    number: Cited | None = None


type Spoke = Literal["how it felt", "blocked", "stop", "turn's end"]
"""Which of an agent's own words, kept whole, `Inboxes.spoke` keeps."""


class Uttered(Model):
    """An agent's words of one kind: how it felt, a block, a stop, or a turn's end."""

    kind: Spoke
    text: str


# What the operator does


class Answering(Model):
    """The operator's answer to a question: a ruling on each decision, and their words."""

    question: Cited
    rulings: list[Ruling] = []
    text: str = ""


class Pile(Party):
    """A pile, as a party a comment reaches: it keeps what's sent to it, as a concern."""

    party: Literal["pile"] = "pile"
    """Which party it is, as a call across containers names it."""
    repository: str
    path: str


class OnItem(Model):
    """What an item's block gives the comment it offers: the item, by its number, and the part of it, where the block is one."""

    item: Cited
    part: int | None = None


class Reached(Model):
    """The party a block's comment reaches, where the block offers no comment of its own: an agent, or a pile, which keeps it."""

    party: Agent | Pile


class Addressing(Model):
    """The operator's words to a party of a repository: an agent, or a pile, where they open a concern."""

    repository: str
    to: str
    text: str


class Clearing(Model):
    """What the operator clears: an item or a concern by its number, or a party's buffer by its name."""

    repository: str
    what: str


class Declining(Model):
    """A concern the operator declines, and why."""

    concern: Cited
    why: str = ""


class Piling(Model):
    """A pile the operator makes, by its path."""

    repository: str
    path: str


class Naming(Model):
    """An agent of a repository named, as their session says its name, under the agent who spawned them where one did."""

    repository: str
    agent: Agent
    name: str
    spawner: Agent | None = None


class Ending(Model):
    """An agent of a repository: one whose session ended or started again, or who's told what's for them."""

    repository: str
    agent: Agent


class Ended(Model):
    """An agent's last words of a turn, in a repository."""

    repository: str
    agent: Agent
    text: str


class Untelling(Model):
    """A repository whose agents to list, by what's untold for them."""

    repository: str


class Untold(Model):
    """Each agent with something for them not yet told them: whom a session wakes, or starts again."""

    agents: list[Agent] = []


# What modules say, in their own kinds of item


class Posting(Model):
    """An item of a module's own kind, said by an agent to the operator in the concern the agent works in: a branch that waits on the operator's review, as a landing says it."""

    by: Agent
    """The agent it's said by, in whose conversation it shows: the one whose
    call it came from."""
    repository: str
    """The repository whose inbox keeps it."""
    kind: str
    """Its kind, one a module declares in its `Recorded`, never the inbox's
    own."""
    text: str
    """Its words, as the operator reads them above what its kind lays out."""
    fields: dict[str, JsonValue] = {}
    """Its kind's own fields, as JSON; who it's by and for, when, and its
    number are the inbox's to say."""

    @classmethod
    def of(
        cls,
        kind: type[Item],
        said: BaseModel | None = None,
        *,
        by: Agent,
        repository: str,
        text: str,
    ) -> Posting:
        """Return an item of `kind`, its own fields `said`'s, said by `by` in `repository`'s inbox in `text`."""
        return cls(
            by=by,
            repository=repository,
            kind=kind.declared() or "",
            text=text,
            fields={} if said is None else said.model_dump(mode="json"),
        )


class Posted(Model):
    """The number an item of a module's own kind is kept under: what the module settles it by."""

    number: Cited


class Settling(Model):
    """What came of an item of a module's own kind, said for the operator's act: told to whoever wrote it, and answering it, so it waits no more."""

    repository: str
    item: Cited
    """The item, by its number."""
    text: str
    """What came of it, in words: `on trial at 4f2a1c0`, or the operator's own."""


# What stands, as data


class Nothing(Model):
    """Nothing: what reading what stands takes."""


class Placed(Model):
    """Where one concern stands, as data."""

    number: int
    name: str | None
    title: str
    kind: str
    """Its kind: `inbox:concern`, or `inbox:friction`."""
    holder: str
    """Who holds it, as `@` cites them: `@frictions`, `@no-agent`, an agent's name."""
    left_by: str | None = None
    """The ended agent who held it, as `@` cites them, where it reads as in `no-agent`."""
    said: int = 0
    """How many items are in it."""
    done: bool = False
    cleared: bool = False
    declined: bool = False


class Telling(Model):
    """How many times one item was told to one party."""

    item: int
    party: str
    times: int


class Comments(Model):
    """One of the operator's comments, and how many parties it reaches."""

    item: int
    reaches: int


class Inboxed(Model):
    """A repository's inbox, as data: where each concern stands, what waits on the operator, what's new to them, what's been told, and the operator's comments."""

    repository: str
    concerns: list[Placed] = []
    waiting: list[int] = []
    """The numbers of what waits on the operator."""
    new: list[int] = []
    """The numbers of what's new to the operator."""
    told: list[Telling] = []
    comments: list[Comments] = []


class ToldItem(Model):
    """One item told to an agent."""

    number: int
    by: str | None
    kind: str
    text: str


class Told(Model):
    """What's told to an agent: each item for them not told before this, by its number, who wrote it, and its words."""

    items: list[ToldItem] = []


class Everywhere(Model):
    """Every repository's inbox the store holds, as data."""

    inboxes: list[Inboxed] = []


# What the operator reads


class PartiesOf(Model):
    """A repository whose parties to show."""

    repository: str


class PartyOf(Model):
    """A party whose buffer to show: a repository's, by its name, as `@` cites it."""

    repository: str
    name: str


class ConcernOf(Model):
    """A concern to show, by its number."""

    number: Cited


class Showing(Model):
    """What's been on the operator's screen, by their numbers: each isn't new to them after."""

    items: list[Cited]
