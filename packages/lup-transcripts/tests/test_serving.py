"""Keeping a copy of a repository's sessions' records, when a launch opens and when it stops.

The runtimes' homes here are directories the tests write: no test reads the
operator's.
"""

import asyncio
import json
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest

import lup
from lup.doors import served
from lup.programs import run
from lup_dev import Modules, Project
from lup_dev.declaration.kinds import Folds
from lup_dev.declaration.resolve import resolve
from lup_dev.declaration.serving import Lup, Publisher
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.records import Call as RecordedCall
from lup_dev.host.records import Reader as RecordsReader
from lup_dev.host.records import Record, Recorded, Records, Transcript
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.protocol import Exchanged
from lup_transcripts.environment.conversation import EARLIER_KIND
from lup_transcripts.environment.module import Transcripts
from lup_transcripts.environment.serving import TranscriptsServing, copied

if TYPE_CHECKING:
    from lup.blocks import OfAgent
    from lup.publishing import Published, Refusal
    from lup_dev.host.courier import Conversation


class Unread(RecordsReader):
    """A runtime whose copies hold no session to read."""

    def sessions(self, copies: Path) -> list[Path]:
        del copies
        return []

    def read(self, record: Path) -> Transcript:
        message = f"no session is kept at {record}"
        raise FileNotFoundError(message)

    def calls(self, record: Path, ids: list[str]) -> list[RecordedCall]:
        del record, ids
        return []


class Unexchanged(Exchanges):
    """An inbox where no conversation exchanged any item."""

    async def exchanged(self, viewed: OfAgent) -> Exchanged:
        del viewed
        return Exchanged(sent=[], received=[])


class Unpublished(Publisher):
    """A publishing door nothing goes through."""

    async def refusals(
        self,
        published: Published,
        launch: Register,
        conversation: Conversation | None,
    ) -> list[Refusal]:
        raise AssertionError


def lines(path: Path, *records: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{json.dumps(each)}\n" for each in records))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repository, with no commit."""
    root = tmp_path / "work"
    root.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=root)
    return root


def test_a_copy_takes_what_s_missing_or_grown_and_leaves_what_s_unchanged(
    tmp_path: Path,
) -> None:
    source = tmp_path / "home" / "projects" / "p"
    lines(source / "s1.jsonl", {"n": 1})
    lines(source / "s1" / "tool-results" / "r.txt", {"n": 2})
    records = [Record(source=source, place=PurePosixPath("projects", "p"))]
    target = tmp_path / "copy"
    assert copied(records, target) == 2
    assert copied(records, target) == 0
    with (source / "s1.jsonl").open("a", encoding="utf-8") as grown:
        grown.write('{"n": 3}\n')
    assert copied(records, target) == 1
    assert (target / "projects" / "p" / "s1.jsonl").read_text() == (
        source / "s1.jsonl"
    ).read_text()


class Held(Records):
    """A runtime keeping one record, and noting what it was asked for."""

    def __init__(self, record: Record) -> None:
        self.record = record
        self.asked: list[list[Path]] = []

    def conversation(self, session: str, agent: str | None) -> Path | None:
        return None

    def kept(self, under: list[Path]) -> list[Record]:
        self.asked.append(under)
        return [self.record]


def test_transcripts_copy_the_repository_s_records_at_its_moments(
    repo: Path, tmp_path: Path
) -> None:
    source = tmp_path / "home" / "projects" / "p"
    lines(source / "s1.jsonl", {"n": 1})
    held = Held(Record(source=source, place=PurePosixPath("projects", "p")))
    data = tmp_path / "data"
    registered = Register(
        launch="one",
        runtime="claude",
        worktree=repo,
        repository=repo / ".git",
        judge=tmp_path / "judge",
        container="lup-one",
        limits=Limits(actions=[], protected=[]),
        github=None,
    )
    serving = TranscriptsServing(
        module=Transcripts(),
        recorded={"claude": Recorded(records=held, reader=Unread())},
        data=data,
        related=[],
        publisher=Unpublished(),
        exchanges=Unexchanged(),
    )
    asyncio.run(serving.keep(lup.Stopped(), by=Lup(launch=registered)))
    assert (data / "claude" / "projects" / "p" / "s1.jsonl").is_file()
    [under] = held.asked
    assert under[0] == repo / ".git"
    assert repo in under


def test_a_call_read_whole_is_answered_again_as_a_call_of_its_agent_s_finishes() -> (
    None
):
    door = served(TranscriptsServing)["call"].viewing()
    assert door is not None
    assert door.watch == lup.Watch(on=[lup.CallFinished])


def test_a_person_s_layer_keeps_more_or_fewer_of_the_agent_s_words_open_in_the_drawer(
    tmp_path: Path,
) -> None:
    keeping = EARLIER_KIND.model_copy(update={"keeps_open": 40})
    person = Modules().edit(Transcripts(folds=Folds().replace("earlier", keeping)))
    resolved = resolve(Project(modules=person))
    [module] = [each for each in resolved.modules if isinstance(each, Transcripts)]

    def serving(module: Transcripts) -> TranscriptsServing:
        return TranscriptsServing(
            module=module,
            recorded={},
            data=tmp_path,
            related=[],
            publisher=Unpublished(),
            exchanges=Unexchanged(),
        )

    assert serving(module).earlier().keeps_open == 40
    assert serving(Transcripts()).earlier().keeps_open == 20
    # The looks the page reads say it with the kind.
    assert [
        each.keeps_open for each in resolved.looks.folds if each.name == "earlier"
    ] == [40]


def test_an_exchange_is_answered_again_as_the_drawer_is_since_what_came_before_the_agent_s_last_words_moves_on() -> (
    None
):
    doors = served(TranscriptsServing)
    exchange, conversation = (
        doors["exchange"].viewing(),
        doors["conversation"].viewing(),
    )
    assert exchange is not None
    assert conversation is not None
    assert exchange.watch == conversation.watch
    assert lup.TurnEnded in exchange.watch.on
