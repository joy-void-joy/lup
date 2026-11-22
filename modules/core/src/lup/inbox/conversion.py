"""Bringing a repository's frictions and concerns over from the second lup's ledger into its inbox here, once, at the switch (#13).

The second lup kept the words of both tools, `concern` and `friction`, as one
kind of item, so a concern read as a friction on the operator's dashboard.
Each of its threads is sorted here by the tool its first words were filed
with: a friction goes to `frictions`, for triage to group; a concern keeps
its title, every body it had, its done mark, and its place: under the agent
holding it, else under the concern it was under, else in `no-agent`. Each
keeps the words filed in it with either tool, as the operator was told them,
each by whoever wrote it and when. The notes agents sent into a thread, and
everything else of the ledger, stay there (`README.md` here, *The second
lup's ledger*).
"""

from functools import cache
from typing import Literal
from urllib.parse import quote
lazy from pathlib import Path

from pydantic import AwareDatetime, ValidationError
from sqlalchemy import (
    Column,
    Connection,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from lup.doors.parties import Agent
from lup.inbox.inbox import Inbox, InboxError
from lup.inbox.records import (
    FRICTIONS,
    NO_AGENT,
    AgentRecord,
    Concern,
    Item,
    PartyRecord,
)
from lup.store.records import named
from lup.types import Model

LEDGER = MetaData()
"""The second lup's ledger, as far as it's read: the columns of each table a conversion reads."""

LEDGER_NODES = Table(
    "nodes",
    LEDGER,
    Column("number", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("repository", Text, nullable=False),
    Column("name", Text),
)
LEDGER_VERSIONS = Table(
    "versions",
    LEDGER,
    Column("version", Integer, primary_key=True),
    Column("number", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("record", Text, nullable=False),
)
LEDGER_EDGES = Table(
    "edges",
    LEDGER,
    Column("drawn", Integer, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("source", Integer),
    Column("target", Integer, nullable=False),
    Column("record", Text, nullable=False),
)
LEDGER_RECORDS = Table(
    "records",
    LEDGER,
    Column("name", Text, primary_key=True),
    Column("record", Text, nullable=False),
)

CONVERTED = "inbox:converted:{repository}"
"""The plain record saying a repository's inbox was brought over, which a second conversion refuses on."""


class ConversionError(InboxError):
    """A conversion can't go on: the ledger doesn't read, or the repository's inbox was brought over already."""


# What the second lup kept


class Conversation(Model):
    """A party of the second lup's that's a conversation: a session's own, or one of its subagents'."""

    party: Literal["conversation"] = "conversation"
    session: str
    """The runtime's id for the session."""
    agent: str | None = None
    """The runtime's id for the subagent, in the session; none for the
    session's own conversation."""

    def caller(self) -> Agent:
        """Return the agent as this lup knows them: by the session's id, and the subagent's in it where they're one."""
        return Agent.of(self.session, self.agent)


class Elsewhere(Model):
    """A party of the second lup's that isn't a conversation: the operator, or lup itself."""

    party: str


type Writer = Conversation | Elsewhere
"""Whoever wrote a record of the second lup's."""


class Thread(Model):
    """A thread of the second lup's, as it stands: what this lup calls a concern."""

    number: int
    name: str | None = None
    title: str
    parent: int | None = None
    """The thread it's under, by its number; none at the top."""
    holder: Writer | None = None
    """Who holds it; none where it's held through the thread it's under."""
    at: AwareDatetime
    """When this version of it was written."""


class Filing(Model):
    """Why an item of the second lup's was made: the tool an agent called, and what they gave it."""

    tool: str
    text: str
    title: str = ""


class Filed(Model):
    """Words filed in a thread with `concern` or `friction`, as the operator was told them."""

    by: Writer
    at: AwareDatetime
    reason: Filing


class Bodied(Model):
    """A thread's body, rewritten whole, by whoever answered for it."""

    by: Writer
    at: AwareDatetime
    text: str


class Marked(Model):
    """A thread's agent saying it's done, and what to try."""

    by: Writer
    at: AwareDatetime
    to_try: str


class Named(Model):
    """What the second lup kept of a conversation: its name, where it was given one, as a subagent's is, and the conversation that spawned it."""

    conversation: Conversation
    name: str | None = None
    parent: Conversation | None = None
    """The conversation that spawned it, a session's or a subagent's; none
    where none did, or the second lup didn't say."""
    since: AwareDatetime
    """When it started."""


class Brought(Model):
    """One thread to bring over: as it stands, when it was opened, and what was filed, written and marked in it, each oldest first."""

    thread: Thread
    opened: AwareDatetime
    words: list[Filed] = []
    bodies: list[Bodied] = []
    marks: list[Marked] = []

    def friction(self) -> bool:
        """Say whether it's a friction: its first words were filed with `friction`."""
        return bool(self.words) and self.words[0].reason.tool == "friction"


class Ledger(Model):
    """A repository's frictions and concerns, as the second lup's ledger holds them: each thread, parents before what's under them, and the names of the subagents who wrote in any."""

    threads: list[Brought]
    names: list[Named] = []

    def named(self, conversation: Conversation) -> Named | None:
        """Return what the second lup kept of `conversation`; none where it kept nothing."""
        return next(
            (each for each in self.names if each.conversation == conversation), None
        )

    def spawner(self, conversation: Conversation) -> Conversation | None:
        """Return the conversation that spawned `conversation`, as the second lup said, where it started before it; else, for a subagent, their session's own; none for a session nothing spawned."""
        named = self.named(conversation)
        parent = None if named is None else named.parent
        before = None if parent is None else self.named(parent)
        if parent is not None and (
            before is None or named is None or before.since < named.since
        ):
            return parent
        if conversation.agent is not None:
            return Conversation(session=conversation.session)
        return None


class Converted(Model):
    """What a conversion brought over: how many of each, kept as the plain record that refuses a second."""

    repository: str
    concerns: int = 0
    frictions: int = 0
    words: int = 0
    bodies: int = 0
    marks: int = 0
    agents: int = 0

    def said(self) -> str:
        """Say what was brought over, as the operator reads it."""
        return (
            f"Brought {self.concerns} concerns and {self.frictions} frictions into "
            f"{self.repository}'s inbox, with {self.words} sets of words, "
            f"{self.bodies} bodies and {self.marks} done marks. The {self.agents} "
            "agents who held or wrote them read as ended, so what they held waits "
            "in `no-agent`, saying who left it, until they start here."
        )


# Reading the ledger


def read(path: Path, repository: str) -> Ledger:
    """Read the frictions and concerns of `repository`, as the ledger at `path` names it, opening the ledger read-only.

    Raise `ConversionError` where there's no file at `path`, or it isn't a
    ledger the second lup wrote, or a record of it doesn't read.
    """
    if not path.is_file():
        message = f"no ledger is at {path}"
        raise ConversionError(message, about=[str(path)])
    engine = create_engine(
        URL.create(
            "sqlite",
            database=f"file:{quote(str(path))}",
            query={"mode": "ro", "uri": "true"},
        )
    )
    try:
        with engine.connect() as connection:
            return ledger(connection, repository)
    except (SQLAlchemyError, ValidationError) as unread:
        message = f"the ledger at {path} doesn't read as the second lup's: {unread}"
        raise ConversionError(message, about=[str(path)]) from unread
    finally:
        engine.dispose()


def ledger(connection: Connection, repository: str) -> Ledger:
    """Read `repository`'s threads from the ledger `connection` reads, with what was filed, written and marked in each."""
    threads = connection.execute(
        select(LEDGER_NODES.c.number, LEDGER_VERSIONS.c.record)
        .join(LEDGER_VERSIONS, LEDGER_VERSIONS.c.version == LEDGER_NODES.c.version)
        .where(
            LEDGER_NODES.c.repository == repository,
            LEDGER_NODES.c.kind == "ledger:thread",
        )
        .order_by(LEDGER_NODES.c.number)
    ).all()
    firsts = (
        select(
            LEDGER_VERSIONS.c.number,
            func.min(LEDGER_VERSIONS.c.version).label("version"),
        )
        .group_by(LEDGER_VERSIONS.c.number)
        .subquery()
    )
    opened = dict(
        connection.execute(
            select(LEDGER_NODES.c.number, LEDGER_VERSIONS.c.record)
            .join(firsts, firsts.c.number == LEDGER_NODES.c.number)
            .join(LEDGER_VERSIONS, LEDGER_VERSIONS.c.version == firsts.c.version)
            .where(
                LEDGER_NODES.c.repository == repository,
                LEDGER_NODES.c.kind == "ledger:thread",
            )
        ).all()
    )
    brought = [
        Brought(
            thread=Thread.model_validate_json(record),
            opened=Thread.model_validate_json(opened[number]).at,
            words=words(connection, number),
            bodies=[
                Bodied.model_validate_json(each)
                for each in drawn(connection, number, "ledger:body")
            ],
            marks=[
                Marked.model_validate_json(each)
                for each in drawn(connection, number, "ledger:done")
            ],
        )
        for number, record in threads
    ]
    written = {
        each.by: each.by
        for thread in brought
        for each in [*thread.words, *thread.bodies, *thread.marks]
        if isinstance(each.by, Conversation)
    }
    holders = {
        thread.thread.holder: thread.thread.holder
        for thread in brought
        if isinstance(thread.thread.holder, Conversation)
    }
    lines = [
        each
        for one in {**written, **holders}.values()
        for each in lineage(connection, one, [])
    ]
    return Ledger(
        threads=parents_first(brought),
        names=list({each.conversation: each for each in lines}.values()),
    )


def lineage(
    connection: Connection, of: Conversation, trail: list[Conversation]
) -> list[Named]:
    """Return what the ledger kept of the conversation `of`, then of each that spawned it in turn, as far as the ledger says, never one twice."""
    named = conversation(connection, of)
    if named is None:
        return []
    parent = named.parent
    if parent is None or parent in trail:
        return [named]
    return [named, *lineage(connection, parent, [*trail, of])]


def words(connection: Connection, thread: int) -> list[Filed]:
    """Return the words filed in `thread` with `concern` or `friction`, as the operator was told them, oldest first: each item whose latest place is `thread`."""
    tool = func.json_extract(LEDGER_VERSIONS.c.record, "$.reason.tool")
    recipient = func.json_extract(LEDGER_VERSIONS.c.record, "$.recipient.party")
    latest = (
        select(LEDGER_EDGES.c.target)
        .where(
            LEDGER_EDGES.c.kind == "ledger:in",
            LEDGER_EDGES.c.source == LEDGER_NODES.c.number,
        )
        .order_by(LEDGER_EDGES.c.drawn.desc())
        .limit(1)
        .scalar_subquery()
    )
    records = connection.execute(
        select(LEDGER_VERSIONS.c.record)
        .join(LEDGER_NODES, LEDGER_NODES.c.version == LEDGER_VERSIONS.c.version)
        .where(
            LEDGER_NODES.c.kind == "inbox:item",
            tool.in_(["concern", "friction"]),
            recipient == "operator",
            latest == thread,
        )
        .order_by(LEDGER_NODES.c.number)
    ).scalars()
    return [Filed.model_validate_json(each) for each in records]


def drawn(connection: Connection, thread: int, kind: str) -> list[str]:
    """Return the record of each edge of `kind` drawn to `thread`, in the order drawn."""
    return list(
        connection.execute(
            select(LEDGER_EDGES.c.record)
            .where(LEDGER_EDGES.c.kind == kind, LEDGER_EDGES.c.target == thread)
            .order_by(LEDGER_EDGES.c.drawn)
        ).scalars()
    )


def conversation(connection: Connection, of: Conversation) -> Named | None:
    """Return what the ledger kept of the conversation `of`; none where it kept nothing."""
    record = connection.execute(
        select(LEDGER_RECORDS.c.record)
        .where(
            LEDGER_RECORDS.c.name.startswith("inbox:conversation:"),
            func.json_extract(LEDGER_RECORDS.c.record, "$.conversation.session")
            == of.session,
            func.json_extract(LEDGER_RECORDS.c.record, "$.conversation.agent")
            == of.agent,
        )
        .limit(1)
    ).scalar_one_or_none()
    return None if record is None else Named.model_validate_json(record)


def parents_first(threads: list[Brought]) -> list[Brought]:
    """Return `threads` ordered so each comes after the thread it's under, otherwise as they were."""
    numbers = {each.thread.number: each for each in threads}
    ordered: dict[int, Brought] = {}

    def place(brought: Brought, trail: list[int]) -> None:
        parent = brought.thread.parent
        if parent in numbers and parent not in ordered and parent not in trail:
            place(numbers[parent], [*trail, brought.thread.number])
        ordered[brought.thread.number] = brought

    for each in threads:
        if each.thread.number not in ordered:
            place(each, [])
    return list(ordered.values())


# Writing the inbox


class Over(Model):
    """One thread brought over: the concern it is here, and the words kept in it."""

    brought: Brought
    concern: Concern
    items: list[Item]


def converted(inbox: Inbox, ledger: Ledger) -> Converted:
    """Bring `ledger`'s threads into `inbox`, in one transaction, and say what came over.

    Each act keeps when it happened in the second lup, but where that's before
    the concern it changes was last written, which a later version can't
    precede. Raise `ConversionError`, keeping nothing, where the inbox was
    brought over already, or where something was written by a party of the
    second lup's this lup has no party for.
    """
    database = inbox.database
    marker = CONVERTED.format(repository=inbox.repository)
    known = [each.id for each in inbox.agents()]
    seen = sorted(
        (
            (each.at, each.by)
            for brought in ledger.threads
            for each in [*brought.words, *brought.bodies, *brought.marks]
            if isinstance(each.by, Conversation)
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    first_seen = {by: at for at, by in seen}
    numbers = [each.thread.number for each in ledger.threads]

    @cache
    def agent(conversation: Conversation) -> AgentRecord:
        """Return the agent `conversation` is here, made the first time, under the conversation that spawned them, named as the second lup named them where this lup can take the name."""
        caller = conversation.caller()
        spawned = ledger.spawner(conversation)
        spawner = None if spawned is None else agent(spawned)
        found = ledger.named(conversation)
        given = None if found is None else found.name
        name = (
            inbox.free(given)
            if given is not None and valid_name(given) and caller.id not in known
            else None
        )
        at = first_seen.get(conversation)
        return inbox.model_copy(update={"at": at}).agent(caller, name, spawner)

    def writer(by: Writer) -> PartyRecord:
        """Return the party here who wrote what `by` wrote in the second lup."""
        match by:
            case Conversation():
                return agent(by)
            case Elsewhere(party="operator"):
                return inbox.operator()
            case Elsewhere(party=party):
                message = (
                    f"the second lup's `{party}` wrote in a thread, and no party "
                    "here is theirs"
                )
                raise ConversionError(message, about=[party])

    @cache
    def over(number: int) -> Over:
        """Bring the thread numbered `number` over, after the thread it's under where that comes before it."""
        brought = ledger.threads[numbers.index(number)]
        thread = brought.thread
        parent = (
            over(thread.parent).concern
            if thread.parent in numbers[: numbers.index(number)]
            else None
        )
        place: PartyRecord | Concern = (
            inbox.pile(FRICTIONS)
            if brought.friction()
            else writer(thread.holder)
            if thread.holder is not None
            else parent
            if parent is not None
            else inbox.pile(NO_AGENT)
        )
        first = brought.words[0] if brought.words else None
        opener = (
            writer(first.by)
            if first is not None
            else writer(thread.holder)
            if thread.holder is not None
            else inbox.operator()
        )
        concern = inbox.model_copy(update={"at": brought.opened}).opened(
            opener,
            thread.title,
            thread.title if first is None else first.reason.text,
            place,
            friction=brought.friction(),
            name=(
                inbox.free(thread.name)
                if thread.name is not None and valid_name(thread.name)
                else None
            ),
        )
        events = sorted(
            [*brought.words[1:], *brought.bodies, *brought.marks],
            key=lambda each: each.at,
        )

        latest = concern
        for event in events:
            there = inbox.model_copy(update={"at": max(event.at, latest.at)})
            by = writer(event.by)
            match event:
                case Filed():
                    there.filed(by, latest, event.reason.text)
                case Bodied():
                    latest = there.rewritten(by, latest, event.text)
                case Marked() if isinstance(by, AgentRecord):
                    there.done(by, latest, event.to_try)
                case Marked():
                    message = (
                        f"a done mark in `{thread.name}` was written by "
                        f"{inbox.called(by)}, who isn't an agent"
                    )
                    raise ConversionError(message, about=[str(thread.number)])
        return Over(brought=brought, concern=latest, items=inbox.said_in(latest))

    with database.together():
        if database.plain(marker, Converted) is not None:
            message = (
                f"{inbox.repository}'s inbox was brought over from the second lup "
                "already: a conversion runs once"
            )
            raise ConversionError(message, about=[inbox.repository])
        brought = [over(each) for each in numbers]
        inbox.shown([item for each in brought for item in each.items])
        ended = [each for each in inbox.agents() if each.id not in known]
        for each in ended:
            inbox.end(each)
        counted = Converted(
            repository=inbox.repository,
            concerns=sum(not each.brought.friction() for each in brought),
            frictions=sum(each.brought.friction() for each in brought),
            words=sum(len(each.brought.words) for each in brought),
            bodies=sum(len(each.brought.bodies) for each in brought),
            marks=sum(len(each.brought.marks) for each in brought),
            agents=len(ended),
        )
        database.rewritten(marker, counted)
    return counted


def valid_name(name: str) -> bool:
    """Say whether `name` is one a node can take here."""
    try:
        named(name)
    except ValueError:
        return False
    return True
