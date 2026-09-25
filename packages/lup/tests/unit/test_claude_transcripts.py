"""Claude history and listings, read from the transcripts under the session's own home.

The records here are the shapes Claude Code writes — a prompt as a string, an
assistant message split into one record per block, tool results carrying
``is_error`` or not, titles as their own records, a rewound branch left in
the file. They are written under a configuration home this process's
environment does not name, because reading that home without touching the
environment is the property the Agent SDK's own readers lack.
"""

import json
from pathlib import Path

import pytest

from lup.providers.claude import Claude
from lup.providers.claude.login import CLAUDE_CONFIG_DIR
from lup.providers.claude.runtime import (
    ClaudeConversationState,
    ClaudeRecord,
    ClaudeSessionOpener,
)
from lup.providers.claude.transcripts import (
    PROJECT_NAME_LIMIT,
    ClaudeTranscripts,
    project_name,
)
from lup.sessions.events import (
    SessionId,
    TurnMessage,
    TurnTextBlock,
    TurnThinkingBlock,
    TurnToolCallBlock,
    TurnToolResultBlock,
)
from lup.types import JsonObject, JsonValue

SESSION = "3a500f80-0a48-48c0-b9e0-4aac1915ea53"
OTHER = "0d7d2205-b592-4810-b59c-4df32df76b1f"


def entry(
    kind: str,
    uuid: str,
    parent: str | None,
    content: JsonValue = None,
    **fields: str | bool,
) -> JsonObject:
    """One linked transcript record, in Claude Code's own spelling."""
    record: JsonObject = {
        "type": kind,
        "uuid": uuid,
        "parentUuid": parent,
        "isSidechain": False,
        "sessionId": SESSION,
        "cwd": "/work/project",
        "timestamp": "2026-09-25T02:29:23.328Z",
        **fields,
    }
    if content is not None:
        role = "assistant" if kind == "assistant" else "user"
        message: JsonObject = {"role": role, "content": content, "id": f"msg-{uuid}"}
        record["message"] = message
    return record


