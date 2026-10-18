"""Reading kept sessions: each runtime's records into transcripts, and the views `lup-dev transcripts` prints."""

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from lup.transcripts import views
from lup.transcripts.module import Transcripts
from lup_dev import cli
from lup_dev.adapters.claude import ClaudeRecords, ClaudeTranscripts
from lup_dev.adapters.codex import CodexRecords, CodexTranscripts
from lup_dev.host.records import Called, Entry, Said, Transcript
from lup_dev.inbox.context import moment
from lup_dev.layout import Layout
from lup_dev.settings import LupDevSettings

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import Shell

runner = CliRunner()

AT = "2026-10-17T12:00:00.000Z"


def line(**fields: object) -> str:
    return json.dumps({"timestamp": AT, **fields})


def human(text: str) -> str:
    return line(
        type="user",
        origin={"kind": "human"},
        promptSource="typed",
        cwd="/w/lup.git/tree/dev",
        message={"role": "user", "content": text},
    )


def agent(*blocks: dict[str, object]) -> str:
    return line(
        type="assistant", message={"role": "assistant", "content": list(blocks)}
    )


CLAUDE_SESSION = [
    json.dumps({"type": "permission-mode", "permissionMode": "default"}),
    human("Can we talk about the dashboard?"),
    agent({"type": "thinking", "thinking": "hm"}),
    agent({"type": "text", "text": "Yes. Two options:\n1. queue\n2. agents"}),
    agent({"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}),
    line(
        type="user",
        message={"role": "user", "content": [{"type": "tool_result", "content": "x"}]},
    ),
    agent({"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}),
    agent({"type": "tool_use", "name": "Read", "input": {"file_path": "/a"}}),
    agent({"type": "text", "text": "Which do you want?"}),
    line(
        type="user",
        message={
            "role": "user",
            "content": [{"type": "text", "text": "[Request interrupted by user]"}],
        },
    ),
    line(
        type="user",
        origin={"kind": "task-notification"},
        message={
            "role": "user",
            "content": "<task-notification>done</task-notification>",
        },
    ),
    line(
        type="user",
        isMeta=True,
        message={"role": "user", "content": "<local-command-caveat>x"},
    ),
    line(
        type="user",
        message={"role": "user", "content": "<command-name>/clear</command-name>"},
    ),
    line(
        type="user",
        message={
            "role": "user",
            "content": "An older release's words, with no origin.",
        },
    ),
    line(
        type="attachment",
        attachment={
            "type": "queued_command",
            "prompt": "Also, the queue first.",
            "commandMode": "prompt",
            "origin": {"kind": "human"},
        },
    ),
    line(
        type="attachment",
        attachment={
            "type": "queued_command",
            "prompt": "<task-notification>",
            "commandMode": "task-notification",
        },
    ),
    line(
        type="attachment",
        attachment={"type": "hook_additional_context", "content": ["lup: hi"]},
    ),
    json.dumps({"type": "ai-title", "aiTitle": "Dashboard talk", "sessionId": "s1"}),
    json.dumps({"type": "custom-title", "customTitle": "lup-impl", "sessionId": "s1"}),
    "not json",
    json.dumps({"type": "something-new", "field": 1}),
    human("2->queue, yes"),
]


@pytest.fixture
def copies(tmp_path: Path) -> Path:
    """Kept copies of Claude Code's records: one session of the repository, and a subagent's beside it."""
    root = tmp_path / "copies" / "claude"
    folder = root / "projects" / "-w-lup-git-tree-dev"
    (folder / "s1" / "subagents").mkdir(parents=True)
    (folder / "s1.jsonl").write_text("\n".join(CLAUDE_SESSION) + "\n")
    (folder / "s1" / "subagents" / "agent-a1.jsonl").write_text(human("not a session"))
    return root


def test_claude_codes_record_reads_as_the_operators_words_the_agents_and_its_tools(
    copies: Path,
) -> None:
    reader = ClaudeTranscripts()
    [record] = reader.sessions(copies)
    session = reader.read(record)
    at = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert record.name == "s1.jsonl"
    assert session.title == "lup-impl"
    assert str(session.directory) == "/w/lup.git/tree/dev"
    assert session.entries == [
        Said(by="operator", text="Can we talk about the dashboard?", at=at),
        Said(by="agent", text="Yes. Two options:\n1. queue\n2. agents", at=at),
        Called(tool="Bash", at=at),
        Called(tool="Bash", at=at),
        Called(tool="Read", at=at),
        Said(by="agent", text="Which do you want?", at=at),
        Said(by="operator", text="An older release's words, with no origin.", at=at),
        Said(by="operator", text="Also, the queue first.", at=at),
        Said(by="operator", text="2->queue, yes", at=at),
    ]
    assert ClaudeTranscripts().sessions(copies.parent / "none") == []


def session(
    entries: list[Said | Called], *, title: str | None = "lup-impl"
) -> Transcript:
    return Transcript(
        runtime="claude",
        session="c0fa70bc",
        title=title,
        entries=entries,
    )


def at(minute: int) -> datetime:
    return datetime(2026, 10, 17, 12, minute, tzinfo=UTC)


TALK = session(
    [
        Said(by="operator", text="Can we talk?", at=at(0)),
        Said(by="agent", text="Looking first.", at=at(1)),
        Called(tool="Read", at=at(1)),
        Called(tool="Read", at=at(1)),
        Said(by="agent", text="Two options:\n1. queue\n2. agents", at=at(2)),
        Said(by="operator", text="1->yes\n2->later", at=at(3)),
    ]
)


def test_answered_shows_each_of_the_operators_words_after_what_it_answered() -> None:
    shown = views.answered(TALK)
    assert "`lup-impl` (claude c0fa70bc)" in shown
    assert "(the session's first words)\n  you:\n    Can we talk?" in shown
    assert (
        "  answering the agent:\n    Two options:\n    1. queue\n    2. agents\n"
        "  you:\n    1->yes\n    2->later\n"
    ) in shown


def test_whole_folds_each_run_of_tool_calls_to_a_line() -> None:
    shown = views.whole(TALK)
    assert "the agent, " in shown
    assert "    Looking first.\n\n· called Read x2\n\nthe agent, " in shown


def test_found_gives_each_time_the_operator_said_every_word() -> None:
    other = session(
        [Said(by="operator", text="Nothing about it.", at=at(9))], title="other"
    )
    hit = views.found([other, TALK], ["LATER", "yes"])
    missed = views.found([TALK], ["absent"])
    assert hit.startswith("`lup-impl` (claude c0fa70bc), ")
    assert "\n  answering: Two options:\n  you:\n    1->yes\n    2->later\n" in hit
    assert "other" not in hit
    assert missed == "You never said 'absent' in a kept session.\n"


def test_a_session_is_chosen_by_its_id_its_ids_start_or_its_name() -> None:
    other = TALK.model_copy(update={"session": "c0ffee", "title": "other"})
    sessions = [TALK, other]
    assert views.chosen(sessions, "c0fa") == TALK
    assert views.chosen(sessions, "other") == other
    with pytest.raises(views.TranscriptError, match="several kept sessions are `c0f`"):
        views.chosen(sessions, "c0f")
    with pytest.raises(views.TranscriptError, match="no kept session is `zz`"):
        views.chosen(sessions, "zz")


def test_lup_dev_transcripts_reads_the_repositorys_kept_copies(
    tmp_path: Path, shell: Shell, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    shell.git(repository, "init", "--quiet")
    monkeypatch.chdir(repository)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    common = repository / ".git"
    data = Layout.of(LupDevSettings()).module_data(Transcripts.name, common.resolve())
    folder = data / "claude" / "projects" / "-repo"
    folder.mkdir(parents=True)
    (folder / "s1.jsonl").write_text("\n".join(CLAUDE_SESSION) + "\n")
    listed = runner.invoke(cli.app, ["transcripts", "list"])
    shown = runner.invoke(cli.app, ["transcripts", "show", "lup-impl"])
    found = runner.invoke(cli.app, ["transcripts", "search", "queue", "first"])
    assert listed.exit_code == 0, listed.output
    assert "`lup-impl` (claude s1)  4 from you  in /w/lup.git/tree/dev" in listed.output
    assert "  you:\n    2->queue, yes\n" in shown.output
    assert (
        "  answering: Which do you want?\n  you:\n    Also, the queue first."
        in found.output
    )


def rolled(type_: str, payload: dict[str, object]) -> str:
    return json.dumps({"timestamp": AT, "type": type_, "payload": payload})


def meta(thread: str, mode: str, parent: str | None = None) -> str:
    started: dict[str, object] = {
        "id": thread,
        "session_id": thread,
        "cwd": "/w",
        "history_mode": mode,
    }
    if parent is not None:
        started["parent_thread_id"] = parent
    return rolled("session_meta", started)


INJECTED = rolled(
    "response_item",
    {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}],
    },
)

LEGACY = [
    meta("th-1", "legacy"),
    INJECTED,
    rolled(
        "response_item",
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "fix it"}],
        },
    ),
    rolled("event_msg", {"type": "user_message", "message": "fix it", "images": []}),
    rolled(
        "response_item",
        {
            "type": "function_call",
            "name": "exec_command",
            "arguments": "{}",
            "call_id": "c1",
        },
    ),
    rolled(
        "response_item",
        {
            "type": "function_call",
            "name": "ask",
            "namespace": "mcp__lup__",
            "arguments": "{}",
            "call_id": "c2",
        },
    ),
    rolled(
        "response_item",
        {
            "type": "local_shell_call",
            "call_id": "c3",
            "action": {"type": "exec", "command": ["ls"]},
        },
    ),
    rolled(
        "response_item",
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Fixed."}],
        },
    ),
    rolled(
        "event_msg",
        {"type": "agent_message", "message": "Fixed.", "phase": "final_answer"},
    ),
    rolled(
        "event_msg",
        {
            "type": "thread_name_updated",
            "thread_id": "th-1",
            "thread_name": "fix-build",
        },
    ),
    rolled("turn_context", {"cwd": "/w"}),
]

