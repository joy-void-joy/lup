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
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, get_args
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
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy import (
    Index as Indexed,
)
from sqlalchemy.pool import StaticPool
lazy from sqlalchemy import ColumnElement
lazy from sqlalchemy.pool import ConnectionPoolEntry

from lup.runtimes.records import (
    Called,
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
from lup.types import Model, MutableModel

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
    Column("text", Text, nullable=False),
    Indexed("steps_of", "record", "line", "place"),
    Indexed("steps_keyed", "key", "place"),
)
"""Each step indexed: what it is, who said it, its text, and, for the operator's
words, the step of the agent's they answered."""

WORDS = Table("words", MetaData(), Column("rowid", Integer), Column("words", Text))
"""The full-text index of the steps' text, an FTS5 table SQLAlchemy reads but
can't make, its rows the steps' by their ids."""


def words_made(connection: Connection) -> None:
    """Make the full-text index and keep it in step with the steps, in SQLite's own statements, which SQLAlchemy has no construct for: each step's text indexed as it's kept, and forgotten as it's deleted."""
    connection.exec_driver_sql(
        "CREATE VIRTUAL TABLE words USING fts5(text, content='steps', "
        "content_rowid='id', tokenize='unicode61 remove_diacritics 2', prefix='2 3')"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER steps_indexed AFTER INSERT ON steps BEGIN "
        "INSERT INTO words(rowid, text) VALUES (new.id, new.text); END"
    )
    connection.exec_driver_sql(
        "CREATE TRIGGER steps_forgotten AFTER DELETE ON steps BEGIN "
        "INSERT INTO words(words, rowid, text) VALUES ('delete', old.id, old.text); END"
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


class Home(Model):
    """A home a runtime keeps records in, read with its reader: its own directory, a room's, or a copy kept of one in its layout."""

    runtime: str
    """The runtime, by lup's name for it."""
    path: Path
    whose: Whose
    records: SerializeAsAny[Records]


type Searcher = Literal["operator", "agent", "lup", "tools", "any"]
"""Whose words a search looks in: the operator's, the agent's, lup's, the
calls and what they returned, or everything."""


class Searching(Model):
    """A search: the words, each a word or a phrase, and what narrows it."""

    words: list[str]
    """Every one of them is there, case aside: a word matches any word that
    starts with it, a phrase its words in order."""
    by: Searcher = "operator"
    under: list[Path] = []
    """Only conversations that ran in a directory under one of these."""
    since: datetime | None = None
    until: datetime | None = None
    limit: Annotated[int, Field(ge=1)] = 20
    """The most hits answered, the latest; how many more there are is said."""


class Hit(Model):
    """A step a search found: what it is, where, and, for the operator's words, the agent's last words before them."""

    step: int
    runtime: str
    session: str
    subagent: str | None
    title: str | None
    directory: str | None
    whose: Whose
    at: str | None
    kind: str
    by: Speaker | None
    tool: str | None
    text: str
    answered: str | None = None
    """The agent's last words before the operator's, in the same conversation;
    none where nothing came before, or the hit isn't the operator's."""


class Searched(Model):
    """What a search found: its hits, the latest first, and how many more it found past its limit."""

    hits: list[Hit]
    more: int


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
        """Hold the lock and one transaction across a write: committed where it ends, rolled back where it raises."""
        with self.lock, self.connection.begin():
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
            rows = list(self.rows(record_id, read.steps, spoken))
            if rows:
                connection.execute(insert(STEPS), [each.model_dump() for each in rows])
            agents = [
                each.id for each in rows if each.kind == "said" and each.by == "agent"
            ]
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
                    spoken=agents[-1] if agents else spoken,
                    **titled(titles),
                    **timed(times, first=row is None or since is None),
                )
            )
            return read

    def rows(
        self, record: int, steps: list[Stepped], spoken: int | None
    ) -> Iterator[StepRow]:
        """Yield each step's row, its text what's searched, the operator's words noting the agent's last words before them, which `spoken` starts as."""
        last = spoken
        number = self.next_step()
        for step in steps:
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
                at=step.at.isoformat() if step.at else None,
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

    def next_step(self) -> int:
        """Return the highest step's id, from which new ones count."""
        return self.connection.execute(select(func.max(STEPS.c.id))).scalar() or 0

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
        with self.lock:
            rows = self.connection.execute(hits).mappings().all()
            total = self.connection.execute(counted).scalar() or 0
        listed = [Hit.model_validate(dict(each)) for each in rows]
        return Searched(hits=listed, more=max(0, total - len(listed)))


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


def narrowed(searching: Searching) -> list[ColumnElement[bool]]:
    """Return what narrows a search to the steps it looks in: whose words, where the conversation ran, and when."""
    match searching.by:
        case "operator" | "agent" | "lup":
            whose = [STEPS.c.kind == "said", STEPS.c.by == searching.by]
        case "tools":
            whose = [STEPS.c.kind.in_(["called", "returned"])]
        case "any":
            whose = []
    under = (
        [
            or_(
                *(
                    or_(
                        RECORDS.c.directory == str(each),
                        RECORDS.c.directory.startswith(f"{each}/", autoescape=True),
                    )
                    for each in searching.under
                )
            )
        ]
        if searching.under
        else []
    )
    since = [STEPS.c.at >= searching.since.isoformat()] if searching.since else []
    until = [STEPS.c.at < searching.until.isoformat()] if searching.until else []
    return [*whose, *under, *since, *until]


def named(runtime: str, record: Record) -> str:
    """Return the name a conversation is known by across homes: its runtime, its session, and its subagent's id where it's one."""
    return json.dumps([runtime, record.session, record.conversation])


def searched(step: Stepped) -> str | None:
    """Return the text a step is searched by: words as said, a call as its tool and what it was given, a result whole; none for a step holding no text."""
    match step:
        case Said(text=text):
            return text
        case Called(tool=tool, given=given):
            return f"{tool} {json.dumps(given, ensure_ascii=False)}"
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
    return {"last": max(times).isoformat()} | (
        {"first": min(times).isoformat()} if first else {}
    )
