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
from lup.blocks import OfAgent
from lup.programs import run
from lup_dev.declaration.serving import Lup, Publisher
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.records import Record, Records
from lup_dev.inbox.exchanges import Exchanges
from lup_dev.inbox.protocol import Exchanged
from lup_transcripts.environment.module import Transcripts
from lup_transcripts.environment.serving import TranscriptsServing, copied

if TYPE_CHECKING:
    from lup.publishing import Published, Refusal
    from lup_dev.host.courier import Conversation


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
        records={"claude": held},
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
