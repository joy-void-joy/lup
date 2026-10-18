"""Each runtime's records of a repository's sessions, and keeping a copy of them.

The runtimes' homes here are directories the tests write, laid out as Claude Code
and Codex lay out their own: no test reads the operator's.
"""

import asyncio
import json
from pathlib import Path, PurePosixPath

from lup.transcripts.hooks import TranscriptsHooks, copied
from lup.transcripts.module import Transcripts
from lup_dev.adapters.claude import ClaudeRecords
from lup_dev.adapters.codex import CodexRecords
from lup_dev.declaration.serving import Moment
from lup_dev.host.protocol import Limits, Register
from lup_dev.host.records import Record, Records


def lines(path: Path, *records: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{json.dumps(each)}\n" for each in records))


def test_claude_code_s_records_are_the_folders_whose_sessions_ran_under_the_repository(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    ours = home / "projects" / "-w-lup-git-tree-dev"
    lines(
        ours / "s1.jsonl",
        {"type": "mode", "sessionId": "s1"},
        {"type": "user", "cwd": "/w/lup.git/tree/dev"},
    )
    (ours / "s1" / "subagents").mkdir(parents=True)
    (home / "file-history" / "s1").mkdir(parents=True)
    lines(
        home / "projects" / "-w-other" / "s2.jsonl", {"type": "user", "cwd": "/w/other"}
    )
    lines(home / "projects" / "-w-quiet" / "s3.jsonl", {"type": "mode"})
    kept = ClaudeRecords(directory=home).kept([Path("/w/lup.git")])
    assert kept == [
        Record(source=ours, place=PurePosixPath("projects", "-w-lup-git-tree-dev")),
        Record(
            source=home / "file-history" / "s1",
            place=PurePosixPath("file-history", "s1"),
        ),
    ]


def test_claude_code_without_records_keeps_none(tmp_path: Path) -> None:
    assert ClaudeRecords(directory=tmp_path / "absent").kept([tmp_path]) == []


def test_codex_s_records_are_the_rollouts_whose_first_line_ran_under_the_repository(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    ours = sessions / "2026" / "10" / "17" / "rollout-a.jsonl"
    lines(ours, {"type": "session_meta", "payload": {"cwd": "/w/lup.git/tree/dev"}})
    lines(
        sessions / "2026" / "10" / "17" / "rollout-b.jsonl",
        {"type": "session_meta", "payload": {"cwd": "/w/other"}},
    )
    lines(sessions / "2026" / "10" / "17" / "rollout-c.jsonl", {"type": "turn"})
    kept = CodexRecords(home=tmp_path / ".codex").kept([Path("/w/lup.git")])
    assert kept == [
        Record(
            source=ours,
            place=PurePosixPath("sessions", "2026", "10", "17", "rollout-a.jsonl"),
        )
    ]


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
    hooks = TranscriptsHooks(
        module=Transcripts(), launch=registered, records=held, data=data
    )
    asyncio.run(hooks.keep(Moment(name="stopped")))
    assert (data / "claude" / "projects" / "p" / "s1.jsonl").is_file()
    [under] = held.asked
    assert under[0] == repo / ".git"
    assert repo in under