PAGINATED = [
    meta("th-2", "paginated"),
    INJECTED,
    rolled(
        "event_msg",
        {
            "type": "item_completed",
            "item": {
                "type": "UserMessage",
                "content": [{"type": "text", "text": "hello", "text_elements": []}],
            },
        },
    ),
    rolled(
        "response_item",
        {
            "type": "custom_tool_call",
            "name": "apply_patch",
            "input": "*** Begin",
            "call_id": "c4",
        },
    ),
    rolled(
        "event_msg",
        {
            "type": "item_completed",
            "item": {
                "type": "AgentMessage",
                "content": [{"type": "Text", "text": "Hi."}],
                "phase": "final_answer",
            },
        },
    ),
    rolled(
        "event_msg",
        {"type": "item_completed", "item": {"type": "Reasoning", "summary_text": []}},
    ),
]


def test_codexs_rollouts_read_in_either_history_mode_a_subagents_left_out(
    tmp_path: Path,
) -> None:
    day = tmp_path / "codex" / "sessions" / "2026" / "10" / "17"
    day.mkdir(parents=True)
    (day / "rollout-2026-10-17T12-00-00-th-1.jsonl").write_text(
        "\n".join(LEGACY) + "\n"
    )
    (day / "rollout-2026-10-17T12-05-00-th-2.jsonl").write_text(
        "\n".join(PAGINATED) + "\n"
    )
    (day / "rollout-2026-10-17T12-06-00-th-3.jsonl").write_text(
        meta("th-3", "paginated", parent="th-2") + "\n"
    )
    reader = CodexTranscripts()
    legacy, paginated = [
        reader.read(each) for each in reader.sessions(tmp_path / "codex")
    ]
    when = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert legacy.session == "th-1"
    assert legacy.title == "fix-build"
    assert str(legacy.directory) == "/w"
    assert legacy.entries == [
        Said(by="operator", text="fix it", at=when),
        Called(tool="exec_command", id="c1", at=when),
        Called(tool="mcp__lup__ask", id="c2", at=when),
        Called(tool="shell", id="c3", at=when),
        Said(by="agent", text="Fixed.", at=when),
    ]
    assert paginated.title is None
    assert paginated.entries == [
        Said(by="operator", text="hello", at=when),
        Called(tool="apply_patch", id="c4", at=when),
        Said(by="agent", text="Hi.", at=when),
    ]


