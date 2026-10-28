"""Each runtime's records of a repository's sessions: which of them are the repository's, and what a running session's runtime holds queued for each of its conversations.

The runtimes' homes here are directories the tests write, laid out as Claude Code
and Codex lay out their own: no test reads the operator's. Keeping a copy of them
is `Transcripts`' (`packages/lup-transcripts/tests/`).
"""

import json
from pathlib import Path, PurePosixPath

from lup_dev.adapters.claude import ClaudeQueues, ClaudeRecords
from lup_dev.adapters.codex import CodexRecords
from lup_dev.host.records import Queued, Record
from lup_dev.layout import HomesLayout


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


# What Claude Code holds queued for each conversation of a running session, as
# its records say (`ClaudeQueues`): the shapes measured on 2.1.311.


def queued_line(operation: str, content: str | None = None) -> dict[str, object]:
    line: dict[str, object] = {
        "type": "queue-operation",
        "operation": operation,
        "timestamp": "2026-10-27T22:07:56.729Z",
        "sessionId": "s1",
    }
    if content is not None:
        line["content"] = content
    return line


def started_line(call: str, **result: object) -> dict[str, object]:
    """A call's result line, saying what the call started in the background."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call, "content": ""}],
        },
        "toolUseResult": result,
    }


def notified(task: str, summary: str, call: str | None = None) -> str:
    called = "" if call is None else f"<tool-use-id>{call}</tool-use-id>\n"
    return (
        f"<task-notification>\n<task-id>{task}</task-id>\n{called}"
        f"<output-file>/tmp/{task}.output</output-file>\n<status>completed</status>\n"
        f"<summary>{summary}</summary>\n</task-notification>"
    )


def append(path: Path, *records: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as written:
        written.writelines(f"{json.dumps(each)}\n" for each in records)


def test_the_operator_s_typed_words_are_queued_for_the_session_s_own_conversation_alone(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    session = home / "projects" / "-w" / "s1.jsonl"
    append(session, queued_line("enqueue", "Stop the gate, it hangs."))
    append(session.with_suffix("") / "subagents" / "agent-a1.jsonl", {"type": "user"})
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    main = queues.queued("s1", None)
    worker = queues.queued("s1", "a1")
    assert main == [Queued(id="0", kind="typed")]
    assert worker == []


def test_what_was_absorbed_handed_or_taken_back_to_edit_is_no_longer_queued(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    session = home / "projects" / "-w" / "s1.jsonl"
    gate = notified("b1", 'Background command "gate" completed (exit code 0)', "c1")
    append(
        session,
        started_line("c1", backgroundTaskId="b1"),
        queued_line("enqueue", gate),
        queued_line("remove", gate),
        queued_line("enqueue", "First words."),
        queued_line("dequeue"),
        queued_line("enqueue", "Words to edit."),
        queued_line("popAll", "Words to edit."),
    )
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    assert queues.queued("s1", None) == []


def test_a_task_is_queued_for_the_conversation_whose_call_started_it(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    session = home / "projects" / "-w" / "s1.jsonl"
    worker = session.with_suffix("") / "subagents" / "agent-a1.jsonl"
    append(
        session,
        started_line("c1", agentId="a1"),
        started_line("c2", taskId="m1"),
    )
    append(worker, {**started_line("c3", backgroundTaskId="b1"), "isSidechain": True})
    gate = 'Background command "gate" completed (exit code 0)'
    watched = 'Monitor event: "the gate\'s log"'
    append(
        session,
        queued_line("enqueue", notified("b1", gate, "c3")),
        queued_line("enqueue", notified("m1", watched)),
        queued_line("enqueue", notified("a1", 'Agent "worker" finished', "c1")),
        queued_line("enqueue", notified("x1", "Another's", "c9")),
    )
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    main = queues.queued("s1", None)
    theirs = queues.queued("s1", "a1")
    assert [(each.kind, each.summary) for each in main] == [
        ("task", watched),
        ("subagent", 'Agent "worker" finished'),
    ]
    assert [(each.kind, each.summary) for each in theirs] == [("task", gate)]


def test_a_subagent_s_report_and_another_session_s_message_are_the_session_s_own(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    session = home / "projects" / "-w" / "s1.jsonl"
    append(
        session,
        queued_line(
            "enqueue",
            '<agent-message from="a1">\n[Subagent hand-back] Done.\n</agent-message>',
        ),
        queued_line(
            "enqueue",
            '<cross-session-message from="uds:/s" from-name="main-09">\nHi.\n'
            "</cross-session-message>",
        ),
        queued_line(
            "enqueue",
            '<channel source="lup" wake="t1">\n<note item="7"/>\n</channel>',
        ),
    )
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    main = queues.queued("s1", None)
    assert [(each.kind, each.summary) for each in main] == [
        ("subagent", None),
        ("message", "from main-09"),
    ]
    assert queues.queued("s1", "a1") == []


def test_each_look_reads_what_the_record_gained_and_a_line_once_it_s_whole(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    session = home / "projects" / "-w" / "s1.jsonl"
    append(session, {"type": "user"})
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    before = queues.queued("s1", None)
    line = json.dumps(queued_line("enqueue", "Hello."))
    with session.open("a") as written:
        written.write(line[:20])
    partway = queues.queued("s1", None)
    with session.open("a") as written:
        written.write(f"{line[20:]}\n")
    whole = queues.queued("s1", None)
    assert before == []
    assert partway == []
    assert [each.kind for each in whole] == ["typed"]


def test_nothing_is_queued_for_a_session_whose_record_isn_t_here(
    tmp_path: Path,
) -> None:
    queues = ClaudeQueues(records=ClaudeRecords(directory=tmp_path / "absent"))
    assert queues.queued("s1", None) == []


def test_a_record_gone_from_where_it_was_found_is_looked_for_again(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    first = home / "projects" / "-w" / "s1.jsonl"
    append(first, {"type": "user"})
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    before = queues.queued("s1", None)
    moved = home / "projects" / "-x" / "s1.jsonl"
    moved.parent.mkdir(parents=True)
    first.rename(moved)
    append(moved, queued_line("enqueue", "Still here?"))
    after = queues.queued("s1", None)
    assert before == []
    assert [each.kind for each in after] == ["typed"]


def test_a_launched_session_s_record_is_read_from_its_room_s_home_and_no_link_out_of_it(
    tmp_path: Path,
) -> None:
    homes = HomesLayout(home=tmp_path / "homes")
    operators = tmp_path / ".claude"
    room = homes.project(tmp_path / "work" / ".git", "claude")
    launched = room / "projects" / "-work" / "s1.jsonl"
    launched.parent.mkdir(parents=True)
    launched.write_text("{}\n")
    subagent = room / "projects" / "-work" / "s1" / "subagents" / "agent-a1.jsonl"
    subagent.parent.mkdir(parents=True)
    subagent.write_text("{}\n")
    host = operators / "projects" / "-work" / "s0.jsonl"
    host.parent.mkdir(parents=True)
    host.write_text("{}\n")
    (room / "projects" / "-work" / "s0.jsonl").symlink_to(host)
    elsewhere = tmp_path / "secret.jsonl"
    elsewhere.write_text("{}\n")
    (room / "projects" / "-work" / "s2.jsonl").symlink_to(elsewhere)
    records = ClaudeRecords(directory=operators, homes=homes)

    assert records.conversation("s1", None) == launched
    assert records.conversation("s1", "a1") == subagent
    assert records.conversation("s0", None) == host
    assert records.conversation("s2", None) is None
    assert ClaudeRecords(directory=operators).conversation("s1", None) is None


def test_a_launched_codex_thread_s_rollout_is_read_from_its_room_s_home(
    tmp_path: Path,
) -> None:
    homes = HomesLayout(home=tmp_path / "homes")
    shared = homes.shared("codex")
    rollout = shared / "sessions" / "2026" / "10" / "28" / "rollout-x-t1.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n")
    (shared / "sessions" / "2026" / "10" / "28" / "rollout-x-t2.jsonl").symlink_to(
        tmp_path / "nowhere.jsonl"
    )

    records = CodexRecords(home=tmp_path / ".codex", homes=homes)

    assert records.conversation("t1", None) == rollout
    assert records.conversation("s", "t1") == rollout
    assert records.conversation("t2", None) is None
