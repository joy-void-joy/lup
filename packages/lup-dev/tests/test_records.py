"""Each runtime's records of a repository's sessions: which of them are the repository's, and what a running session's runtime holds queued for each of its conversations.

The runtimes' homes here are directories the tests write, laid out as Claude Code
and Codex lay out their own: no test reads the operator's. Keeping a copy of them
is `Transcripts`' (`packages/lup-transcripts/tests/`).
"""

import json
import os
from pathlib import Path, PurePosixPath

from lup_dev.adapters.claude import ClaudeQueues, ClaudeRecords
from lup_dev.adapters.codex import CodexRecords
from lup_dev.host.homes import Found, kept
from lup_dev.host.records import Queued, Record, head
from lup_dev.layout import HomesLayout, HostLayout


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
    kept = ClaudeRecords(directory=home).kept([Path("/w/lup.git")], REPOSITORY)
    assert kept == [
        Record(
            home=home,
            whose="host",
            place=PurePosixPath("projects", "-w-lup-git-tree-dev"),
        ),
        Record(home=home, whose="host", place=PurePosixPath("file-history", "s1")),
    ]


def test_claude_code_without_records_keeps_none(tmp_path: Path) -> None:
    records = ClaudeRecords(directory=tmp_path / "absent")
    assert records.kept([tmp_path], REPOSITORY) == []


REPOSITORY = Path("/w/lup.git")
"""The repository whose records the tests keep, by its git directory."""


def test_each_home_s_records_are_kept_and_said_whose_home_they_re_in(
    tmp_path: Path,
) -> None:
    homes = HomesLayout(home=tmp_path / "homes")
    own = tmp_path / ".claude"
    rooms = homes.project(REPOSITORY, "claude")
    for home, session in [(own, "s1"), (rooms, "s2"), (homes.shared("claude"), "s3")]:
        lines(
            home / "projects" / "-w-lup-git-tree-dev" / f"{session}.jsonl",
            {"type": "user", "cwd": "/w/lup.git/tree/dev"},
        )
    another = homes.project(Path("/w/other.git"), "claude")
    lines(
        another / "projects" / "-w-lup-git-tree-dev" / "s4.jsonl",
        {"type": "user", "cwd": "/w/lup.git/tree/dev"},
    )
    kept = ClaudeRecords(directory=own, homes=homes).kept([REPOSITORY], REPOSITORY)
    assert [(each.whose, each.home) for each in kept] == [
        ("host", own),
        ("rooms", rooms),
        ("shared", homes.shared("claude")),
    ]


def test_a_record_reached_through_a_link_or_a_pipe_is_never_read(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    elsewhere = tmp_path / "elsewhere"
    lines(elsewhere / "s1.jsonl", {"type": "user", "cwd": "/w/lup.git/tree/dev"})
    (home / "projects").mkdir(parents=True)
    (home / "projects" / "-w-linked").symlink_to(elsewhere)
    folder = home / "projects" / "-w-lup-git-tree-dev"
    folder.mkdir()
    (folder / "s2.jsonl").symlink_to(elsewhere / "s1.jsonl")
    os.mkfifo(folder / "s3.jsonl")
    (home / "file-history").symlink_to(elsewhere)
    assert ClaudeRecords(directory=home).kept([REPOSITORY], REPOSITORY) == []
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)
    os.mkfifo(sessions / "rollout-a.jsonl")
    (sessions / "rollout-b.jsonl").symlink_to(elsewhere / "s1.jsonl")
    assert CodexRecords(home=sessions.parent).kept([REPOSITORY], REPOSITORY) == []


