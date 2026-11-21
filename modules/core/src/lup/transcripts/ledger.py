"""The second lup's ledger, read: the operator's words through it and agents' items, each with what it's on.

The second lup kept its inbox in one SQLite database, `ledger.sqlite3` in its
state's `ledger/` directory, at version 2 of its tables: each node's versions
as JSON, its latest named by `nodes`, and edges beside them. This lup reads it
and never writes it, from a copy taken whole (`copied`), since the second lup
writes it in write-ahead mode until it's switched off (#13), and a directory
lent read-only can't hold the reader's shared memory. Its shape was read from the
second lup's code (`lup_ledger`, `lup_dev/inbox/`), and checked on the
operator's own ledger (`docs/field-notes.md`, *The second lup's ledger*):
- **The operator's words** are a review's comments, each on an agent's item and
  quoting the passage it's on (`quote.text`), its letters to a party and its
  remarks on a conversation; a message of theirs; an answer's rulings; and a
  comment on an approval or a held change, kept on its `inbox:decided` edge.
  A review reaching several conversations is kept once for each, every copy
  holding every comment, so a comment is read once, by the review's moment and
  its place in it, from the copy that reached the conversation it's on.
- **Agents' items** are their questions, each decision with its lean, their
  messages (a turn's last words among them, `ending`), frictions, how it felt,
  and why they stopped. The judge's flagged writes and held changes, and
  approvals, aren't words, and aren't read.
"""

import shutil
from typing import Literal
lazy from collections.abc import Iterator
lazy from pathlib import Path

from pydantic import AwareDatetime, Field, ValidationError
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
)

from lup.types import Model

TABLES = MetaData()
"""The ledger's tables this lup reads, as version 2 of them declares them."""