CONVERSATION: list[JsonObject] = [
    {"type": "queue-operation", "operation": "enqueue", "sessionId": SESSION},
    entry("user", "u1", None, "first prompt"),
    entry("attachment", "a1", "u1"),
    entry(
        "assistant",
        "m1",
        "a1",
        [{"type": "thinking", "thinking": "weighing it", "signature": "sig"}],
    ),
    entry(
        "assistant",
        "m2",
        "m1",
        [{"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"cmd": "ls"}}],
    ),
    entry(
        "user",
        "r1",
        "m2",
        [
            {
                "type": "tool_result",
                "tool_use_id": "call-1",
                "content": [{"type": "text", "text": "denied"}],
                "is_error": True,
            }
        ],
    ),
    entry("assistant", "m3", "r1", [{"type": "text", "text": "it was refused"}]),
    entry("user", "u2", "m3", "abandoned prompt"),
    entry("assistant", "m4", "u2", [{"type": "text", "text": "abandoned answer"}]),
    {"type": "ai-title", "aiTitle": "Generated title", "sessionId": SESSION},
    entry("user", "u3", "m3", "kept prompt"),
    entry("user", "x1", "u3", "caveat the CLI added", isMeta=True),
    entry("assistant", "m5", "x1", [{"type": "text", "text": "kept answer"}]),
    {"type": "custom-title", "customTitle": "Given title", "sessionId": SESSION},
    entry("user", "s1", "m3", "a subagent's prompt", isSidechain=True),
]


def write(home: Path, workspace: Path, session: str, records: list[JsonObject]) -> Path:
    directory = home / "projects" / project_name(workspace)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def test_history_is_the_branch_the_conversation_is_on_now(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "work"
    write(home, workspace, SESSION, CONVERSATION)

    messages = ClaudeTranscripts(home).conversation(SessionId(value=SESSION), workspace)

    assert messages is not None
    assert [(message.role, message.blocks) for message in messages] == [
        ("user", [TurnTextBlock(text="first prompt")]),
        (
            "assistant",
            [TurnThinkingBlock(thinking="weighing it", redacted=False)],
        ),
        (
            "assistant",
            [TurnToolCallBlock(id="call-1", name="Bash", arguments={"cmd": "ls"})],
        ),
        (
            "tool",
            [
                TurnToolResultBlock(
                    tool_call_id="call-1",
                    content='[{"type": "text", "text": "denied"}]',
                    is_error=True,
                )
            ],
        ),
        ("assistant", [TurnTextBlock(text="it was refused")]),
        ("user", [TurnTextBlock(text="kept prompt")]),
        ("assistant", [TurnTextBlock(text="kept answer")]),
    ]
    assert messages[1].message_id == "msg-m1"
    assert messages[3].blocks[0].refusal is not None


def test_a_listing_names_the_title_a_person_gave_and_the_first_prompt(
    tmp_path: Path,
) -> None:
    home, workspace = tmp_path / "home", tmp_path / "work"
    write(home, workspace, SESSION, CONVERSATION)
    write(home, workspace, OTHER, [entry("user", "s0", None, "x", isSidechain=True)])
    (home / "projects" / project_name(workspace) / "not-a-session.jsonl").write_text("")

    [summary] = ClaudeTranscripts(home).sessions(workspace)

    assert summary.id == SessionId(value=SESSION)
    assert summary.title == "Given title"
    assert summary.preview == "first prompt"
    assert summary.cwd == Path("/work/project")
    assert summary.created_at is not None


def test_a_session_that_moved_is_found_under_the_project_it_started_in(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    write(home, tmp_path / "started-here", SESSION, CONVERSATION)

    transcripts = ClaudeTranscripts(home)

    assert transcripts.transcript(SessionId(value=SESSION), tmp_path / "now-here")
    assert transcripts.conversation(SessionId(value=OTHER), tmp_path) is None


def test_an_id_claude_never_mints_names_no_transcript(tmp_path: Path) -> None:
    """Refused before any glob, so a wildcard cannot read another session."""
    home, workspace = tmp_path / "home", tmp_path / "work"
    write(home, workspace, SESSION, CONVERSATION)

    found = ClaudeTranscripts(home).transcript(SessionId(value="*"), workspace)

    assert found is None


def test_a_long_workspace_is_found_by_the_part_both_readers_agree_on(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / ("deep" * 60)
    named = project_name(workspace)
    assert len(named) > PROJECT_NAME_LIMIT
    home = tmp_path / "home"
    hashed = home / "projects" / f"{named[:PROJECT_NAME_LIMIT]}-cli1hash"
    hashed.mkdir(parents=True)
    (hashed / f"{SESSION}.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in CONVERSATION)
    )

    assert ClaudeTranscripts(home).project_directories(workspace) == [hashed]


def home_environment(home: Path) -> dict[str, str]:
    return {CLAUDE_CONFIG_DIR: str(home)}


async def test_a_session_reads_its_history_under_its_own_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process names a different home, and the session's own is what is read."""
    monkeypatch.setenv(CLAUDE_CONFIG_DIR, str(tmp_path / "somebody-else"))
    home, workspace = tmp_path / "home", tmp_path / "work"
    write(home, workspace, SESSION, CONVERSATION)
    config = Claude(cwd=workspace, environment=home_environment(home))
    state = ClaudeConversationState(
        ClaudeSessionOpener(config), config, SessionId(value=SESSION)
    )

    messages = await ClaudeRecord(state).messages()

    assert [message.role for message in messages][-2:] == ["user", "assistant"]
    assert all(isinstance(message, TurnMessage) for message in messages)


async def test_a_new_conversation_reads_empty_and_a_lost_one_refuses(
    tmp_path: Path,
) -> None:
    config = Claude(cwd=tmp_path, environment=home_environment(tmp_path / "home"))
    fresh = ClaudeConversationState(ClaudeSessionOpener(config), config, None)
    lost = ClaudeConversationState(
        ClaudeSessionOpener(config), config, SessionId(value=SESSION)
    )

    assert await ClaudeRecord(fresh).messages() == []
    with pytest.raises(LookupError, match="no transcript"):
        await ClaudeRecord(lost).messages()


async def test_an_agent_lists_its_workspace_under_its_own_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CLAUDE_CONFIG_DIR, str(tmp_path / "somebody-else"))
    home, workspace = tmp_path / "home", tmp_path / "work"
    write(home, workspace, SESSION, CONVERSATION)

    listed = await Claude(cwd=workspace, environment=home_environment(home)).sessions()

    assert [summary.id.value for summary in listed] == [SESSION]