def test_a_home_whose_own_path_runs_through_a_link_is_read(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "claude"
    lines(
        real / "projects" / "-w-lup-git-tree-dev" / "s1.jsonl",
        {"type": "user", "cwd": "/w/lup.git/tree/dev"},
    )
    (tmp_path / ".claude").symlink_to(real)
    kept = ClaudeRecords(directory=tmp_path / ".claude").kept([REPOSITORY], REPOSITORY)
    assert [each.place for each in kept] == [
        PurePosixPath("projects", "-w-lup-git-tree-dev")
    ]


def test_a_record_s_head_is_read_only_so_far(tmp_path: Path) -> None:
    folder = tmp_path / "projects" / "-w-lup-git-tree-dev"
    folder.mkdir(parents=True)
    endless = '{"type": "mode", "pad": "' + "x" * 64 + '"}'
    (folder / "s1.jsonl").write_text(
        endless + "\n" + json.dumps({"type": "user", "cwd": "/w/lup.git"}) + "\n"
    )
    assert list(head(folder / "s1.jsonl", reach=32)) == [endless[:32]]
    assert len(list(head(folder / "s1.jsonl"))) == 2


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
    home = tmp_path / ".codex"
    kept = CodexRecords(home=home).kept([Path("/w/lup.git")], REPOSITORY)
    assert kept == [
        Record(
            home=home,
            whose="host",
            place=PurePosixPath("sessions", "2026", "10", "17", "rollout-a.jsonl"),
        )
    ]


def test_codex_keeps_each_home_s_rollouts_too(tmp_path: Path) -> None:
    homes = HomesLayout(home=tmp_path / "homes")
    rooms = homes.project(REPOSITORY, "codex")
    lines(
        rooms / "sessions" / "2026" / "10" / "28" / "rollout-a.jsonl",
        {"type": "session_meta", "payload": {"cwd": "/w/lup.git/tree/dev"}},
    )
    records = CodexRecords(home=tmp_path / ".codex", homes=homes)
    [kept] = records.kept([REPOSITORY], REPOSITORY)
    assert (kept.whose, kept.source) == (
        "rooms",
        rooms / "sessions" / "2026" / "10" / "28" / "rollout-a.jsonl",
    )


def test_a_folder_saying_it_ran_in_the_repository_under_another_directory_s_name_isn_t_its(
    tmp_path: Path,
) -> None:
    # Every room could write ~/.claude: a line naming the repository, written
    # first into another directory's folder, would have its sessions taken for
    # the repository's.
    home = tmp_path / ".claude"
    lines(
        home / "projects" / "-w-secret" / "0-planted.jsonl",
        {"type": "user", "cwd": "/w/lup.git/tree/dev"},
    )
    lines(
        home / "projects" / "-w-secret" / "s2.jsonl",
        {"type": "user", "cwd": "/w/secret"},
    )
    assert ClaudeRecords(directory=home).kept([REPOSITORY], REPOSITORY) == []


def test_a_long_directory_s_folder_is_its_by_the_name_claude_code_cuts(
    tmp_path: Path,
) -> None:
    directory = Path("/w/lup.git/tree") / ("b" * 220)
    folder = f"-w-lup-git-tree-{'b' * 184}-1x9k2a"
    home = tmp_path / ".claude"
    lines(home / "projects" / folder / "s1.jsonl", {"cwd": str(directory)})
    [kept] = ClaudeRecords(directory=home).kept([REPOSITORY], REPOSITORY)
    assert kept.place == PurePosixPath("projects", folder)


def test_a_record_that_s_a_pipe_or_a_link_is_passed_over_unread(tmp_path: Path) -> None:
    # A pipe would hold the read forever, and a link could aim it at any file
    # the host reads, /dev/zero among them.
    home = tmp_path / ".claude"
    ours = home / "projects" / "-w-lup-git-tree-dev"
    ours.mkdir(parents=True)
    os.mkfifo(ours / "0-pipe.jsonl")
    elsewhere = tmp_path / "elsewhere.jsonl"
    lines(elsewhere, {"cwd": "/w/other"})
    (ours / "1-link.jsonl").symlink_to(elsewhere)
    lines(ours / "s1.jsonl", {"cwd": "/w/lup.git/tree/dev"})
    [kept] = ClaudeRecords(directory=home).kept([REPOSITORY], REPOSITORY)
    assert kept.source == ours
    sessions = tmp_path / ".codex" / "sessions" / "2026" / "10" / "17"
    sessions.mkdir(parents=True)
    os.mkfifo(sessions / "rollout-pipe.jsonl")
    (sessions / "rollout-link.jsonl").symlink_to(elsewhere)
    assert CodexRecords(home=tmp_path / ".codex").kept([Path("/w")], REPOSITORY) == []


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
    main = queues.queued("s1", None, queues.records.directory)
    worker = queues.queued("s1", "a1", queues.records.directory)
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
    assert queues.queued("s1", None, queues.records.directory) == []


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
    main = queues.queued("s1", None, queues.records.directory)
    theirs = queues.queued("s1", "a1", queues.records.directory)
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
    main = queues.queued("s1", None, queues.records.directory)
    assert [(each.kind, each.summary) for each in main] == [
        ("subagent", None),
        ("message", "from main-09"),
    ]
    assert queues.queued("s1", "a1", queues.records.directory) == []


def test_each_look_reads_what_the_record_gained_and_a_line_once_it_s_whole(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    session = home / "projects" / "-w" / "s1.jsonl"
    append(session, {"type": "user"})
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    before = queues.queued("s1", None, queues.records.directory)
    line = json.dumps(queued_line("enqueue", "Hello."))
    with session.open("a") as written:
        written.write(line[:20])
    partway = queues.queued("s1", None, queues.records.directory)
    with session.open("a") as written:
        written.write(f"{line[20:]}\n")
    whole = queues.queued("s1", None, queues.records.directory)
    assert before == []
    assert partway == []
    assert [each.kind for each in whole] == ["typed"]


def test_nothing_is_queued_for_a_session_whose_record_isn_t_here(
    tmp_path: Path,
) -> None:
    queues = ClaudeQueues(records=ClaudeRecords(directory=tmp_path / "absent"))
    assert queues.queued("s1", None, queues.records.directory) == []


def test_a_record_gone_from_where_it_was_found_is_looked_for_again(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    first = home / "projects" / "-w" / "s1.jsonl"
    append(first, {"type": "user"})
    queues = ClaudeQueues(records=ClaudeRecords(directory=home))
    before = queues.queued("s1", None, queues.records.directory)
    moved = home / "projects" / "-x" / "s1.jsonl"
    moved.parent.mkdir(parents=True)
    first.rename(moved)
    append(moved, queued_line("enqueue", "Still here?"))
    after = queues.queued("s1", None, queues.records.directory)
    assert before == []
    assert [each.kind for each in after] == ["typed"]


def test_a_launched_session_s_record_is_read_from_its_launch_s_home_alone(
    tmp_path: Path,
) -> None:
    host = HostLayout(sockets=tmp_path / "run", state=tmp_path / "state")
    homes = HomesLayout(home=tmp_path / "homes")
    operators = tmp_path / ".claude"
    room = homes.project(tmp_path / "work" / ".git", "claude")
    other = homes.project(tmp_path / "other" / ".git", "claude")
    folder = room / "projects" / "-work"
    launched = folder / "s1.jsonl"
    subagent = folder / "s1" / "subagents" / "agent-a1.jsonl"
    subagent.parent.mkdir(parents=True)
    launched.write_text("{}\n")
    subagent.write_text("{}\n")
    kept(host, "claude", "s1", room)
    host_session = operators / "projects" / "-work" / "s0.jsonl"
    host_session.parent.mkdir(parents=True)
    host_session.write_text("{}\n")
    # A room plants records under the operator's session and another room's.
    (folder / "s0.jsonl").write_text('{"forged": true}\n')
    planted = other / "projects" / "-other"
    planted.mkdir(parents=True)
    (planted / "s1.jsonl").write_text('{"forged": true}\n')
    secret = tmp_path / "secret.jsonl"
    secret.write_text("{}\n")
    (folder / "s2.jsonl").symlink_to(secret)
    kept(host, "claude", "s2", room)
    records = ClaudeRecords(directory=operators, host=host)

    assert records.conversation("s1", None) == Found(record=launched, root=room)
    assert records.conversation("s1", "a1") == Found(record=subagent, root=room)
    assert records.conversation("s0", None) == Found(
        record=host_session, root=operators
    )
    assert records.conversation("s2", None) is None
    kept(host, "claude", "s1", other)
    assert records.conversation("s1", None) == Found(record=launched, root=room)


def test_a_launched_codex_thread_s_rollout_is_read_from_its_launch_s_home(
    tmp_path: Path,
) -> None:
    host = HostLayout(sockets=tmp_path / "run", state=tmp_path / "state")
    shared = HomesLayout(home=tmp_path / "homes").shared("codex")
    day = shared / "sessions" / "2026" / "10" / "28"
    rollout = day / "rollout-x-t1.jsonl"
    child = day / "rollout-x-c1.jsonl"
    day.mkdir(parents=True)
    rollout.write_text("{}\n")
    child.write_text("{}\n")
    (day / "rollout-x-t2.jsonl").symlink_to(tmp_path / "nowhere.jsonl")
    kept(host, "codex", "t1", shared)
    kept(host, "codex", "t2", shared)
    records = CodexRecords(home=tmp_path / ".codex", host=host)

    assert records.conversation("t1", None) == Found(record=rollout, root=shared)
    assert records.conversation("t1", "c1") == Found(record=child, root=shared)
    assert records.conversation("t2", None) is None
    assert records.conversation("t9", None) is None


def test_an_id_that_isn_t_a_plain_name_or_a_record_that_isn_t_a_file_finds_nothing(
    tmp_path: Path,
) -> None:
    host = HostLayout(sockets=tmp_path / "run", state=tmp_path / "state")
    room = HomesLayout(home=tmp_path / "homes").project(
        tmp_path / "w" / ".git", "claude"
    )
    folder = room / "projects" / "-work"
    folder.mkdir(parents=True)
    (folder / "s1.jsonl").write_text("{}\n")
    os.mkfifo(folder / "s2.jsonl")
    kept(host, "claude", "s2", room)
    kept(host, "claude", "*", room)
    records = ClaudeRecords(directory=room, host=host)
    rollouts = CodexRecords(home=tmp_path / ".codex", host=host)

    assert records.conversation("*", None) is None
    assert records.conversation("s1", "../../s1") is None
    assert records.conversation("s2", None) is None
    assert rollouts.conversation("*", None) is None
    assert not host.home_of("claude", "*").exists()


def test_a_line_too_long_to_hold_is_read_past_and_what_follows_is_queued(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".claude"
    session = home / "projects" / "-w" / "s1.jsonl"
    session.parent.mkdir(parents=True)
    long = json.dumps({"type": "user", "pad": "x" * 5000})
    session.write_text(f"{long}\n")
    append(session, queued_line("enqueue", "Hello."))
    queues = ClaudeQueues(records=ClaudeRecords(directory=home), largest=1024)

    queued = queues.queued("s1", None, queues.records.directory)

    assert queued == [Queued(id=str(len(long) + 1), kind="typed")]
