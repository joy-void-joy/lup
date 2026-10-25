"""Each runtime's records of a repository's sessions: which of them are the repository's.

The runtimes' homes here are directories the tests write, laid out as Claude Code
and Codex lay out their own: no test reads the operator's. Keeping a copy of them
is `Transcripts`' (`packages/lup-transcripts/tests/`).
"""

import json
from pathlib import Path, PurePosixPath

from lup_dev.adapters.claude import ClaudeRecords
from lup_dev.adapters.codex import CodexRecords
from lup_dev.host.records import Record


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
