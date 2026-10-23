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
    whole = views.found([other, TALK], ["LATER", "yes"], whole=True)
    missed = views.found([TALK], ["absent"])
    assert hit.startswith("`lup-impl` (claude c0fa70bc), ")
    assert "\n  answering: Two options:\n  you:\n    1->yes\n    2->later\n" in hit
    assert (
        "\n  answering:\n    Two options:\n    1. queue\n    2. agents\n  you:\n"
        "    1->yes\n    2->later\n"
    ) in whole
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
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    common = repository / ".git"
    data = Layout.of(LupDevSettings()).module_data(Transcripts.name, common.resolve())
    folder = data / "claude" / "projects" / "-repo"
    folder.mkdir(parents=True)
    (folder / "s1.jsonl").write_text("\n".join(CLAUDE_SESSION) + "\n")
    listed = runner.invoke(cli.app, ["transcripts", "list"])
    shown = runner.invoke(cli.app, ["transcripts", "show", "lup-impl"])
    found = runner.invoke(cli.app, ["transcripts", "search", "queue", "first"])
    whole = runner.invoke(
        cli.app, ["transcripts", "search", "queue", "first", "--whole"]
    )
    assert listed.exit_code == 0, listed.output
    assert "`lup-impl` (claude s1)  4 from you  in /w/lup.git/tree/dev" in listed.output
    assert "  you:\n    2->queue, yes\n" in shown.output
    assert (
        "  answering: Which do you want?\n  you:\n    Also, the queue first."
        in found.output
    )
    assert whole.exit_code == 0, whole.output
    assert (
        "  answering:\n    Which do you want?\n  you:\n    Also, the queue first."
        in whole.output
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


def test_claude_codes_record_reads_its_context_in_use_and_its_task_list(
    tmp_path: Path,
) -> None:
    """The context is the last reply's input, its cached parts included, in the window the operator's model chooses; the task list is replayed from the calls that wrote it, each task numbered by its result."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "opus[1m]"}))
    folder = tmp_path / "projects" / "-w"
    folder.mkdir(parents=True)

    def replied(*blocks: dict[str, object], usage: dict[str, int]) -> str:
        return line(
            type="assistant",
            message={
                "role": "assistant",
                "model": "claude-opus-4-1",
                "content": list(blocks),
                "usage": usage,
            },
        )

    def resulted(call: str, task: dict[str, str] | None = None) -> str:
        return line(
            type="user",
            message={
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": call, "content": "ok"}
                ],
            },
            **({} if task is None else {"toolUseResult": {"task": task}}),
        )

    def call(id_: str, name: str, **input_: object) -> dict[str, object]:
        return {"type": "tool_use", "id": id_, "name": name, "input": input_}

    (folder / "s1.jsonl").write_text(
        "\n".join(
            [
                human("Build it."),
                replied(
                    call(
                        "c1",
                        "TaskCreate",
                        subject="Write the sampler",
                        activeForm="Writing the sampler",
                    ),
                    usage={
                        "input_tokens": 2,
                        "cache_creation_input_tokens": 14149,
                        "cache_read_input_tokens": 8077,
                    },
                ),
                resulted("c1", {"id": "1", "subject": "Write the sampler"}),
                replied(
                    call("c2", "TaskCreate", subject="Write the models"),
                    usage={
                        "input_tokens": 1,
                        "cache_creation_input_tokens": 500,
                        "cache_read_input_tokens": 22226,
                    },
                ),
                resulted("c2", {"id": "2", "subject": "Write the models"}),
                replied(
                    call("c3", "TaskUpdate", taskId="1", status="in_progress"),
                    usage={
                        "input_tokens": 3,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 22726,
                    },
                ),
                resulted("c3"),
                # A call whose input doesn't read as its tool's is passed over.
                replied(
                    call("c4", "TaskUpdate", status="completed"),
                    usage={"input_tokens": 1},
                ),
                resulted("c4"),
            ]
        )
        + "\n"
    )
    reader = ClaudeTranscripts(settings=settings)
    read = reader.read(folder / "s1.jsonl")
    assert read.usage is not None
    assert (read.usage.used, read.usage.window, read.usage.model) == (
        1,
        1_000_000,
        "claude-opus-4-1",
    )
    assert [
        (each.id, each.subject, each.status, each.active) for each in read.tasks
    ] == [
        ("1", "Write the sampler", "in_progress", "Writing the sampler"),
        ("2", "Write the models", "pending", None),
    ]
    # `TodoWrite` replaces the list; a `TaskUpdate` to `deleted` takes a task off; no settings read no window.
    with (folder / "s1.jsonl").open("a") as grown:
        grown.write(
            replied(
                call(
                    "c5",
                    "TodoWrite",
                    todos=[
                        {
                            "content": "Smoke-test",
                            "status": "completed",
                            "activeForm": "Smoke-testing",
                        },
                        {"content": "Measure", "status": "pending"},
                    ],
                ),
                usage={"input_tokens": 40},
            )
            + "\n"
            + replied(
                call("c6", "TaskUpdate", taskId="1", status="deleted"),
                usage={"input_tokens": 41},
            )
            + "\n"
        )
    read = ClaudeTranscripts().read(folder / "s1.jsonl")
    assert [(each.id, each.subject, each.status) for each in read.tasks] == [
        ("2", "Measure", "pending")
    ]
    assert read.usage is not None
    assert (read.usage.used, read.usage.window) == (41, None)
    assert ClaudeTranscripts(settings=tmp_path / "none.json").model() is None


def test_codexs_rollout_reads_its_context_in_use_and_its_plan(tmp_path: Path) -> None:
    """The context is the last request's count but its reasoning, in the window the event names; the plan is the last `update_plan` call's, each step numbered in order."""
    day = tmp_path / "codex" / "sessions" / "2026" / "10" / "17"
    day.mkdir(parents=True)
    plan = {
        "plan": [
            {"step": "Read the records", "status": "completed"},
            {"step": "Write the reader", "status": "in_progress"},
        ]
    }
    (day / "rollout-2026-10-17T12-00-00-th-1.jsonl").write_text(
        "\n".join(
            [
                meta("th-1", "paginated"),
                rolled("turn_context", {"model": "gpt-5.1-codex", "cwd": "/w"}),
                rolled(
                    "response_item",
                    {
                        "type": "function_call",
                        "name": "update_plan",
                        "call_id": "c1",
                        "arguments": json.dumps(
                            {
                                "plan": [
                                    {
                                        "step": "Read the records",
                                        "status": "in_progress",
                                    }
                                ]
                            }
                        ),
                    },
                ),
                rolled(
                    "event_msg",
                    {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 9000,
                                "cached_input_tokens": 8000,
                                "output_tokens": 600,
                                "reasoning_output_tokens": 400,
                                "total_tokens": 9600,
                            },
                            "last_token_usage": {
                                "input_tokens": 9000,
                                "cached_input_tokens": 8000,
                                "output_tokens": 600,
                                "reasoning_output_tokens": 400,
                                "total_tokens": 9600,
                            },
                            "model_context_window": 272000,
                        },
                        "rate_limits": None,
                    },
                ),
                rolled(
                    "response_item",
                    {
                        "type": "function_call",
                        "name": "update_plan",
                        "call_id": "c2",
                        "arguments": json.dumps(plan),
                    },
                ),
                rolled(
                    "event_msg",
                    {"type": "token_count", "info": None, "rate_limits": None},
                ),
            ]
        )
        + "\n"
    )
    read = CodexTranscripts().read(day / "rollout-2026-10-17T12-00-00-th-1.jsonl")
    assert read.usage is not None
    assert (read.usage.used, read.usage.window, read.usage.model) == (
        9200,
        272000,
        "gpt-5.1-codex",
    )
    assert [
        (each.id, each.subject, each.status, each.active) for each in read.tasks
    ] == [
        ("1", "Read the records", "completed", None),
        ("2", "Write the reader", "in_progress", None),
    ]


def test_codexs_rollout_as_0_163_writes_it_reads_its_words_calls_and_context(
    tmp_path: Path,
) -> None:
    """Each line shaped as Codex 0.163.0 wrote this repository's kept rollouts, its values invented: the lines and keys lup doesn't read are passed over (`docs/field-notes.md`, *A thread's rollout*)."""
    passthrough = {"turn_id": "t1", "create_time": 1792571593.5}
    usage = {
        "input_tokens": 26471,
        "cached_input_tokens": 26112,
        "cache_write_input_tokens": 0,
        "output_tokens": 1165,
        "reasoning_output_tokens": 1034,
        "total_tokens": 27636,
    }
    lines: list[dict[str, object]] = [
        {
            "type": "session_meta",
            "payload": {
                "session_id": "th-1",
                "id": "th-1",
                "timestamp": AT,
                "cwd": "/w",
                "originator": "codex-tui",
                "cli_version": "0.163.0",
                "source": "cli",
                "model_provider": "openai",
                "base_instructions": {"text": "You are Codex."},
                "history_mode": "paginated",
                "context_window": {"window_id": "w1"},
                "git": {"commit_hash": "abc", "branch": "dev"},
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "m1",
                "role": "developer",
                "content": [{"type": "input_text", "text": "<permissions>"}],
                "internal_chat_message_metadata_passthrough": passthrough,
            },
            "metadata": {"client_authored": False},
        },
        {"type": "world_state", "payload": {"full": True, "state": {"model": "m"}}},
        {
            "type": "turn_context",
            "payload": {
                "turn_id": "t1",
                "cwd": "/w",
                "approval_policy": "never",
                "model": "gpt-6-astra",
                "effort": "high",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "m2",
                "role": "user",
                "content": [{"type": "input_text", "text": "go"}],
                "internal_chat_message_metadata_passthrough": passthrough,
            },
            "metadata": {"client_authored": False},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": "th-1",
                "turn_id": "t1",
                "item": {
                    "type": "UserMessage",
                    "id": "i1",
                    "client_id": "k1",
                    "content": [{"type": "text", "text": "go", "text_elements": []}],
                },
                "started_at_ms": 1792571593995,
                "completed_at_ms": 1792571593995,
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "id": "r1",
                "status": "completed",
                "call_id": "c1",
                "name": "exec",
                "input": "await tools.note({text: 'x'})",
                "internal_chat_message_metadata_passthrough": passthrough,
            },
        },
        # lup: defer(issue=268, why="a tool an `exec` cell calls is only this item, which lup doesn't read yet")
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": "th-1",
                "turn_id": "t1",
                "item": {
                    "type": "McpToolCall",
                    "id": "c2",
                    "server": "lup",
                    "tool": "note",
                    "status": "completed",
                    "duration": {"secs": 0, "nanos": 5},
                },
            },
        },
        {
            "type": "token_usage_record",
            "payload": {"thread_id": "th-1", "turn_id": "t1", "usage": usage},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "id": "r2",
                "call_id": "c1",
                "output": [{"type": "input_text", "text": "ok"}],
                "internal_chat_message_metadata_passthrough": passthrough,
            },
            "metadata": {"client_authored": False},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": usage,
                    "last_token_usage": usage,
                    "model_context_window": 258400,
                },
                "rate_limits": {"limit_id": "l1", "primary": {"used_percent": 0.0}},
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "status": "completed",
                "id": "r3",
                "name": "spawn_agent",
                "namespace": "collaboration",
                "arguments": "{}",
                "call_id": "c3",
                "internal_chat_message_metadata_passthrough": passthrough,
            },
            "metadata": {"client_authored": False, "user_input_order": 2},
        },
        {
            "type": "inter_agent_communication_metadata",
            "payload": {"trigger_turn": False},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "agent_message",
                "id": "r4",
                "author": "/root/scout",
                "recipient": "/root",
                "content": [{"type": "input_text", "text": "found it"}],
                "internal_chat_message_metadata_passthrough": passthrough,
            },
            "metadata": {"client_authored": False},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": "th-1",
                "turn_id": "t1",
                "item": {
                    "type": "AgentMessage",
                    "id": "i2",
                    "content": [{"type": "Text", "text": "Done."}],
                    "phase": "final_answer",
                },
            },
        },
    ]
    day = tmp_path / "codex" / "sessions" / "2026" / "10" / "21"
    day.mkdir(parents=True)
    rollout = day / "rollout-2026-10-21T10-33-01-th-1.jsonl"
    rollout.write_text(
        "\n".join(
            json.dumps({"timestamp": AT, "ordinal": at, **each})
            for at, each in enumerate(lines)
        )
        + "\n"
    )
    read = CodexTranscripts().read(rollout)
    when = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert (read.session, read.title, str(read.directory)) == ("th-1", None, "/w")
    assert read.entries == [
        Said(by="operator", text="go", at=when),
        Called(tool="exec", id="c1", at=when),
        Called(tool="collaborationspawn_agent", id="c3", at=when),
        Said(by="agent", text="Done.", at=when),
    ]
    assert read.usage is not None
    assert (read.usage.used, read.usage.window, read.usage.model) == (
        26602,
        258400,
        "gpt-6-astra",
    )
    assert read.tasks == []


