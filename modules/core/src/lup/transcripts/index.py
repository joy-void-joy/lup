"""The index of every conversation's words, calls and results, in one SQLite database, kept current by reading only what each record added.

`README.md` here, *The index*. Its tables are declared as SQLAlchemy's `Table`s,
every query built from them; the full-text table is SQLite's FTS5, kept in step
with the steps it indexes by triggers, which SQLAlchemy can't declare, so its
statements are written once here.
- **A record is read from where the last read stopped** (`Records.read`), its
  reading kept beside it, so a record that grew costs what it added, and one
  that didn't costs a `stat`.
- **One conversation, one record read.** A conversation the runtimes keep in
  several homes, its record's original and a copy, is read from the home
  preferred (`Whose`): the original while it's there, else the copy.
- **What each of the operator's words answered** is kept as they're read: the
  agent's last words before them in the same record.
"""

import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, get_args
lazy import os
lazy from collections.abc import Generator, Iterator
lazy from sqlite3 import Connection as Driver

from pydantic import Field, SerializeAsAny
from sqlalchemy import (
    Column,
    Connection,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    false,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy import (
    Index as Indexed,
)
from sqlalchemy.pool import StaticPool
lazy from sqlalchemy import ColumnElement, ScalarSelect, Select
lazy from sqlalchemy.pool import ConnectionPoolEntry

from lup.runtimes.records import (
    Called,
    Ended,
    Read,
    Reading,
    Record,
    Records,
    Returned,
    Said,
    Speaker,
    Stepped,
    Titled,
)
from lup.transcripts.ledger import Spoken, copied, spoken
from lup.types import Model, MutableModel
lazy from lup.inbox.said import SaidItem, SaidSince

type Whose = Literal["rooms", "operator", "kept", "archive"]
"""Whose home a record was read from: a room's, the operator's own runtime
directory, lup's copy of the operator's, or the second lup's copies, read and
never written. Where a conversation is in several, the first of these holding it
is read."""

TABLES = MetaData()
"""The index's tables, version 1 of them."""

RECORDS = Table(
    "records",
    TABLES,
    Column("id", Integer, primary_key=True),
    Column("runtime", String, nullable=False),
    Column("whose", String, nullable=False),
    Column("path", String, nullable=False, unique=True),
    Column("conversation", String, nullable=False),
    Column("session", String, nullable=False),
    Column("subagent", String),
    Column("spawner", String),
    Column("call", String),
    Column("directory", String),
    Column("reading", Text, nullable=False),
    Column("size", Integer, nullable=False),
    Column("changed", Integer, nullable=False),
    Column("indexed", Integer, nullable=False),
    Column("title", String),
    Column("named", String),
    Column("first", String),
    Column("last", String),
    Column("spoken", Integer),
    Indexed("records_conversation", "conversation"),
    Indexed("records_session", "session"),
)
"""Each record found, where its last read stopped, and what's known of its
conversation: `conversation` names it across homes, the runtime and its ids;
`indexed` says whether its steps are the ones indexed for that conversation;
`spoken` is the step of the agent's last words read so far."""

STEPS = Table(
    "steps",
    TABLES,
    Column("id", Integer, primary_key=True),
    Column("record", Integer, nullable=False),
    Column("line", Integer, nullable=False),
    Column("place", Integer, nullable=False),
    Column("at", String),
    Column("kind", String, nullable=False),
    Column("by", String),
    Column("key", String),
    Column("call", String),
    Column("tool", String),
    Column("answers", Integer),
    Column("ending", Integer, nullable=False, default=0),
    Column("text", Text, nullable=False),
    Indexed("steps_of", "record", "line", "place"),
    Indexed("steps_keyed", "key", "place"),
)
"""Each step indexed: what it is, who said it, its text, for the operator's
words the step of the agent's they answered, and, for the agent's words, whether
they were the last of a turn."""

SAID = Table(
    "said",
    TABLES,
    Column("id", Integer, primary_key=True),
    Column("source", String, nullable=False),
    Column("number", Integer, nullable=False),
    Column("part", Integer),
    Column("at", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("by", String, nullable=False),
    Column("runtime", String),
    Column("session", String),
    Column("agent", String),
    Column("kind", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("on_number", Integer),
    Column("quoted", Text),
    Indexed("said_of", "source", "number"),
    Indexed("said_session", "session"),
)
"""Each item said through lup, the second lup's ledger's or this lup's inbox's:
the operator's words, each apart, and agents' items whole, each with the
conversation it's of and what it's on."""

MARKS = Table(
    "marks",
    TABLES,
    Column("name", String, primary_key=True),
    Column("value", Text, nullable=False),
)
"""Where each source of what's said was last read: the ledger's copy, as its
files stood, and the inbox's last key."""

SAID_WORDS = Table(
    "said_words", MetaData(), Column("rowid", Integer), Column("said_words", Text)
)
"""The full-text index of what's said through lup, as `WORDS` is of the steps."""

WORDS = Table("words", MetaData(), Column("rowid", Integer), Column("words", Text))
"""The full-text index of the steps' text, an FTS5 table SQLAlchemy reads but
can't make, its rows the steps' by their ids."""


def words_made(connection: Connection) -> None:
    """Make the full-text index and keep it in step with the steps, in SQLite's own statements, which SQLAlchemy has no construct for: each step's text indexed as it's kept, and forgotten as it's deleted."""
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE words USING fts5(tool, text, content='steps', "
        "content_rowid='id', tokenize='unicode61 remove_diacritics 2', prefix='2 3')"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER steps_indexed AFTER INSERT ON steps BEGIN "
        "INSERT INTO words(rowid, tool, text) VALUES (new.id, new.tool, new.text); END"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER steps_forgotten AFTER DELETE ON steps BEGIN "
        "INSERT INTO words(words, rowid, tool, text) "
        "VALUES ('delete', old.id, old.tool, old.text); END"
    )
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE said_words USING fts5(text, content='said', "
        "content_rowid='id', tokenize='unicode61 remove_diacritics 2', prefix='2 3')"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER said_indexed AFTER INSERT ON said BEGIN "
        "INSERT INTO said_words(rowid, text) VALUES (new.id, new.text); END"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER said_forgotten AFTER DELETE ON said BEGIN "
        "INSERT INTO said_words(said_words, rowid, text) "
        "VALUES ('delete', old.id, old.text); END"
    )


class StepRow(Model):
    """A step's row, as the index keeps it."""

    id: int
    record: int
    line: int
    place: int
    at: str | None
    kind: str
    by: Speaker | None
    key: str | None
    call: str | None
    tool: str | None
    answers: int | None
    text: str


class Rowed(Model):
    """A record's new steps as rows, the agent's steps that ended a turn among them, and the agent's last step after them."""

    rows: list[StepRow]
    endings: list[int]
    spoken: int | None


class Home(Model):
    """A home a runtime keeps records in, read with its reader: its own directory, a room's, or a copy kept of one in its layout."""

    runtime: str
    """The runtime, by lup's name for it."""
    path: Path
    whose: Whose
    records: SerializeAsAny[Records]


type Searcher = Literal["operator", "agent", "lup", "tools", "any"]
"""Whose words a search looks in: the operator's, typed or through lup; the
agents', their last words of each turn and their items through lup; lup's; the
calls and what they returned; or everything."""


class Searching(Model):
    """A search: the words, each a word or a phrase, and what narrows it."""

    words: list[str]
    """Every one of them is there, case aside: a word matches any word that
    starts with it, a phrase its words in order."""
    by: Searcher = "operator"
    """Whose words to look in: the operator's, typed or through lup; the
    agents', their last words of each turn and their items through lup; lup's;
    the calls and what they returned; or everything."""
    under: list[Path] = []
    """Only conversations that ran in a directory under one of these."""
    since: datetime | None = None
    until: datetime | None = None
    limit: Annotated[int, Field(ge=1)] = 20
    """The most hits answered, the latest; how many more there are is said."""
    whole: bool = False
    """Each hit with all of what it answered, rather than its first line."""


type Source = Literal["record", "ledger", "inbox"]
"""Where a hit was read from: a runtime's record of a conversation, the second
lup's ledger, or this lup's inbox."""


class Hit(Model):
    """What a search found: a step of a conversation's record, or an item said through lup; when, where, and what it answered."""

    source: Source
    step: int | None = None
    """The record's step, which `show` opens the conversation around; none for
    an item."""
    number: int | None = None
    """The item's number; none for a record's step."""
    runtime: str | None = None
    session: str | None = None
    subagent: str | None = None
    title: str | None = None
    directory: str | None = None
    repository: str | None = None
    whose: Whose | None = None
    at: str | None
    kind: str
    by: str | None
    tool: str | None = None
    text: str
    answered: str | None = None
    """What it answered: for the operator's words in a record, the agent's last
    words before them; for an item, the passage of the item it's on; none
    where nothing is known."""
    on: int | None = None
    """For an item, the number of the item it's on."""


class Searched(Model):
    """What a search found: its hits, the latest first, and how many more it found past its limit."""

    hits: list[Hit]
    more: int


class Listing(Model):
    """Which conversations to list: where they ran, when, and how many."""

    under: list[Path] = []
    """Only conversations that ran in a directory under one of these."""
    since: datetime | None = None
    until: datetime | None = None
    subagents: bool = False
    """Subagents' conversations too, each under its session; sessions alone
    otherwise."""
    limit: Annotated[int, Field(ge=1)] = 50
    """The most listed, the latest; how many more there are is said."""


class Conversation(Model):
    """A conversation as the index knows it: its runtime and ids, its name, where and when it ran, and how many times the operator spoke in it."""

    runtime: str
    session: str
    subagent: str | None
    spawner: str | None
    title: str | None
    directory: str | None
    whose: Whose
    first: str | None
    last: str | None
    spoken: int
    """How many times the operator's words are among its steps."""


class Listed(Model):
    """The conversations listed, the latest first, and how many more there are."""

    conversations: list[Conversation]
    more: int


class Showing(Model):
    """Which conversation to show, and how much of it."""

    session: str
    """The session, by the runtime's id for it or its start, or by its name."""
    subagent: str | None = None
    """One of its subagents' conversations, by the runtime's id for them or its
    start; the session's own where none."""
    at: int | None = None
    """A step to show the steps around, as a hit names it."""
    around: Annotated[int, Field(ge=0)] = 10
    """How many steps before and after `at` to show."""
    whole: bool = False
    """Every step, calls and the agent's words mid-turn among them; else the
    operator's words, each after the agent's last words before them, or, around
    `at`, what was said but the agent's words mid-turn."""


class Stepping(Model):
    """A step shown, of the conversation's record or said through lup in it: what it is, who said it, and its text."""

    step: int | None = None
    """The record's step; none for an item said through lup."""
    number: int | None = None
    """The item's number, for one said through lup."""
    item: str | None = None
    """What the item is, for one said through lup: a comment, a question, a
    turn's end…"""
    on: int | None = None
    """The number of the item it's on, for one said through lup."""
    at: str | None
    kind: str
    by: str | None
    tool: str | None = None
    text: str
    ending: bool = False
    """For the agent's words, whether they were the last of a turn."""
    answered: str | None = None
    """For the operator's words, the agent's last words before them, or the
    passage of the item they're on."""


class Shown(Model):
    """A conversation's steps, as `Showing` asked, and how many of its steps come before and after them."""

    conversation: Conversation
    steps: list[Stepping]
    before: int
    after: int


class Caught(Model):
    """What catching up read: how many records it found, read, and read again from their start."""

    found: int = 0
    read: int = 0
    again: int = 0


class Index(MutableModel, arbitrary_types_allowed=True):
    """The index, open: every conversation's steps and what's known of each.

    Safe to share between threads: each call takes the lock.
    """

    connection: Connection
    lock: threading.RLock = Field(default_factory=threading.RLock)

    @classmethod
    def opened(cls, database: Path | str) -> Index:
        """Open the index kept at `database`, making it where there's none; `":memory:"` for one kept nowhere."""
        engine = create_engine(
            f"sqlite:///{database}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def connected(driver: Driver, _entry: ConnectionPoolEntry) -> None:
            """Leave beginning each transaction to SQLAlchemy, and set the journal."""
            driver.isolation_level = None
            driver.execute("PRAGMA journal_mode = WAL")
            driver.execute("PRAGMA synchronous = NORMAL")

        connection = engine.connect()
        with connection.begin():
            found = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
            if found == 0:
                TABLES.create_all(connection)
                words_made(connection)
                connection.exec_driver_sql("PRAGMA user_version = 1")
        return cls(connection=connection)

    def close(self) -> None:
        """Close the index; it can't be used after."""
        with self.lock:
            self.connection.close()
            self.connection.engine.dispose()

    @contextmanager
    def writing(self) -> Generator[Connection]:
        """Hold the lock and one transaction across a read or a write: committed where it ends, rolled back where it raises; within another, a savepoint of it."""
        with self.lock:
            begun = (
                self.connection.begin_nested()
                if self.connection.in_transaction()
                else self.connection.begin()
            )
            with begun:
                yield self.connection

    def caught_up(self, homes: list[Home]) -> Caught:
        """Read what every record in `homes` added since it was last read, each conversation from the home preferred among those holding it."""
        found = [
            (home, record) for home in homes for record in home.records.found(home.path)
        ]
        order = list(get_args(Whose.__value__))
        preferred = {
            named(home.runtime, record): (home, record)
            for home, record in sorted(
                found, key=lambda each: order.index(each[0].whose), reverse=True
            )
        }
        reads = [
            read
            for conversation, (home, record) in preferred.items()
            if (read := self.record_read(conversation, home, record)) is not None
        ]
        return Caught(
            found=len(found),
            read=len(reads),
            again=sum(1 for each in reads if each.again),
        )

    def record_read(self, conversation: str, home: Home, record: Record) -> Read | None:
        """Read what `record` added since it was last read, as the one indexed for `conversation`, and index it; none where it's as it was."""
        try:
            stat = record.path.stat()
        except OSError:
            return None
        with self.writing() as connection:
            row = connection.execute(
                select(RECORDS).where(RECORDS.c.path == str(record.path))
            ).one_or_none()
            if (
                row is not None
                and row.size == stat.st_size
                and row.changed == stat.st_mtime_ns
                and row.indexed
            ):
                return None
            others = (
                connection.execute(
                    select(RECORDS.c.id).where(
                        RECORDS.c.conversation == conversation,
                        RECORDS.c.path != str(record.path),
                        RECORDS.c.indexed == 1,
                    )
                )
                .scalars()
                .all()
            )
            for other in others:
                connection.execute(delete(STEPS).where(STEPS.c.record == other))
                connection.execute(
                    update(RECORDS).where(RECORDS.c.id == other).values(indexed=0)
                )
            since = (
                Reading.model_validate_json(row.reading)
                if row is not None and row.indexed
                else None
            )
            read = home.records.read(record, since)
            if row is None:
                key = connection.execute(
                    insert(RECORDS).values(
                        runtime=home.runtime,
                        whose=home.whose,
                        path=str(record.path),
                        conversation=conversation,
                        session=record.session,
                        subagent=record.conversation,
                        spawner=record.spawner,
                        call=record.call,
                        directory=str(record.directory) if record.directory else None,
                        reading=Reading().model_dump_json(),
                        size=0,
                        changed=0,
                        indexed=1,
                    )
                ).inserted_primary_key
                if key is None:
                    message = f"the index kept no row for {record.path}"
                    raise RuntimeError(message)
                record_id = int(key[0])
                spoken = None
            else:
                record_id = row.id
                spoken = row.spoken if since is not None else None
            if read.again or since is None:
                connection.execute(delete(STEPS).where(STEPS.c.record == record_id))
                spoken = None
            rowed = self.rows(record_id, read.steps, spoken)
            if rowed.rows:
                connection.execute(
                    insert(STEPS), [each.model_dump() for each in rowed.rows]
                )
            if rowed.endings:
                connection.execute(
                    update(STEPS).where(STEPS.c.id.in_(rowed.endings)).values(ending=1)
                )
            titles = [each for each in read.steps if isinstance(each, Titled)]
            times = [each.at for each in read.steps if each.at is not None]
            connection.execute(
                update(RECORDS)
                .where(RECORDS.c.id == record_id)
                .values(
                    reading=read.reading.model_dump_json(),
                    size=stat.st_size,
                    changed=stat.st_mtime_ns,
                    indexed=1,
                    whose=home.whose,
                    spoken=rowed.spoken,
                    **titled(titles),
                    **timed(times, first=row is None or since is None),
                )
            )
            return read

    def rows(self, record: int, steps: list[Stepped], spoken: int | None) -> Rowed:
        """Return each step's row, its text what's searched, the operator's words noting the agent's last words before them, which `spoken` starts as, and which of the agent's steps ended a turn."""
        number = self.next_step()

        def made() -> Iterator[StepRow | int]:
            """Yield each step's row, and at a turn's end the agent's step that ended it."""
            nonlocal number
            last = spoken
            for step in steps:
                if isinstance(step, Ended) and last is not None:
                    yield last
                text = searched(step)
                if text is None:
                    continue
                number += 1
                by: Speaker | None = step.by if isinstance(step, Said) else None
                yield StepRow(
                    id=number,
                    record=record,
                    line=step.place.line,
                    place=step.place.index,
                    at=moment(step.at),
                    kind=step.kind,
                    by=by,
                    key=step.key,
                    call=step.call if isinstance(step, Called | Returned) else None,
                    tool=step.tool if isinstance(step, Called) else None,
                    answers=last if by == "operator" else None,
                    text=text,
                )
                if by == "agent":
                    last = number

        made_ = list(made())
        rows = [each for each in made_ if isinstance(each, StepRow)]
        agents = [
            each.id for each in rows if each.kind == "said" and each.by == "agent"
        ]
        return Rowed(
            rows=rows,
            endings=[each for each in made_ if isinstance(each, int)],
            spoken=agents[-1] if agents else spoken,
        )

    def next_step(self) -> int:
        """Return the highest step's id, from which new ones count."""
        with self.writing() as connection:
            return connection.execute(select(func.max(STEPS.c.id))).scalar() or 0

    def listed(self, listing: Listing) -> Listed:
        """Return the conversations indexed, the latest first, narrowed as `listing` says."""
        spoken = (
            select(func.count())
            .where(
                STEPS.c.record == RECORDS.c.id,
                STEPS.c.kind == "said",
                STEPS.c.by == "operator",
            )
            .scalar_subquery()
        )
        kept = [
            RECORDS.c.indexed == 1,
            *([] if listing.subagents else [RECORDS.c.subagent.is_(None)]),
            *within(listing.under),
            *([RECORDS.c.last >= listing.since.isoformat()] if listing.since else []),
            *([RECORDS.c.first < listing.until.isoformat()] if listing.until else []),
        ]
        query = (
            select(*conversation_columns(), spoken.label("spoken"))
            .where(*kept)
            .order_by(RECORDS.c.last.desc(), RECORDS.c.id.desc())
            .limit(listing.limit)
        )
        counted = select(func.count()).select_from(RECORDS).where(*kept)
        with self.writing():
            rows = self.connection.execute(query).mappings().all()
            total = self.connection.execute(counted).scalar() or 0
        listed = [Conversation.model_validate(dict(each)) for each in rows]
        return Listed(conversations=listed, more=max(0, total - len(listed)))

    def named_by(self, session: str, subagent: str | None) -> list[Conversation]:
        """Return the conversations `session` names, by the start of their session's id or by their name, and `subagent`, by the start of theirs; several where it names several."""
        spoken = (
            select(func.count())
            .where(
                STEPS.c.record == RECORDS.c.id,
                STEPS.c.kind == "said",
                STEPS.c.by == "operator",
            )
            .scalar_subquery()
        )
        whose = (
            RECORDS.c.subagent.is_(None)
            if subagent is None
            else RECORDS.c.subagent.startswith(subagent, autoescape=True)
        )
        query = select(*conversation_columns(), spoken.label("spoken")).where(
            RECORDS.c.indexed == 1,
            or_(
                RECORDS.c.session.startswith(session, autoescape=True),
                RECORDS.c.title == session,
            ),
            whose,
        )
        with self.writing():
            rows = self.connection.execute(query).mappings().all()
        return [Conversation.model_validate(dict(each)) for each in rows]

    def shown(self, conversation: Conversation, showing: Showing) -> Shown:
        """Return `conversation`'s steps as `showing` asks: every one, those around a step, or the operator's words each with what they answered."""
        answered = STEPS.alias("answered")
        record = (
            select(RECORDS.c.id)
            .where(
                RECORDS.c.indexed == 1,
                RECORDS.c.session == conversation.session,
                RECORDS.c.runtime == conversation.runtime,
                RECORDS.c.subagent.is_(None)
                if conversation.subagent is None
                else RECORDS.c.subagent == conversation.subagent,
            )
            .scalar_subquery()
        )
        columns = [
            STEPS.c.id.label("step"),
            STEPS.c.at,
            STEPS.c.kind,
            STEPS.c.by,
            STEPS.c.tool,
            STEPS.c.text,
            STEPS.c.ending,
            answered.c.text.label("answered"),
        ]
        steps = (
            select(*columns)
            .outerjoin(answered, answered.c.id == STEPS.c.answers)
            .where(STEPS.c.record == record)
        )
        said = [
            STEPS.c.kind == "said",
            or_(STEPS.c.by != "agent", STEPS.c.ending == 1),
        ]
        match showing:
            case Showing(at=int() as at, whole=True):
                shown = steps.where(
                    STEPS.c.id >= self.around(record, at, -showing.around),
                    STEPS.c.id <= self.around(record, at, showing.around),
                )
            case Showing(at=int() as at):
                shown = steps.where(
                    STEPS.c.id >= self.around(record, at, -showing.around),
                    STEPS.c.id <= self.around(record, at, showing.around),
                    *said,
                )
            case Showing(whole=True):
                shown = steps
            case _:
                shown = steps.where(STEPS.c.kind == "said", STEPS.c.by == "operator")
        every = select(func.count()).where(STEPS.c.record == record)
        with self.writing() as connection:
            rows = connection.execute(shown.order_by(STEPS.c.id)).mappings().all()
            total = connection.execute(every).scalar() or 0
            listed = [Stepping.model_validate(dict(each)) for each in rows]
            before = (
                connection.execute(
                    select(func.count()).where(
                        STEPS.c.record == record, STEPS.c.id < listed[0].step
                    )
                ).scalar()
                or 0
                if listed and showing.at is not None
                else 0
            )
        after = total - before - len(listed) if showing.at is not None else 0
        items = self.said_in(conversation, showing, listed)
        merged = sorted(
            [*listed, *items], key=lambda each: (each.at or "", each.step or 0)
        )
        return Shown(
            conversation=conversation, steps=merged, before=before, after=after
        )

    def said_in(
        self, conversation: Conversation, showing: Showing, steps: list[Stepping]
    ) -> list[Stepping]:
        """Return what was said through lup in `conversation`, as `showing` asks: the operator's words alone by default; every item, among `steps` as far as they reach, around a step or whole."""
        whose = (
            SAID.c.agent.is_(None)
            if conversation.subagent is None
            else SAID.c.agent == conversation.subagent
        )
        times = [each.at for each in steps if each.at]
        window = (
            [SAID.c.at >= min(times), SAID.c.at <= max(times)]
            if showing.at is not None and times
            else []
        )
        operator = (
            [SAID.c.by == "operator"]
            if showing.at is None and not showing.whole
            else []
        )
        query = (
            select(
                SAID.c.number,
                SAID.c.kind.label("item"),
                SAID.c.on_number.label("on"),
                SAID.c.at,
                literal("said").label("kind"),
                SAID.c.by,
                SAID.c.text,
                SAID.c.quoted.label("answered"),
            )
            .where(SAID.c.session == conversation.session, whose, *window, *operator)
            .order_by(SAID.c.at, SAID.c.id)
        )
        with self.writing() as connection:
            rows = connection.execute(query).mappings().all()
        return [Stepping.model_validate(dict(each)) for each in rows]

    def around(self, record: ScalarSelect[int], at: int, by: int) -> int:
        """Return the id of the step `by` steps from `at` in the record, or the first or last where fewer are there."""
        ids = (
            select(STEPS.c.id)
            .where(
                STEPS.c.record == record,
                STEPS.c.id >= at if by >= 0 else STEPS.c.id <= at,
            )
            .order_by(STEPS.c.id if by >= 0 else STEPS.c.id.desc())
            .limit(abs(by) + 1)
        )
        with self.writing():
            found = self.connection.execute(ids).scalars().all()
        return found[-1] if found else at

    def searched(self, searching: Searching) -> Searched:
        """Return the steps holding every word of `searching`, narrowed as it says: a step a fork copied from another conversation found once, where it was first said."""
        query = matching(searching.words)
        if not query:
            return Searched(hits=[], more=0)
        same = func.coalesce(STEPS.c.key, func.cast(STEPS.c.id, String))
        found = (
            select(
                STEPS.c.id,
                func.row_number()
                .over(partition_by=[same, STEPS.c.place], order_by=STEPS.c.id)
                .label("nth"),
            )
            .join(WORDS, WORDS.c.rowid == STEPS.c.id)
            .join(RECORDS, RECORDS.c.id == STEPS.c.record)
            .where(WORDS.c.words.match(query), *narrowed(searching))
            .subquery()
        )
        answered = STEPS.alias("answered")
        hits = (
            select(
                literal("record").label("source"),
                STEPS.c.id.label("step"),
                RECORDS.c.runtime,
                RECORDS.c.session,
                RECORDS.c.subagent,
                RECORDS.c.title,
                RECORDS.c.directory,
                RECORDS.c.whose,
                STEPS.c.at,
                STEPS.c.kind,
                STEPS.c.by,
                STEPS.c.tool,
                STEPS.c.text,
                answered.c.text.label("answered"),
            )
            .join(found, found.c.id == STEPS.c.id)
            .join(RECORDS, RECORDS.c.id == STEPS.c.record)
            .outerjoin(answered, answered.c.id == STEPS.c.answers)
            .where(found.c.nth == 1)
            .order_by(STEPS.c.at.desc(), STEPS.c.id.desc())
            .limit(searching.limit)
        )
        counted = select(func.count()).select_from(found).where(found.c.nth == 1)
        said = said_found(query, searching)
        said_hits = (
            select(
                SAID.c.source,
                SAID.c.number,
                SAID.c.runtime,
                SAID.c.session,
                SAID.c.agent.label("subagent"),
                SAID.c.repository,
                SAID.c.at,
                SAID.c.kind,
                SAID.c.by,
                SAID.c.text,
                SAID.c.quoted.label("answered"),
                SAID.c.on_number.label("on"),
            )
            .where(SAID.c.id.in_(said))
            .order_by(SAID.c.at.desc(), SAID.c.id.desc())
            .limit(searching.limit)
        )
        said_counted = select(func.count()).where(SAID.c.id.in_(said))
        with self.writing():
            rows = [
                *self.connection.execute(hits).mappings().all(),
                *self.connection.execute(said_hits).mappings().all(),
            ]
            total = (self.connection.execute(counted).scalar() or 0) + (
                self.connection.execute(said_counted).scalar() or 0
            )
        every = sorted(
            (Hit.model_validate(dict(each)) for each in rows),
            key=lambda each: each.at or "",
            reverse=True,
        )
        listed = every[: searching.limit]
        return Searched(hits=self.titled(listed), more=max(0, total - len(listed)))

    def titled(self, hits: list[Hit]) -> list[Hit]:
        """Return `hits`, each item's given the title the index knows its conversation by, where it knows one."""
        sessions = list(dict.fromkeys(each.session for each in hits if each.session))
        with self.writing() as connection:
            titles = dict(
                connection.execute(
                    select(RECORDS.c.session, RECORDS.c.title).where(
                        RECORDS.c.session.in_(sessions),
                        RECORDS.c.subagent.is_(None),
                        RECORDS.c.title.is_not(None),
                    )
                ).all()
            )
        return [
            each
            if each.title is not None or each.session not in titles
            else each.model_copy(update={"title": titles[each.session]})
            for each in hits
        ]

    def ledger_caught_up(self, ledger: Path, into: Path) -> int:
        """Read the second lup's ledger at `ledger` again where its files changed since it was last read, its words in place of those read before, from a copy kept in `into`; return how many words it holds, or none read where it didn't change."""
        files = [ledger, ledger.with_name(f"{ledger.name}-wal")]
        stood = json.dumps(
            [
                [each.name, found.st_size, found.st_mtime_ns]
                for each in files
                if (found := statted(each)) is not None
            ]
        )
        with self.writing():
            before = self.connection.execute(
                select(MARKS.c.value).where(MARKS.c.name == "ledger")
            ).scalar()
        if before == stood or statted(ledger) is None:
            return 0
        words = spoken(copied(ledger, into))
        with self.writing() as connection:
            connection.execute(delete(SAID).where(SAID.c.source == "ledger"))
            if words:
                connection.execute(
                    insert(SAID), [said_row("ledger", each) for each in words]
                )
            marked(connection, "ledger", stood)
        return len(words)

    def inbox_after(self) -> int:
        """Return the inbox's key after which it's to be read next: 0 where it never was."""
        with self.writing():
            value = self.connection.execute(
                select(MARKS.c.value).where(MARKS.c.name == "inbox")
            ).scalar()
        return int(value) if value is not None else 0

    def inbox_caught_up(self, said: SaidSince) -> int:
        """Index the items `said` read from the inbox, and keep the key to read after next; return how many."""
        rows = [inbox_row(each) for each in said.items]
        with self.writing() as connection:
            if rows:
                connection.execute(insert(SAID), rows)
            marked(connection, "inbox", str(said.last))
        return len(rows)


def matching(words: list[str]) -> str:
    """Return the full-text query finding every one of `words`, each a phrase of the words it holds, its last matching any word starting with it.

    A word is a run of letters and digits, as the index reads text, so nothing
    the operator typed is read as the query language's own.

    >>> matching(["Queue", "said it all"])
    '"queue"* "said it all"*'
    """
    phrases = [
        " ".join(tokens(each.casefold())) for each in words if tokens(each.casefold())
    ]
    return " ".join(f'"{each}"*' for each in phrases)


def tokens(text: str) -> list[str]:
    """Return the words of `text` as the index reads them: each run of letters and digits."""

    def runs() -> Iterator[str]:
        """Yield each run of letters and digits in turn."""
        held = ""
        for each in text:
            if each.isalnum():
                held += each
                continue
            if held:
                yield held
            held = ""
        if held:
            yield held

    return list(runs())


def said_found(query: str, searching: Searching) -> Select[int]:
    """Return the query finding what's said through lup holding every word of `query`, narrowed as `searching` says: the operator's words, agents' items, or both."""
    match searching.by:
        case "operator" | "agent":
            whose = [SAID.c.by == searching.by]
        case "any":
            whose = []
        case _:
            whose = [false()]
    since = [SAID.c.at >= moment(searching.since)] if searching.since else []
    until = [SAID.c.at < moment(searching.until)] if searching.until else []
    return (
        select(SAID.c.id)
        .join(SAID_WORDS, SAID_WORDS.c.rowid == SAID.c.id)
        .where(SAID_WORDS.c.said_words.match(query), *whose, *since, *until)
    )


def said_row(source: Source, said: Spoken) -> dict[str, str | int | None]:
    """Return words read from the ledger as the index keeps them."""
    conversation = said.conversation
    return {
        "source": source,
        "number": said.number,
        "part": said.part,
        "at": moment(said.at),
        "repository": said.repository,
        "by": said.by,
        "runtime": conversation.runtime if conversation else None,
        "session": conversation.session if conversation else None,
        "agent": conversation.agent if conversation else None,
        "kind": said.kind,
        "text": said.text,
        "on_number": said.on,
        "quoted": said.quoted,
    }


def inbox_row(said: SaidItem) -> dict[str, str | int | None]:
    """Return an item read from the inbox as the index keeps it."""
    return {
        "source": "inbox",
        "number": said.number,
        "part": None,
        "at": moment(said.at),
        "repository": said.repository,
        "by": "agent" if said.agent is not None else "operator",
        "runtime": None,
        "session": said.agent.session if said.agent else None,
        "agent": said.agent.id if said.agent else None,
        "kind": said.kind,
        "text": said.text,
        "on_number": said.on,
        "quoted": said.quoted,
    }


def marked(connection: Connection, name: str, value: str) -> None:
    """Keep where a source was last read, in place of where it was before."""
    connection.execute(delete(MARKS).where(MARKS.c.name == name))
    connection.execute(insert(MARKS).values(name=name, value=value))


def conversation_columns() -> list[ColumnElement[str | None]]:
    """Return the columns a conversation is read from, but how many times the operator spoke."""
    return [
        RECORDS.c.runtime,
        RECORDS.c.session,
        RECORDS.c.subagent,
        RECORDS.c.spawner,
        RECORDS.c.title,
        RECORDS.c.directory,
        RECORDS.c.whose,
        RECORDS.c.first,
        RECORDS.c.last,
    ]


def within(under: list[Path]) -> list[ColumnElement[bool]]:
    """Return what keeps a conversation that ran in a directory under one of `under`: nothing where none is given."""
    if not under:
        return []
    return [
        or_(
            *(
                or_(
                    RECORDS.c.directory == str(each),
                    RECORDS.c.directory.startswith(f"{each}/", autoescape=True),
                )
                for each in under
            )
        )
    ]


def narrowed(searching: Searching) -> list[ColumnElement[bool]]:
    """Return what narrows a search to the steps it looks in: whose words, where the conversation ran, and when."""
    match searching.by:
        case "operator" | "lup":
            whose = [STEPS.c.kind == "said", STEPS.c.by == searching.by]
        case "agent":
            whose = [STEPS.c.kind == "said", STEPS.c.by == "agent", STEPS.c.ending == 1]
        case "tools":
            whose = [STEPS.c.kind.in_(["called", "returned"])]
        case "any":
            whose = []
    under = within(searching.under)
    since = [STEPS.c.at >= searching.since.isoformat()] if searching.since else []
    until = [STEPS.c.at < searching.until.isoformat()] if searching.until else []
    return [*whose, *under, *since, *until]


def statted(path: Path) -> os.stat_result | None:
    """Return what the machine says of the file at `path`; none where it isn't there."""
    try:
        return path.stat()
    except OSError:
        return None


def moment(at: datetime | None) -> str | None:
    """Return a moment as the index keeps it, in UTC, so moments from any source sort as text."""
    return None if at is None else at.astimezone(UTC).isoformat()


def named(runtime: str, record: Record) -> str:
    """Return the name a conversation is known by across homes: its runtime, its session, and its subagent's id where it's one."""
    return json.dumps([runtime, record.session, record.conversation])


def searched(step: Stepped) -> str | None:
    """Return the text a step is searched by, beside a call's tool: words as said, what a call was given, a result whole; none for a step holding no text."""
    match step:
        case Said(text=text):
            return text
        case Called(given=given):
            return json.dumps(given, ensure_ascii=False)
        case Returned(output=output):
            return output
        case _:
            return None


def titled(titles: list[Titled]) -> dict[str, str]:
    """Return a record's name as its latest title says, a name the operator or lup gave winning over the runtime's: nothing where no title was read."""
    ranked = ["guessed", "agent", "named"]
    best = max(titles, key=lambda each: ranked.index(each.how), default=None)
    return {} if best is None else {"title": best.title, "named": best.how}


def timed(times: list[datetime], *, first: bool) -> dict[str, str]:
    """Return when a record's steps began, where these are its first, and when its latest is."""
    if not times:
        return {}
    return {"last": moment(max(times)) or ""} | (
        {"first": moment(min(times)) or ""} if first else {}
    )