def test_claude_finds_one_conversations_record_and_reads_a_subagents_own_steps(
    tmp_path: Path,
) -> None:
    home = tmp_path / "claude"
    folder = home / "projects" / "-w-lup-git-tree-dev"
    (folder / "s1" / "subagents").mkdir(parents=True)
    (folder / "s1.jsonl").write_text(
        "\n".join(
            [
                human("Go."),
                agent(
                    {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}
                ),
            ]
        )
        + "\n"
    )
    subagent = folder / "s1" / "subagents" / "agent-a1.jsonl"
    looking: dict[str, object] = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Looking."},
            {"type": "tool_use", "id": "toolu_2", "name": "Grep", "input": {}},
        ],
    }
    subagent.write_text(
        line(type="assistant", isSidechain=True, message=looking) + "\n"
    )
    records = ClaudeRecords(directory=home)
    reader = ClaudeTranscripts()
    assert records.conversation("s1", None) == folder / "s1.jsonl"
    assert records.conversation("s1", "a1") == subagent
    assert records.conversation("s9", None) is None
    when = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert reader.read(folder / "s1.jsonl").entries[1] == Called(
        tool="Bash", id="toolu_1", at=when
    )
    assert reader.read(subagent).entries == [
        Said(by="agent", text="Looking.", at=when),
        Called(tool="Grep", id="toolu_2", at=when),
    ]