NODES = Table(
    "nodes",
    TABLES,
    Column("number", Integer, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("kind", String, nullable=False),
)
"""Each node's latest version, by its number."""

VERSIONS = Table(
    "versions",
    TABLES,
    Column("version", Integer, primary_key=True),
    Column("record", Text, nullable=False),
)
"""Each version of each node, its record whole as JSON."""

EDGES = Table(
    "edges",
    TABLES,
    Column("drawn", Integer, primary_key=True),
    Column("kind", String, nullable=False),
    Column("target", Integer, nullable=False),
    Column("record", Text, nullable=False),
)
"""Each edge, in the order drawn, its record whole as JSON."""


class Party(Model):
    """Who wrote or received an item: the operator, lup, or a conversation by its runtime's ids."""

    party: str
    runtime: str | None = None
    session: str | None = None
    agent: str | None = None


class Quote(Model):
    """The passage a comment, a letter or a remark quotes."""

    text: str = ""


class Commented(Model):
    """One of a review's comments: the agent's item it's on, its words, and the passage it quotes, none where it's on the item whole."""

    item: int
    text: str
    quote: Quote | None = None


class Lettered(Model):
    """One of a review's letters: words to a party."""

    to: Party
    text: str
    quote: Quote | None = None


class Decided(Model):
    """One of a question's decisions, with the asker's lean."""

    text: str
    lean: str


class Ruled(Model):
    """The operator's word on one decision, by its number from 1."""

    decision: int
    verdict: str | None = None
    comment: str = ""


class Reason(Model):
    """What an item is, and what it holds, by the kind its `reason` names."""

    reason: str
    comments: list[Commented] = []
    letters: list[Lettered] = []
    remarks: list[Lettered] = []
    text: str = ""
    kind: str | None = None
    ending: bool = False
    decisions: list[Decided] = []
    rulings: list[Ruled] = []
    comment: str = ""
    question: int | None = None
    title: str | None = None
    why: str | None = None
    to: Party | None = None


class Item(Model):
    """An item as the ledger keeps it: its number, repository, who sent it to whom, when, and what it is."""

    number: int
    repository: str
    by: Party
    recipient: Party | None = None
    made: AwareDatetime
    reason: Reason


class Verdict(Model):
    """Where an approval or a held change stands once the operator decided it: their comment among it."""

    comment: str = ""


class Decision(Model):
    """An `inbox:decided` edge: the operator's decision on an item, and their comment."""

    at: AwareDatetime
    state: Verdict = Field(default_factory=Verdict)


type Kind = Literal[
    "comment",
    "letter",
    "remark",
    "message",
    "answer",
    "decided",
    "question",
    "turn's end",
    "note",
    "problem",
    "disagreement",
    "asked",
    "friction",
    "how it felt",
    "stop",
]
"""What a word read from the ledger was: the operator's comment on an item,
letter, remark, message, answer or comment on a decision; or an agent's
question, turn's end, note, problem, disagreement, question sent as a message,
friction, how it felt, or why they stopped."""


class Spoken(Model):
    """Words read from the ledger, whoever said them: when, what they are, and what they're on."""

    number: int
    """The item they're of."""
    part: int | None = None
    """Their place among the operator's words in a review, from 1; none for
    an item whole."""
    at: AwareDatetime
    repository: str
    by: Literal["operator", "agent"]
    conversation: Party | None = None
    """The agent's conversation they're of: who wrote an agent's item, or whom
    the operator's words were on or for."""
    kind: Kind
    text: str
    on: int | None = None
    """The number of the item they're on, or answer."""
    quoted: str | None = None
    """What of that item they're on: the passage quoted, or the decisions
    ruled on; none where they're on it whole."""


def copied(ledger: Path, into: Path) -> Path:
    """Copy the ledger's database at `ledger`, with its write-ahead log where there's one, into `into`, and return the copy, read from then on in its place."""
    into.mkdir(parents=True, exist_ok=True)
    copy = into / ledger.name
    shutil.copyfile(ledger, copy)
    log = ledger.with_name(f"{ledger.name}-wal")
    kept = copy.with_name(f"{copy.name}-wal")
    kept.unlink(missing_ok=True)
    if log.is_file():
        shutil.copyfile(log, kept)
    return copy


def spoken(database: Path) -> list[Spoken]:
    """Read every word of the operator's and every agent's item from the ledger's copy at `database`, the oldest first."""
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            records = connection.execute(
                select(VERSIONS.c.record)
                .join(NODES, NODES.c.version == VERSIONS.c.version)
                .where(NODES.c.kind == "inbox:item")
                .order_by(NODES.c.number)
            ).scalars()
            items = {
                item.number: item
                for record in records
                if (item := parsed(Item, record)) is not None
            }
            decisions = [
                (target, decision)
                for target, record in connection.execute(
                    select(EDGES.c.target, EDGES.c.record).where(
                        EDGES.c.kind == "inbox:decided"
                    )
                ).all()
                if (decision := parsed(Decision, record)) is not None
                and decision.state.comment
            ]
    finally:
        engine.dispose()
    copies = [
        (item, each)
        for item in items.values()
        if item.reason.reason == "review"
        for each in read(item, items)
    ]
    reviewed = {
        (each.at, each.part): each
        for _, each in sorted(
            copies,
            key=lambda pair: (
                pair[1].conversation == pair[0].recipient,
                -pair[0].number,
            ),
        )
    }
    words = [
        *(
            each
            for item in items.values()
            if item.reason.reason != "review"
            for each in read(item, items)
        ),
        *reviewed.values(),
        *(
            Spoken(
                number=target,
                at=decision.at,
                repository=items[target].repository,
                by="operator",
                conversation=items[target].by,
                kind="decided",
                text=decision.state.comment,
                on=target,
            )
            for target, decision in decisions
            if target in items
        ),
    ]
    return sorted(words, key=lambda each: (each.at, each.number, each.part or 0))


def read(item: Item, items: dict[int, Item]) -> Iterator[Spoken]:
    """Yield the words `item` holds: the operator's, a review's each apart; or an agent's item whole."""
    reason = item.reason
    match reason.reason:
        case "review":
            yield from reviewed(item, items)
        case "message" if item.by.party == "operator":
            yield Spoken(
                number=item.number,
                at=item.made,
                repository=item.repository,
                by="operator",
                conversation=reason.to or item.recipient,
                kind="message",
                text=reason.text,
            )
        case "answer":
            asked = items.get(reason.question or 0)
            ruled = "\n".join(
                " ".join(
                    each
                    for each in [
                        f"{ruling.decision}.",
                        ruling.verdict or "",
                        ruling.comment,
                    ]
                    if each
                )
                for ruling in reason.rulings
            )
            quoted = (
                "\n".join(
                    f"{number}. {each.text}"
                    for number, each in enumerate(asked.reason.decisions, start=1)
                    if any(ruling.decision == number for ruling in reason.rulings)
                )
                if asked is not None
                else None
            )
            yield Spoken(
                number=item.number,
                at=item.made,
                repository=item.repository,
                by="operator",
                conversation=asked.by if asked is not None else item.recipient,
                kind="answer",
                text="\n\n".join(each for each in [ruled, reason.comment] if each),
                on=reason.question,
                quoted=quoted or None,
            )
        case "question":
            decided = "\n".join(
                f"{number}. {each.text}\n   lean: {each.lean}"
                for number, each in enumerate(reason.decisions, start=1)
            )
            yield agents(
                item, "question", "\n\n".join(e for e in [reason.text, decided] if e)
            )
        case "message":
            yield agents(item, said_as(reason), reason.text)
        case "friction":
            yield agents(
                item,
                "friction",
                "\n\n".join(e for e in [reason.title or "", reason.text] if e),
            )
        case "how it felt":
            yield agents(item, "how it felt", reason.text)
        case "stop":
            yield agents(item, "stop", reason.why or "")
        case _:
            return


def said_as(reason: Reason) -> Kind:
    """Say what an agent's message was: a turn's last words, or a message of its kind."""
    if reason.ending:
        return "turn's end"
    match reason.kind:
        case "problem":
            return "problem"
        case "disagreement":
            return "disagreement"
        case "question":
            return "asked"
        case _:
            return "note"


def agents(item: Item, kind: Kind, text: str) -> Spoken:
    """Return an agent's item whole, as words of theirs."""
    return Spoken(
        number=item.number,
        at=item.made,
        repository=item.repository,
        by="agent",
        conversation=item.by,
        kind=kind,
        text=text,
    )


def reviewed(item: Item, items: dict[int, Item]) -> Iterator[Spoken]:
    """Yield a review's words, each apart, in its order: each comment on the item it's on, quoting the passage; each letter to its party; each remark on a conversation."""
    reason = item.reason
    commented = [
        Spoken(
            number=item.number,
            part=0,
            at=item.made,
            repository=item.repository,
            by="operator",
            conversation=on.by if (on := items.get(each.item)) is not None else None,
            kind="comment",
            text=each.text,
            on=each.item,
            quoted=each.quote.text
            if each.quote is not None and each.quote.text
            else None,
        )
        for each in reason.comments
    ]
    lettered = [
        *(addressed(item, each, "letter") for each in reason.letters),
        *(addressed(item, each, "remark") for each in reason.remarks),
    ]
    for place, each in enumerate([*commented, *lettered], start=1):
        yield each.model_copy(update={"part": place})


def addressed(item: Item, said: Lettered, kind: Kind) -> Spoken:
    """Return a review's letter or remark: the operator's words to a party, quoting what it's on where it quotes."""
    return Spoken(
        number=item.number,
        part=0,
        at=item.made,
        repository=item.repository,
        by="operator",
        conversation=said.to,
        kind=kind,
        text=said.text,
        quoted=said.quote.text if said.quote is not None and said.quote.text else None,
    )


def parsed[M: Model](kind: type[M], record: str) -> M | None:
    """Read `record` as a `kind`; none where it isn't one, as a record of an earlier shape may not be."""
    try:
        return kind.model_validate_json(record)
    except ValidationError:
        return None