def test_codexs_plan_call_as_0_145_writes_it_reads_its_last_steps(
    tmp_path: Path,
) -> None:
    """An `update_plan` call shaped as Codex 0.145.0 wrote it, the latest version a kept rollout calls it in: an `explanation` beside the plan, which lup passes over."""
    day = tmp_path / "codex" / "sessions" / "2026" / "07" / "26"
    day.mkdir(parents=True)
    rollout = day / "rollout-2026-07-26T06-18-50-th-1.jsonl"
    plan = {
        "explanation": "The reader is written; its tests are next.",
        "plan": [
            {"step": "Write the reader", "status": "completed"},
            {"step": "Test it", "status": "in_progress"},
            {"step": "Document it", "status": "pending"},
        ],
    }
    rollout.write_text(
        "\n".join(
            [
                meta("th-1", "paginated"),
                rolled(
                    "response_item",
                    {
                        "type": "function_call",
                        "id": "r1",
                        "name": "update_plan",
                        "arguments": json.dumps(plan),
                        "call_id": "c1",
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": "t1",
                            "create_time": 1785045530.5,
                        },
                    },
                ),
            ]
        )
        + "\n"
    )
    read = CodexTranscripts().read(rollout)
    assert [(each.id, each.subject, each.status) for each in read.tasks] == [
        ("1", "Write the reader", "completed"),
        ("2", "Test it", "in_progress"),
        ("3", "Document it", "pending"),
    ]
