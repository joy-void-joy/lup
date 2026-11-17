"""What a party says or does through the inbox's doors: each tool's, service's and command's model.

An agent's tool takes what they say (`ConcernSaid`, `SendSaid`…), which their
project's part hands `Inboxes` as `Spoken`, with lup's id for them; the
operator's commands take what they do (`Answering`, `Clearing`…).
"""

from typing import Annotated, Literal

from annotated_types import Ge, Lt

from lup.doors.parties import Party
from lup.inbox.records import FRICTIONS, Decision, Ruling, Tone
from lup.types import Model

type Cited = Annotated[int, Ge(1), Lt(2**63)]
"""A number something is cited by, `@12`: from 1, and within what the store keeps a number as. Its bounds are annotated-types', which pydantic checks and hypothesis draws within, wherever the number sits."""

# What agents say


class Spoken[S: Model](Model):
    """What an agent said through one of their tools, for `Inboxes` to keep: the agent, by lup's id for them, and what they said."""

    agent: str
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


class Commenting(Model):
    """The operator's words on an item, or a part of it."""

    item: Cited
    text: str
    part: int | None = None
    quote: str = ""


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
    """An agent named, as their session says its name, under the agent who spawned them where one did, each by lup's id for them."""

    agent: str
    name: str
    spawner: str | None = None


class Ending(Model):
    """An agent whose session ended, or started again, by lup's id for them."""

    agent: str


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


class Pile(Party):
    """A pile, as a party a comment reaches: it keeps what's sent to it, as a concern."""

    party: Literal["pile"] = "pile"
    """Which party it is, as a call across containers names it."""
    repository: str
    path: str
