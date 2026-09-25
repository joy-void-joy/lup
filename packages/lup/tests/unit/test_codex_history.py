"""Codex history, listings and forks, asked of the app-server that keeps them.

The thread read here is the one measured from ``codex app-server`` 0.156.1
with ``thread/read`` and ``includeTurns: true``, saved whole: a turn is its
items, and each item reads back as the message a live turn made of it.
"""

import json
from pathlib import Path

import pytest

import lup.providers.codex.runtime as runtime
from lup.providers.codex import Codex
from lup.providers.codex.app_server import CodexAppServer
from lup.providers.codex.app_server import RpcNotification
from lup.providers.codex.runtime import (
    CodexConversationState,
    CodexRecord,
    CodexTurnChannel,
)
from lup.sessions.events import SessionId, TurnId, TurnTextBlock
from lup.types import EnvVars, JsonObject, JsonValue

THREAD = json.loads(
    (
        Path(__file__).parent / "fixtures" / "codex" / "thread-read-with-turns.json"
    ).read_text(encoding="utf-8")
)
THREAD_ID = "01a0d654-8892-7203-8a7d-d61383130d4e"


def answering(
    state: CodexConversationState,
    answers: dict[str, JsonValue],
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, JsonObject]]:
    """Answer each app-server method from ``answers``, remembering every request."""
    asked: list[tuple[str, JsonObject]] = []

    async def request(method: str, params: JsonObject) -> JsonValue:
        asked.append((method, params))
        return answers[method]

    monkeypatch.setattr(state.server, "request", request)
    return asked


def thread_state(tmp_path: Path, **fields: str) -> CodexConversationState:
    config = Codex(cwd=tmp_path)
    return CodexConversationState(
        config,
        CodexAppServer(Path("codex")),
        SessionId(value=fields["resume"]) if "resume" in fields else None,
    )


async def test_a_thread_reads_back_as_the_messages_its_turns_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = thread_state(tmp_path)
    state.thread_id = THREAD_ID
    asked = answering(state, {"thread/read": THREAD}, monkeypatch)

    messages = await CodexRecord(state).messages()

    assert asked == [("thread/read", {"threadId": THREAD_ID, "includeTurns": True})]
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].blocks == [
        TurnTextBlock(text="Reply with the single word: pong")
    ]
    assert messages[1].blocks == [TurnTextBlock(text="pong")]
    assert messages[1].native is not None
    assert CodexRecord(state).identity() == SessionId(value=THREAD_ID)


def test_a_thread_not_yet_started_answers_no_id(tmp_path: Path) -> None:
    """A session opens its thread before it is handed out, so this is an invariant."""
    with pytest.raises(RuntimeError, match="has not started its thread"):
        CodexRecord(thread_state(tmp_path)).identity()


async def test_a_fork_at_a_turn_asks_codex_to_keep_through_that_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = CodexConversationState(
        Codex(cwd=tmp_path),
        CodexAppServer(Path("codex")),
        None,
        fork_from=SessionId(value=THREAD_ID),
        fork_at=TurnId(value="turn-2"),
    )
    asked = answering(
        state,
        {"config/read": {"config": {}}, "thread/fork": {"thread": {"id": "t2"}}},
        monkeypatch,
    )

    assert await state.ensure_thread() == "t2"
    method, params = asked[-1]
    assert method == "thread/fork"
    assert params["threadId"] == THREAD_ID
    assert params["lastTurnId"] == "turn-2"


class ListingServer:
    """An app-server that pages its threads, recording how it was started."""

    started: list[EnvVars] = []
    pages: list[JsonObject] = []
    asked: list[JsonObject] = []

    def __init__(self, executable: Path, *, environment: EnvVars) -> None:
        self.environment = environment

    async def start(self) -> None:
        ListingServer.started.append(self.environment)

    async def close(self) -> None:
        return None

    async def request(self, method: str, params: JsonObject) -> JsonValue:
        assert method == "thread/list"
        ListingServer.asked.append(params)
        return ListingServer.pages[len(ListingServer.asked) - 1]


def listed(identity: str, updated: int, **fields: JsonValue) -> JsonObject:
    return {
        "id": identity,
        "preview": f"prompt of {identity}",
        "cwd": "/work",
        "createdAt": updated - 10,
        "updatedAt": updated,
        **fields,
    }


async def test_an_agent_lists_its_workspace_threads_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "codex-home"
    ListingServer.started, ListingServer.asked = [], []
    ListingServer.pages = [
        {"data": [listed("older", 100)], "nextCursor": "page-2"},
        {"data": [listed("newer", 200, name="Named thread")], "nextCursor": None},
    ]
    monkeypatch.setattr(runtime, "CodexAppServer", ListingServer)

    summaries = await Codex(
        cwd=tmp_path, environment={"CODEX_HOME": str(home)}
    ).sessions()

    assert [summary.id.value for summary in summaries] == ["newer", "older"]
    assert summaries[0].title == "Named thread"
    assert summaries[1].preview == "prompt of older"
    assert ListingServer.asked[0]["cwd"] == str(tmp_path)
    sources = ListingServer.asked[0]["sourceKinds"]
    assert isinstance(sources, list) and "subAgent" not in sources
    assert ListingServer.asked[1]["cursor"] == "page-2"
    assert ListingServer.started[0]["CODEX_HOME"] == str(home.resolve())


async def test_a_live_turn_keeps_its_prompt_in_the_transcript_not_its_blocks() -> None:
    """A turn's blocks are what it produced; the question is not one of them."""
    [turn] = THREAD["thread"]["turns"]
    channel = CodexTurnChannel(THREAD_ID)
    channel.turn_id = turn["id"]
    for item in turn["items"]:
        channel.feed(
            RpcNotification(
                method="item/completed",
                params={"threadId": THREAD_ID, "turnId": turn["id"], "item": item},
            )
        )

    assert channel.blocks == [TurnTextBlock(text="pong")]
    assert [
        message.role
        for event in channel.durable
        if (message := event.completed_message) is not None
    ] == ["user", "assistant"]