def test_codex_finds_a_threads_rollout_a_subagents_by_its_own_thread(
    tmp_path: Path,
) -> None:
    day = tmp_path / "codex" / "sessions" / "2026" / "10" / "17"
    day.mkdir(parents=True)
    own = day / "rollout-2026-10-17T12-00-00-th-1.jsonl"
    own.write_text(meta("th-1", "legacy") + "\n")
    spawned = day / "rollout-2026-10-17T12-01-00-th-3.jsonl"
    spawned.write_text(meta("th-3", "legacy", parent="th-1") + "\n")
    records = CodexRecords(home=tmp_path / "codex")
    assert records.conversation("th-1", None) == own
    assert records.conversation("th-1", "th-3") == spawned
    assert records.conversation("th-9", None) is None


def test_a_calls_moment_runs_from_the_operators_last_words_to_their_next() -> None:
    when = datetime(2026, 10, 17, 12, tzinfo=UTC)
    steps: list[Entry] = [
        Said(by="operator", text="First.", at=when),
        Called(tool="Bash", id="b1", at=when),
        Said(by="operator", text="Build it.", at=when),
        Said(by="agent", text="Reading.", at=when),
        Called(tool="mcp__lup__note", id="n1", at=when),
        Said(by="agent", text="Carrying on.", at=when),
        Said(by="operator", text="Next.", at=when),
    ]
    session = Transcript(runtime="claude", session="s1", entries=steps)
    found = moment(session, "n1")
    assert found is not None
    assert found.entries == steps[2:6]
    assert found.anchor == 2
    from_start = moment(
        Transcript(runtime="claude", session="s1", entries=steps[3:6]), "n1"
    )
    assert from_start is not None
    assert from_start.anchor == 1
    assert moment(session, "missing") is None
