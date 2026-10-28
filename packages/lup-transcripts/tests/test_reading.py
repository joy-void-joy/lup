"""Reading what `Transcripts` keeps and what runs: its commands over the copies, and its views of a conversation, live.

Each runtime's reading of its records is a stand-in here, holding sessions the
tests write: no test reads the operator's.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from lup.blocks import OfAgent
from lup_dev.declaration.serving import Operator, Publisher
from lup_dev.host.records import (
    Call,
    Called,
    Reader,
    Record,
    Recorded,
    Records,
    Said,
    Transcript,
)
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.protocol import Exchanged
from lup_transcripts.environment.conversation import OfCall, OfExchange
from lup_transcripts.environment.module import Transcripts
from lup_transcripts.environment.serving import (
    Chosen,
    Every,
    Searched,
    TranscriptsServing,
)

if TYPE_CHECKING:
    from lup.publishing import Published, Refusal
    from lup_dev.host.courier import Conversation
    from lup_dev.host.protocol import Register

AT = datetime(2026, 10, 25, 9, tzinfo=UTC)


def session(name: str) -> Transcript:
    return Transcript(
        runtime="claude",
        session=f"{name}-0000",
        title=name,
        directory=Path("/work"),
        entries=[
            Said(by="operator", text="Make the drawer a view.", at=AT),
            Said(by="agent", text="I'll port it.", at=AT),
            Called(tool="Bash", gist="Run the tests", id="t1", at=AT),
            Said(by="operator", text="Now land it.", at=AT),
            Said(by="agent", text="Landed.", at=AT),
        ],
    )


class Kept(Reader):
    """A runtime whose copies of the operator's directory's records, and whose live records, hold the sessions given, each a file named for it."""

    def __init__(self, sessions: list[Transcript]) -> None:
        self.held = {each.session: each for each in sessions}

    def sessions(self, copies: Path) -> list[Path]:
        if copies.name != "host":
            return []
        return [copies / f"{name}.jsonl" for name in self.held]

    def read(self, record: Path) -> Transcript:
        return self.held[record.stem]

    def calls(self, record: Path, ids: list[str]) -> list[Call]:
        del record
        return [
            Call(id=each, input={"command": "uv run pytest"}, output="2 passed")
            for each in ids
        ]


class Live(Records):
    """A runtime whose live record of each conversation is a file under `home`."""

    def __init__(self, home: Path) -> None:
        self.home = home

    def kept(self, under: list[Path], repository: Path) -> list[Record]:
        del under, repository
        return []

    def conversation(self, session: str, agent: str | None) -> Path | None:
        record = self.home / f"{session}.jsonl"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.touch()
        return record


class Exchanging(Exchanges):
    """An inbox holding the items given, the same for every conversation."""

    def __init__(self, items: Exchanged) -> None:
        self.items = items

    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        del viewed
        return self.items


class Unpublished(Publisher):
    """A publishing door nothing goes through."""

    async def refusals(
        self, published: Published, launch: Register, conversation: Conversation | None
    ) -> list[Refusal]:
        raise AssertionError


def serving(tmp_path: Path, *sessions: Transcript) -> TranscriptsServing:
    reader = Kept(list(sessions))
    return TranscriptsServing(
        module=Transcripts(),
        recorded={"claude": Recorded(records=Live(tmp_path / "live"), reader=reader)},
        data=tmp_path / "data",
        related=[],
        publisher=Unpublished(),
        exchanges=Exchanging(Exchanged(sent=[], received=[])),
    )


def test_list_names_each_kept_session(tmp_path: Path) -> None:
    listed = asyncio.run(
        serving(tmp_path, session("first"), session("second")).list(Every(), Operator())
    )
    assert "`first` (claude first-0000)" in listed
    assert "`second` (claude second-0000)" in listed


def test_list_says_when_nothing_is_kept(tmp_path: Path) -> None:
    listed = asyncio.run(serving(tmp_path).list(Every(), Operator()))
    assert listed == "No session of this repository is kept yet."


def test_show_tells_the_operator_s_words_or_everything(tmp_path: Path) -> None:
    kept = serving(tmp_path, session("first"))
    words = asyncio.run(kept.show(Chosen(session="first"), Operator()))
    assert "you:\n    Make the drawer a view." in words
    assert "Run the tests" not in words
    whole = asyncio.run(
        kept.show(Chosen.model_validate({"session": "first", "all": True}), Operator())
    )
    assert "· called Bash" in whole


def test_search_finds_what_the_operator_said(tmp_path: Path) -> None:
    found = asyncio.run(
        serving(tmp_path, session("first")).search(Searched(words=["land"]), Operator())
    )
    assert "Now land it." in found


def test_the_conversation_view_reads_the_live_record(tmp_path: Path) -> None:
    viewed = OfAgent(runtime="claude", session="first-0000")
    blocks = asyncio.run(serving(tmp_path, session("first")).conversation(viewed))
    text = blocks.text()
    assert text.startswith("conversation · 5 steps")
    assert "▸ you: Make the drawer a view.  [exchange step=0]" in text
    assert "you: Now land it." in text


def test_an_earlier_exchange_and_a_call_are_views_of_their_own(tmp_path: Path) -> None:
    kept = serving(tmp_path, session("first"))
    earlier = OfExchange(runtime="claude", session="first-0000", step=0)
    exchange = asyncio.run(kept.exchange(earlier)).text()
    assert "I'll port it." in exchange
    assert "· Bash: Run the tests  [call id=t1]" in exchange
    call = OfCall(runtime="claude", session="first-0000", id="t1")
    shown = asyncio.run(kept.call(call)).text()
    assert "command: uv run pytest" in shown
    assert "2 passed" in shown
